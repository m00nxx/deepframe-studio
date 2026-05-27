import subprocess
import threading
import time

from deepframe_api.ffmpeg import FFmpegAdapter, ExportJob, ExportJobManager, parse_progress


def test_build_trim_export_command_is_argument_list_and_keeps_paths_literal():
    adapter = FFmpegAdapter(ffmpeg_path="ffmpeg")

    command = adapter.build_export_command(
        input_path="/tmp/in video;rm.mp4",
        output_path="/tmp/out video.mp4",
        in_point=1.25,
        out_point=4.5,
        preset="h264",
    )

    assert command == [
        "ffmpeg",
        "-y",
        "-ss",
        "1.250",
        "-to",
        "4.500",
        "-i",
        "/tmp/in video;rm.mp4",
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
        "/tmp/out video.mp4",
    ]


def test_parse_progress_converts_ffmpeg_progress_lines():
    progress = parse_progress("frame=42\nout_time_ms=2500000\nprogress=continue\n")

    assert progress.frame == 42
    assert progress.out_time_seconds == 2.5
    assert progress.progress == "continue"


def test_build_export_command_can_enable_machine_progress_output():
    adapter = FFmpegAdapter(ffmpeg_path="ffmpeg")

    command = adapter.build_export_command(
        input_path="/tmp/in video.mp4",
        output_path="/tmp/out video.mp4",
        in_point=0,
        out_point=1,
        preset="copy",
        progress=True,
    )

    assert command[-4:] == ["-progress", "pipe:1", "-nostats", "/tmp/out video.mp4"]


def test_build_export_command_normalizes_windows_paths_for_wsl():
    adapter = FFmpegAdapter(ffmpeg_path="ffmpeg")

    command = adapter.build_export_command(
        input_path=r"C:\Videos\input.mp4",
        output_path=r"C:\Videos\out.mp4",
        preset="copy",
    )

    assert "/mnt/c/Videos/input.mp4" in command
    assert command[-1] == "/mnt/c/Videos/out.mp4"


