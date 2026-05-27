from pathlib import Path
from types import SimpleNamespace

from deepframe_api.preview import (
    PreviewRenderer,
    build_avisynth_preview_script,
    build_vapoursynth_preview_script,
    fps_from_metadata,
    tool_path,
)


def test_tool_path_converts_wsl_paths_for_windows_executables():
    assert tool_path("/mnt/c/videos/input clip.mp4", "/mnt/c/tools/VSPipe.exe") == "C:\\videos\\input clip.mp4"
    assert tool_path("/tmp/script.vpy", "/usr/bin/vspipe") == "/tmp/script.vpy"


def test_fps_from_metadata_uses_avg_frame_rate_fraction():
    metadata = {"streams": [{"codec_type": "video", "avg_frame_rate": "24000/1001"}]}

    assert round(fps_from_metadata(metadata), 3) == 23.976


def test_build_vapoursynth_preview_script_trims_frames_when_fps_is_known():
    script = build_vapoursynth_preview_script(
        base_script="clip = core.std.BlankClip(length=200)\nclip.set_output()\n",
        in_point=1.0,
        duration_seconds=2.0,
        metadata={"streams": [{"codec_type": "video", "avg_frame_rate": "25/1"}]},
    )

    assert "clip = clip[25:75]" in script
    assert script.rstrip().endswith("clip.set_output()")


def test_build_avisynth_preview_script_trims_frames_when_fps_is_known():
    script = build_avisynth_preview_script(
        base_script='clip = BlankClip(length=200)\nreturn clip\n',
        in_point=1.0,
        duration_seconds=2.0,
        metadata={"streams": [{"codec_type": "video", "avg_frame_rate": "25/1"}]},
    )

    assert "clip = clip.Trim(25, 74)" in script
    assert script.rstrip().endswith("return clip")


def test_preview_renderer_builds_vspipe_to_ffmpeg_command(tmp_path: Path):
    script_file = tmp_path / "preview.vpy"
    output_file = tmp_path / "preview.mp4"
    renderer = PreviewRenderer(ffmpeg_path="ffmpeg", vspipe_path="/mnt/c/tools/VSPipe.exe")

    command = renderer.build_vapoursynth_command(script_file, output_file)

    assert command.vspipe[:3] == ["/mnt/c/tools/VSPipe.exe", "--container", "y4m"]
    assert command.vspipe[-2:] == [tool_path(str(script_file), "/mnt/c/tools/VSPipe.exe"), "-"]
    assert command.ffmpeg[:5] == ["ffmpeg", "-y", "-v", "error", "-i"]
    assert command.ffmpeg[-1] == str(output_file)


def test_preview_renderer_streams_vspipe_stdout_to_ffmpeg(tmp_path: Path):
    calls = []
    stdout_pipe = SimpleNamespace(close=lambda: None)

    class FakeProcess:
        def __init__(self, command, stdout=None):
            self.command = command
            self.stdout = stdout
            self.stderr = b""

        def communicate(self, timeout=None):
            return b"", b""

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("process should not be killed")

    def popen_factory(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "/mnt/c/tools/VSPipe.exe":
            return FakeProcess(command, stdout=stdout_pipe)
        assert command[0] == "ffmpeg"
        assert kwargs["stdin"] is stdout_pipe
        return FakeProcess(command)

    renderer = PreviewRenderer(ffmpeg_path="ffmpeg", vspipe_path="/mnt/c/tools/VSPipe.exe", popen_factory=popen_factory)

    result = renderer.render_vapoursynth(
        base_script="clip = core.std.BlankClip(length=30)\nclip.set_output()\n",
        in_point=0,
        duration_seconds=1,
        metadata={"streams": [{"codec_type": "video", "avg_frame_rate": "30/1"}]},
        output_dir=tmp_path,
    )

    assert result["engine"] == "vapoursynth"
    assert calls[0][0][0] == "/mnt/c/tools/VSPipe.exe"
    assert calls[1][0][0] == "ffmpeg"


def test_preview_renderer_streams_avisynth_stdout_to_ffmpeg(tmp_path: Path):
    calls = []
    stdout_pipe = SimpleNamespace(close=lambda: None)

    class FakeProcess:
        def __init__(self, command, stdout=None):
            self.command = command
            self.stdout = stdout
            self.stderr = b""

        def communicate(self, timeout=None):
            return b"", b""

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("process should not be killed")

    def popen_factory(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "/mnt/c/tools/avs2pipemod64.exe":
            return FakeProcess(command, stdout=stdout_pipe)
        assert command[0] == "ffmpeg"
        assert kwargs["stdin"] is stdout_pipe
        return FakeProcess(command)

    renderer = PreviewRenderer(
        ffmpeg_path="ffmpeg",
        vspipe_path=None,
        avisynth_path="/mnt/c/tools/avs2pipemod64.exe",
        avisynth_dll_path="/mnt/c/tools/AviSynth.dll",
        popen_factory=popen_factory,
    )

    result = renderer.render_avisynth(
        base_script="clip = BlankClip(length=30)\nreturn clip\n",
        in_point=0,
        duration_seconds=1,
        metadata={"streams": [{"codec_type": "video", "avg_frame_rate": "30/1"}]},
        output_dir=tmp_path,
    )

    assert result["engine"] == "avisynth"
    assert calls[0][0][0] == "/mnt/c/tools/avs2pipemod64.exe"
    assert "-y4mp" in calls[0][0]
    assert calls[1][0][0] == "ffmpeg"
