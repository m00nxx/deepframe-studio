import subprocess

from deepframe_api.effects import EffectRegistry
from pathlib import Path

from deepframe_api.script_adapters import AviSynthAdapter, ScriptToolManager, VapourSynthAdapter, is_runtime_dependency_dir


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_vapoursynth_detect_reports_missing_tool():
    adapter = VapourSynthAdapter(vspipe_path=None, resolver=lambda _: None)

    detection = adapter.detect()

    assert detection["name"] == "vspipe"
    assert detection["engine"] == "vapoursynth"
    assert detection["detected"] is False


def test_vapoursynth_version_uses_vspipe_runner():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return FakeResult(stdout="VapourSynth Video Processing Library R70\n")

    adapter = VapourSynthAdapter(vspipe_path="/tools/vspipe", runner=runner)

    assert adapter.version() == "VapourSynth Video Processing Library R70"
    assert calls == [["/tools/vspipe", "--version"]]


def test_script_engine_version_timeout_returns_none():
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=5, output=b"partial")

    assert VapourSynthAdapter(vspipe_path="/tools/vspipe", runner=runner).version() is None
    assert AviSynthAdapter(tool_path="/tools/avs2yuv", runner=runner).version() is None


def test_vapoursynth_validation_runs_temp_script_when_tool_exists():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return FakeResult(returncode=0, stdout="ok\n")

    adapter = VapourSynthAdapter(vspipe_path="/tools/vspipe", runner=runner)

    result = adapter.validate_script("clip = None\n")

    assert result["available"] is True
    assert result["ok"] is True
    assert calls[0][0] == "/tools/vspipe"
    assert calls[0][1] == "--info"
    assert calls[0][2].endswith(".vpy")


def test_vapoursynth_validation_converts_temp_script_for_windows_vspipe():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return FakeResult(returncode=0, stdout="ok\n")

    adapter = VapourSynthAdapter(vspipe_path="/mnt/c/tools/VSPipe.exe", runner=runner)

    result = adapter.validate_script("clip = None\n")

    assert result["ok"] is True
    assert calls[0][2].startswith("C:\\")
    assert calls[0][2].endswith(".vpy")


def test_avisynth_validation_is_skipped_when_tool_is_missing():
    adapter = AviSynthAdapter(tool_path="", resolver=lambda _: None)

    result = adapter.validate_script("return BlankClip()\n")

    assert result["engine"] == "avisynth"
    assert result["available"] is False
    assert result["ok"] is False
    assert result["command"] == []


def test_avisynth_detect_reports_resolved_tool_name():
    adapter = AviSynthAdapter(tool_path=None, resolver=lambda name: "/tools/avs2pipemod" if name == "avs2pipemod" else None)

    detection = adapter.detect()
    result = adapter.validate_script("return BlankClip()\n")

    assert detection["name"] == "avs2pipemod"
    assert detection["path"] == "/tools/avs2pipemod"
    assert result["tool"] == "avs2pipemod"


def test_avisynth_validation_uses_avs2pipemod_info_syntax():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return FakeResult(returncode=0, stdout="ok\n")

    adapter = AviSynthAdapter(tool_path="/mnt/c/tools/avs2pipemod64.exe", runner=runner)

    result = adapter.validate_script("return BlankClip()\n")

    assert result["ok"] is True
    assert calls[0][0] == "/mnt/c/tools/avs2pipemod64.exe"
    assert any(part.startswith("-dll=") for part in calls[0])
    assert "-info" in calls[0]
    assert calls[0][-1].startswith("C:\\")


def test_avisynth_resolver_falls_back_to_bundled_avs2pipemod_when_present():
    adapter = AviSynthAdapter(tool_path=None, resolver=lambda _: None)

    if adapter.tool_path:
        assert adapter.tool_name == "avs2pipemod64"
        assert adapter.tool_path.endswith("vendor/staxrip/bundle/Apps/Support/avs2pipemod/avs2pipemod64.exe")


def test_script_validation_timeout_returns_json_safe_text():
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=20, output=b"partial stdout")

    result = VapourSynthAdapter(vspipe_path="/tools/vspipe", runner=runner).validate_script("clip = None\n")

    assert result["ok"] is False
    assert result["stdout"] == "partial stdout"
    assert result["stderr"] == "validation timed out"


def test_script_tool_manager_generates_and_validates_chain():
    registry = EffectRegistry.load_default()
    manager = ScriptToolManager(
        registry=registry,
        vapoursynth=VapourSynthAdapter(vspipe_path=None, resolver=lambda _: None),
        avisynth=AviSynthAdapter(tool_path="", resolver=lambda _: None),
    )

    result = manager.validate_chain(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "vs.knlmeanscl",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert "KNLMeansCL" in result["scripts"]["vapoursynth"]
    assert result["validations"]["vapoursynth"]["available"] is False
    assert result["validations"]["avisynth"]["available"] is False


def test_runtime_dependency_dirs_skip_python_site_packages_children():
    assert is_runtime_dependency_dir(Path("FrameServer/VapourSynth/Lib/site-packages/vsutil")) is False
    assert is_runtime_dependency_dir(Path("Apps/Plugins/VS/CAS")) is True
