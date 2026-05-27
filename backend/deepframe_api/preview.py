from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepframe_api.path_tools import project_root, runtime_dir, tool_path
from deepframe_api.script_adapters import AviSynthAdapter, VapourSynthAdapter, tool_env


DEFAULT_PREVIEW_DURATION = 5.0


@dataclass(frozen=True)
class PreviewCommand:
    vspipe: list[str]
    ffmpeg: list[str]


class PreviewRenderer:
    def __init__(
        self,
        ffmpeg_path: str | None = None,
        vspipe_path: str | None = None,
        avisynth_path: str | None = None,
        avisynth_dll_path: str | None = None,
        popen_factory: Any = subprocess.Popen,
    ):
        self.ffmpeg_path = ffmpeg_path or "ffmpeg"
        self.vspipe_path = vspipe_path or VapourSynthAdapter().vspipe_path
        self.avisynth_path = avisynth_path if avisynth_path is not None else AviSynthAdapter().tool_path
        self.avisynth_dll_path = avisynth_dll_path or resolve_avisynth_dll()
        self.popen_factory = popen_factory

    def build_vapoursynth_command(self, script_file: Path, output_file: Path) -> PreviewCommand:
        if not self.vspipe_path:
            raise RuntimeError("vspipe not found")
        return PreviewCommand(
            vspipe=[
                self.vspipe_path,
                "--container",
                "y4m",
                tool_path(str(script_file), self.vspipe_path),
                "-",
            ],
            ffmpeg=[
                self.ffmpeg_path,
                "-y",
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_file),
            ],
        )

    def build_avisynth_command(self, script_file: Path, output_file: Path) -> PreviewCommand:
        if not self.avisynth_path:
            raise RuntimeError("avs2pipemod not found")
        source_command = [self.avisynth_path]
        if self.avisynth_dll_path:
            source_command.append(f"-dll={tool_path(str(self.avisynth_dll_path), self.avisynth_path)}")
        source_command.extend(["-y4mp", tool_path(str(script_file), self.avisynth_path)])
        return PreviewCommand(
            vspipe=source_command,
            ffmpeg=[
                self.ffmpeg_path,
                "-y",
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_file),
            ],
        )

    def render_vapoursynth(
        self,
        base_script: str,
        in_point: float,
        duration_seconds: float,
        metadata: dict[str, Any],
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        if not self.vspipe_path:
            raise RuntimeError("vspipe not found")
        output_root = output_dir or runtime_dir("preview")
        output_root.mkdir(parents=True, exist_ok=True)
        script_path = output_root / f"preview-{uuid.uuid4().hex}.vpy"
        output_path = output_root / f"preview-{uuid.uuid4().hex}.mp4"
        script = build_vapoursynth_preview_script(base_script, in_point, duration_seconds, metadata)
        script_path.write_text(script, encoding="utf-8")
        command = self.build_vapoursynth_command(script_path, output_path)
        self._run_streaming_preview(command, Path(self.vspipe_path).parent)
        return {
            "path": str(output_path),
            "script_path": str(script_path),
            "engine": "vapoursynth",
            "command": command.vspipe + ["|", *command.ffmpeg],
            "duration_seconds": duration_seconds,
        }

    def render_avisynth(
        self,
        base_script: str,
        in_point: float,
        duration_seconds: float,
        metadata: dict[str, Any],
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        if not self.avisynth_path:
            raise RuntimeError("avs2pipemod not found")
        output_root = output_dir or runtime_dir("preview")
        output_root.mkdir(parents=True, exist_ok=True)
        script_path = output_root / f"preview-{uuid.uuid4().hex}.avs"
        output_path = output_root / f"preview-{uuid.uuid4().hex}.mp4"
        script = build_avisynth_preview_script(base_script, in_point, duration_seconds, metadata)
        script_path.write_text(script, encoding="utf-8")
        command = self.build_avisynth_command(script_path, output_path)
        self._run_streaming_preview(command, Path(self.avisynth_path).parent)
        return {
            "path": str(output_path),
            "script_path": str(script_path),
            "engine": "avisynth",
            "command": command.vspipe + ["|", *command.ffmpeg],
            "duration_seconds": duration_seconds,
        }

    def _run_streaming_preview(self, command: PreviewCommand, cwd: Path) -> None:
        source_process = None
        ffmpeg_process = None
        try:
            source_process = self.popen_factory(
                command.vspipe,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(cwd),
                env=tool_env(cwd),
            )
            ffmpeg_process = self.popen_factory(
                command.ffmpeg,
                stdin=source_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if source_process.stdout:
                source_process.stdout.close()
            _ffmpeg_stdout, ffmpeg_stderr = ffmpeg_process.communicate(timeout=90)
            source_stderr = read_stream(source_process.stderr)
            source_return = source_process.wait(timeout=5)
            ffmpeg_return = getattr(ffmpeg_process, "returncode", 0)
            if source_return != 0:
                raise RuntimeError(decode_bytes(source_stderr) or f"frameserver exited with code {source_return}")
            if ffmpeg_return != 0:
                raise RuntimeError(decode_bytes(ffmpeg_stderr) or f"ffmpeg exited with code {ffmpeg_return}")
        finally:
            if ffmpeg_process and ffmpeg_process.poll() is None:
                ffmpeg_process.kill()
            if source_process and source_process.poll() is None:
                source_process.kill()


def build_vapoursynth_preview_script(
    base_script: str,
    in_point: float,
    duration_seconds: float,
    metadata: dict[str, Any],
) -> str:
    lines = [line for line in base_script.splitlines() if line.strip() != "clip.set_output()"]
    frame_window = preview_frame_window(in_point, duration_seconds, metadata)
    if frame_window:
        start, end = frame_window
        lines.append(f"clip = clip[{start}:{end}]")
    lines.append("clip.set_output()")
    return "\n".join(lines) + "\n"


def build_avisynth_preview_script(
    base_script: str,
    in_point: float,
    duration_seconds: float,
    metadata: dict[str, Any],
) -> str:
    lines = [line for line in base_script.splitlines() if line.strip().lower() != "return clip"]
    frame_window = preview_frame_window(in_point, duration_seconds, metadata)
    if frame_window:
        start, end = frame_window
        lines.append(f"clip = clip.Trim({start}, {end - 1})")
    lines.append("return clip")
    return "\n".join(lines) + "\n"


def preview_frame_window(in_point: float, duration_seconds: float, metadata: dict[str, Any]) -> tuple[int, int] | None:
    fps = fps_from_metadata(metadata)
    if fps <= 0:
        return None
    start = max(0, int(round(in_point * fps)))
    end = max(start + 1, int(round((in_point + duration_seconds) * fps)))
    return start, end


def fps_from_metadata(metadata: dict[str, Any]) -> float:
    for stream in metadata.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        for key in ("avg_frame_rate", "r_frame_rate"):
            fps = parse_fraction(str(stream.get(key, "")))
            if fps > 0:
                return fps
    return 0.0


def parse_fraction(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            den = float(denominator)
            return float(numerator) / den if den else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def read_stream(stream: Any) -> bytes:
    if stream is None:
        return b""
    if isinstance(stream, bytes):
        return stream
    if isinstance(stream, str):
        return stream.encode("utf-8", errors="replace")
    if hasattr(stream, "read"):
        value = stream.read()
        return value if isinstance(value, bytes) else str(value).encode("utf-8", errors="replace")
    return b""


def resolve_avisynth_dll() -> str | None:
    dll = project_root() / "vendor" / "staxrip" / "bundle" / "Apps" / "FrameServer" / "AviSynth" / "AviSynth.dll"
    return str(dll) if dll.exists() else None


def decode_bytes(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")
