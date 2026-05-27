from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from deepframe_api.path_tools import local_path, runtime_dir


@dataclass(frozen=True)
class ToolDetection:
    ffmpeg_path: str | None
    ffprobe_path: str | None
    ffmpeg_version: str | None
    detected_at: str


@dataclass(frozen=True)
class Progress:
    frame: int | None = None
    fps: float | None = None
    bitrate: str | None = None
    out_time_seconds: float | None = None
    speed: str | None = None
    progress: str | None = None


TERMINAL_JOB_STATES = {"completed", "failed", "canceled"}


@dataclass
class ExportJob:
    job_id: str
    command: list[str]
    duration_seconds: float | None
    state: str = "queued"
    percent: float = 0.0
    progress: Progress | None = None
    return_code: int | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    stderr_tail: list[str] | None = None
    process: subprocess.Popen[str] | None = None
    worker: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        progress = self.progress or Progress()
        return {
            "job_id": self.job_id,
            "state": self.state,
            "command": self.command,
            "duration_seconds": self.duration_seconds,
            "percent": self.percent,
            "progress": {
                "frame": progress.frame,
                "fps": progress.fps,
                "bitrate": progress.bitrate,
                "out_time_seconds": progress.out_time_seconds,
                "speed": progress.speed,
                "progress": progress.progress,
            },
            "return_code": self.return_code,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stderr_tail": self.stderr_tail or [],
        }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> float:
    parts = value.strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return float(value)


def parse_progress(output: str) -> Progress:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    out_time_seconds = None
    if "out_time_ms" in values:
        try:
            out_time_seconds = int(values["out_time_ms"]) / 1_000_000
        except ValueError:
            out_time_seconds = None
    elif "out_time" in values:
        try:
            out_time_seconds = parse_timestamp(values["out_time"])
        except ValueError:
            out_time_seconds = None

    return Progress(
        frame=int(values["frame"]) if values.get("frame", "").isdigit() else None,
        fps=parse_optional_float(values.get("fps")),
        bitrate=values.get("bitrate"),
        out_time_seconds=out_time_seconds,
        speed=values.get("speed"),
        progress=values.get("progress"),
    )