def test_thumbnail_data_url_extracts_png_frame_with_ffmpeg():
    calls = []

    class FakeResult:
        returncode = 0
        stdout = b"\x89PNG\r\n"
        stderr = b""

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return FakeResult()

    adapter = FFmpegAdapter(ffmpeg_path="ffmpeg", runner=runner)

    thumbnail = adapter.thumbnail_data_url("/tmp/in video.mp4", time_seconds=1.25)

    assert thumbnail == "data:image/png;base64,iVBORw0K"
    assert calls[0][0] == [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        "1.250",
        "-i",
        "/tmp/in video.mp4",
        "-frames:v",
        "1",
        "-vf",
        "scale=1280:-2:force_original_aspect_ratio=decrease",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    assert calls[0][1]["text"] is False


def test_thumbnail_data_url_reports_ffmpeg_errors():
    class FakeResult:
        returncode = 1
        stdout = b""
        stderr = b"decode failed"

    adapter = FFmpegAdapter(ffmpeg_path="ffmpeg", runner=lambda *args, **kwargs: FakeResult())

    try:
        adapter.thumbnail_data_url("/tmp/broken.mp4")
    except RuntimeError as exc:
        assert "decode failed" in str(exc)
    else:
        raise AssertionError("thumbnail failure should raise RuntimeError")


def test_browser_preview_transcodes_to_browser_safe_mp4(tmp_path):
    calls = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return FakeResult()

    adapter = FFmpegAdapter(ffmpeg_path="ffmpeg", runner=runner)

    result = adapter.browser_preview(r"C:\Videos\input.mov", start_seconds=2.5, duration_seconds=12, output_dir=tmp_path)

    command = calls[0][0]
    assert result["path"].endswith(".mp4")
    assert command[command.index("-i") + 1] == "/mnt/c/Videos/input.mov"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert calls[0][1]["timeout"] == 180


def test_frame_cache_extracts_jpeg_sequence(tmp_path):
    calls = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        output_pattern = command[-1]
        frame_dir = tmp_path / output_pattern.split("/")[-2]
        frame_dir.mkdir(parents=True, exist_ok=True)
        (frame_dir / "frame-00001.jpg").write_bytes(b"jpg")
        (frame_dir / "frame-00002.jpg").write_bytes(b"jpg")
        return FakeResult()

    adapter = FFmpegAdapter(ffmpeg_path="ffmpeg", runner=runner)

    result = adapter.frame_cache("/tmp/input.mp4", start_seconds=1, duration_seconds=2, fps=12, width=960, output_dir=tmp_path)

    command = calls[0][0]
    assert command[command.index("-vf") + 1] == "fps=12,scale=960:-2:force_original_aspect_ratio=decrease"
    assert result["fps"] == 12
    assert [frame["filename"] for frame in result["frames"]] == ["frame-00001.jpg", "frame-00002.jpg"]


def test_export_job_manager_tracks_completed_progress():
    class FakePipe:
        def __init__(self, lines):
            self.lines = lines

        def __iter__(self):
            return iter(self.lines)

    class FakeProcess:
        def __init__(self):
            self.stdout = FakePipe(["frame=1\n", "out_time_ms=500000\n", "progress=continue\n", "frame=2\n", "out_time_ms=1000000\n", "progress=end\n"])
            self.stderr = FakePipe([])
            self.stdin = None
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    manager = ExportJobManager(FFmpegAdapter(ffmpeg_path="ffmpeg"), popen_factory=lambda *args, **kwargs: FakeProcess())

    started = manager.start_export(
        input_path="input.mp4",
        output_path="output.mp4",
        in_point=0,
        out_point=1,
        preset="copy",
    )
    completed = manager.wait(started["job_id"], timeout=2)

    assert completed["state"] == "completed"
    assert completed["progress"]["out_time_seconds"] == 1.0
    assert completed["percent"] == 1.0
    assert "-progress" in completed["command"]


def test_export_job_manager_cancels_running_process_gracefully():
    stop_event = threading.Event()
    written = []

    class BlockingStdout:
        def __iter__(self):
            yield "frame=1\n"
            yield "out_time_ms=100000\n"
            yield "progress=continue\n"
            stop_event.wait(2)

    class FakeStdin:
        def write(self, value):
            written.append(value)
            stop_event.set()

        def flush(self):
            return None

    class FakeProcess:
        def __init__(self):
            self.stdout = BlockingStdout()
            self.stderr = []
            self.stdin = FakeStdin()
            self.returncode = None

        def wait(self, timeout=None):
            if not stop_event.wait(timeout or 0):
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            self.returncode = 255
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 255
            stop_event.set()

        def kill(self):
            self.returncode = 255
            stop_event.set()

    manager = ExportJobManager(FFmpegAdapter(ffmpeg_path="ffmpeg"), popen_factory=lambda *args, **kwargs: FakeProcess())

    started = manager.start_export(input_path="input.mp4", output_path="output.mp4", in_point=0, out_point=10, preset="copy")
    time.sleep(0.05)
    canceled = manager.cancel(started["job_id"])
    completed = manager.wait(started["job_id"], timeout=2)

    assert written == ["q\n"]
    assert canceled["state"] == "canceled"
    assert completed["state"] == "canceled"


def test_export_job_manager_cancel_during_process_spawn_stops_process():
    spawn_started = threading.Event()
    release_spawn = threading.Event()
    stop_event = threading.Event()
    written = []

    class BlockingStdout:
        def __iter__(self):
            stop_event.wait(2)
            return iter(())

    class FakeStdin:
        def write(self, value):
            written.append(value)
            stop_event.set()

        def flush(self):
            return None

    class FakeProcess:
        def __init__(self):
            self.stdout = BlockingStdout()
            self.stderr = []
            self.stdin = FakeStdin()
            self.returncode = None

        def wait(self, timeout=None):
            if not stop_event.wait(timeout or 0):
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            self.returncode = 255
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 255
            stop_event.set()

        def kill(self):
            self.returncode = 255
            stop_event.set()

    def slow_spawn(*args, **kwargs):
        spawn_started.set()
        release_spawn.wait(2)
        return FakeProcess()

    manager = ExportJobManager(FFmpegAdapter(ffmpeg_path="ffmpeg"), popen_factory=slow_spawn)

    started = manager.start_export(input_path="input.mp4", output_path="output.mp4", in_point=0, out_point=1, preset="copy")
    assert spawn_started.wait(2)
    cancel_result = {}
    cancel_thread = threading.Thread(target=lambda: cancel_result.update(manager.cancel(started["job_id"])))
    cancel_thread.start()
    time.sleep(0.05)
    release_spawn.set()
    cancel_thread.join(2)
    completed = manager.wait(started["job_id"], timeout=2)

    assert written == ["q\n"]
    assert cancel_result["state"] == "canceled"
    assert completed["state"] == "canceled"


def test_export_job_manager_does_not_start_already_canceled_job():
    spawned = []
    manager = ExportJobManager(
        FFmpegAdapter(ffmpeg_path="ffmpeg"),
        popen_factory=lambda *args, **kwargs: spawned.append(True),
    )
    job = ExportJob(
        job_id="job-1",
        command=["ffmpeg"],
        duration_seconds=1,
        state="canceled",
        stderr_tail=[],
    )

    manager._run_job(job)

    assert job.state == "canceled"
    assert spawned == []