class FFmpegAdapter:
    def __init__(self, ffmpeg_path: str | None = None, ffprobe_path: str | None = None, runner: Any = subprocess.run):
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self.ffprobe_path = ffprobe_path or shutil.which("ffprobe")
        self.runner = runner

    def detect(self) -> ToolDetection:
        return ToolDetection(
            ffmpeg_path=self.ffmpeg_path,
            ffprobe_path=self.ffprobe_path,
            ffmpeg_version=self.version(),
            detected_at=utc_timestamp(),
        )

    def version(self) -> str | None:
        if not self.ffmpeg_path:
            return None
        result = self.runner(
            [self.ffmpeg_path, "-version"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.splitlines()[0] if result.stdout else None

    def probe(self, media_path: str) -> dict[str, Any]:
        if not self.ffprobe_path:
            raise RuntimeError("ffprobe not found")
        media_path = local_path(media_path)
        result = self.runner(
            [
                self.ffprobe_path,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                media_path,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        return json.loads(result.stdout or "{}")

    def build_export_command(
        self,
        input_path: str,
        output_path: str,
        in_point: float | None = None,
        out_point: float | None = None,
        preset: str = "copy",
        overwrite: bool = True,
        progress: bool = False,
    ) -> list[str]:
        if not input_path:
            raise ValueError("input_path is required")
        if not output_path:
            raise ValueError("output_path is required")
        if in_point is not None and out_point is not None and out_point < in_point:
            raise ValueError("out_point must be greater than or equal to in_point")

        input_path = local_path(input_path)
        output_path = local_path(output_path)
        command = [self.ffmpeg_path or "ffmpeg"]
        command.append("-y" if overwrite else "-n")
        if in_point is not None:
            command.extend(["-ss", format_seconds(in_point)])
        if out_point is not None:
            command.extend(["-to", format_seconds(out_point)])
        command.extend(["-i", input_path])
        command.extend(codec_args_for_preset(preset))
        if progress:
            command.extend(["-progress", "pipe:1", "-nostats"])
        command.append(output_path)
        return command

    def thumbnail_data_url(self, media_path: str, time_seconds: float = 0.0) -> str:
        if not self.ffmpeg_path:
            raise RuntimeError("ffmpeg not found")
        if not media_path:
            raise ValueError("media_path is required")
        media_path = local_path(media_path)
        result = self.runner(
            [
                self.ffmpeg_path,
                "-v",
                "error",
                "-ss",
                format_seconds(max(time_seconds, 0.0)),
                "-i",
                media_path,
                "-frames:v",
                "1",
                "-vf",
                "scale=1280:-2:force_original_aspect_ratio=decrease",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            check=False,
            capture_output=True,
            text=False,
            timeout=20,
        )
        if result.returncode != 0 or not result.stdout:
            stderr = decode_process_output(result.stderr)
            raise RuntimeError(stderr or "ffmpeg thumbnail extraction failed")
        encoded = base64.b64encode(result.stdout).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def frame_cache(
        self,
        media_path: str,
        start_seconds: float = 0.0,
        duration_seconds: float = 30.0,
        fps: float = 12.0,
        width: int = 960,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        if not self.ffmpeg_path:
            raise RuntimeError("ffmpeg not found")
        if not media_path:
            raise ValueError("media_path is required")

        media_path = local_path(media_path)
        start_seconds = max(start_seconds, 0.0)
        duration_seconds = max(duration_seconds, 0.1)
        fps = min(max(fps, 1.0), 30.0)
        width = min(max(width, 240), 1920)
        cache_key = hashlib.sha1(f"{media_path}|{start_seconds:.3f}|{duration_seconds:.3f}|{fps:.3f}|{width}".encode("utf-8")).hexdigest()[:24]
        output_root = output_dir or runtime_dir("frame-cache")
        cache_dir = output_root / cache_key
        frame_pattern = cache_dir / "frame-%05d.jpg"

        existing = sorted(cache_dir.glob("frame-*.jpg")) if cache_dir.exists() else []
        if not existing:
            cache_dir.mkdir(parents=True, exist_ok=True)
            command = [
                self.ffmpeg_path,
                "-y",
                "-v",
                "error",
                "-ss",
                format_seconds(start_seconds),
                "-t",
                format_seconds(duration_seconds),
                "-i",
                media_path,
                "-an",
                "-vf",
                f"fps={fps},scale={width}:-2:force_original_aspect_ratio=decrease",
                "-q:v",
                "4",
                str(frame_pattern),
            ]
            result = self.runner(command, check=False, capture_output=True, text=False, timeout=120)
            if result.returncode != 0:
                stderr = decode_process_output(result.stderr)
                raise RuntimeError(stderr or "ffmpeg frame cache extraction failed")
            existing = sorted(cache_dir.glob("frame-*.jpg"))

        if not existing:
            raise RuntimeError("ffmpeg frame cache produced no frames")

        frames = [
            {
                "filename": frame.name,
                "time_seconds": start_seconds + index / fps,
            }
            for index, frame in enumerate(existing)
        ]
        return {
            "cache_id": cache_key,
            "start_seconds": start_seconds,
            "duration_seconds": min(duration_seconds, len(existing) / fps),
            "fps": fps,
            "frames": frames,
        }

    def browser_preview(
        self,
        media_path: str,
        start_seconds: float = 0.0,
        duration_seconds: float = 30.0,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        if not self.ffmpeg_path:
            raise RuntimeError("ffmpeg not found")
        if not media_path:
            raise ValueError("media_path is required")

        output_root = output_dir or runtime_dir("preview")
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = output_root / f"browser-preview-{uuid.uuid4().hex}.mp4"
        command = [
            self.ffmpeg_path,
            "-y",
            "-v",
            "error",
            "-ss",
            format_seconds(max(start_seconds, 0.0)),
            "-t",
            format_seconds(duration_seconds),
            "-i",
            local_path(media_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            "scale=1280:-2:force_original_aspect_ratio=decrease",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = self.runner(command, check=False, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "browser preview generation failed")
        return {
            "path": str(output_path),
            "command": command,
            "duration_seconds": duration_seconds,
        }


class ExportJobManager:
    def __init__(self, adapter: FFmpegAdapter, popen_factory: Any = subprocess.Popen):
        self.adapter = adapter
        self.popen_factory = popen_factory
        self._jobs: dict[str, ExportJob] = {}
        self._lock = threading.Lock()

    def start_project(self, project: Any) -> dict[str, Any]:
        settings = project.output_settings
        preset = "copy" if settings.video_codec == "copy" and settings.audio_codec == "copy" else "h264"
        duration_seconds = project_duration_seconds(project)
        return self.start_export(
            input_path=project.media_path,
            output_path=settings.output_path,
            in_point=project.in_point,
            out_point=project.out_point,
            preset=preset,
            duration_seconds=duration_seconds,
        )

    def start_export(
        self,
        input_path: str,
        output_path: str,
        in_point: float | None = None,
        out_point: float | None = None,
        preset: str = "copy",
        duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        if duration_seconds is None and in_point is not None and out_point is not None and out_point > in_point:
            duration_seconds = out_point - in_point
        command = self.adapter.build_export_command(
            input_path=input_path,
            output_path=output_path,
            in_point=in_point,
            out_point=out_point,
            preset=preset,
            progress=True,
        )
        job = ExportJob(
            job_id=str(uuid.uuid4()),
            command=command,
            duration_seconds=duration_seconds,
            stderr_tail=[],
        )
        worker = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        job.worker = worker
        with self._lock:
            self._jobs[job.job_id] = job
        worker.start()
        return self.status(job.job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return self._get_job(job_id).snapshot()

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._get_job(job_id)
            if job.state in TERMINAL_JOB_STATES:
                return job.snapshot()
            job.state = "cancel_requested"
            process = job.process

        if process is not None and process.poll() is None:
            self._request_graceful_stop(process)
            try:
                process.wait(timeout=1)
            except TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except TimeoutExpired:
                    process.kill()

        with self._lock:
            job = self._get_job(job_id)
            if job.state not in TERMINAL_JOB_STATES:
                job.state = "canceled"
                job.finished_at = utc_timestamp()
            return job.snapshot()

    def wait(self, job_id: str, timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            job = self._get_job(job_id)
            worker = job.worker
        if worker is not None:
            worker.join(timeout=timeout)
        return self.status(job_id)

    def _get_job(self, job_id: str) -> ExportJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"export job not found: {job_id}") from exc

    def _run_job(self, job: ExportJob) -> None:
        with self._lock:
            if job.state in {"cancel_requested", "canceled"}:
                job.state = "canceled"
                job.finished_at = utc_timestamp()
                return
            job.state = "running"
            job.started_at = utc_timestamp()
            try:
                process = self.popen_factory(
                    job.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    shell=False,
                )
            except Exception as exc:
                job.state = "failed"
                job.error = str(exc)
                job.finished_at = utc_timestamp()
                return
            job.process = process

        stderr_thread = threading.Thread(target=self._drain_stderr, args=(job, process), daemon=True)
        stderr_thread.start()
        self._read_progress(job, process)
        return_code = process.wait()
        stderr_thread.join(timeout=0.2)

        with self._lock:
            job.return_code = return_code
            job.finished_at = utc_timestamp()
            if job.state in {"cancel_requested", "canceled"}:
                job.state = "canceled"
            elif return_code == 0:
                job.state = "completed"
                job.percent = 1.0
            else:
                job.state = "failed"
                if not job.error:
                    tail = "\n".join(job.stderr_tail or [])
                    job.error = tail or f"ffmpeg exited with code {return_code}"

    def _read_progress(self, job: ExportJob, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        block: list[str] = []
        for line in process.stdout:
            block.append(line)
            if line.startswith("progress="):
                progress = parse_progress("".join(block))
                block.clear()
                with self._lock:
                    job.progress = progress
                    if progress.out_time_seconds is not None and job.duration_seconds and job.duration_seconds > 0:
                        job.percent = max(0.0, min(progress.out_time_seconds / job.duration_seconds, 1.0))

    def _drain_stderr(self, job: ExportJob, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            with self._lock:
                tail = (job.stderr_tail or []) + [line.rstrip()]
                job.stderr_tail = tail[-20:]

    def _request_graceful_stop(self, process: subprocess.Popen[str]) -> None:
        if process.stdin is None:
            return
        try:
            process.stdin.write("q\n")
            process.stdin.flush()
        except OSError:
            return


def parse_optional_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def project_duration_seconds(project: Any) -> float | None:
    if project.out_point and project.out_point > project.in_point:
        return project.out_point - project.in_point
    try:
        duration = float(project.metadata_cache.get("format", {}).get("duration"))
    except (AttributeError, TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def format_seconds(value: float) -> str:
    return f"{value:.3f}"


def decode_process_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def codec_args_for_preset(preset: str) -> list[str]:
    normalized = preset.lower()
    if normalized == "copy":
        return ["-c", "copy"]
    if normalized in {"h264", "mp4", "default"}:
        return [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
    if normalized in {"prores", "mov"}:
        return ["-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le"]
    raise ValueError(f"unsupported export preset: {preset}")
