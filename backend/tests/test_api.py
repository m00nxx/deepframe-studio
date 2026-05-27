from fastapi.testclient import TestClient

from deepframe_api.app import app
from deepframe_api.path_tools import runtime_dir


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_effects_endpoint_returns_sample_effects():
    response = client.get("/effects")

    assert response.status_code == 200
    ids = {effect["effect_id"] for effect in response.json()}
    assert {"vs.knlmeanscl", "vs.resize.bicubic"} <= ids


def test_media_thumbnail_endpoint_returns_data_url(monkeypatch):
    class FakeFFmpeg:
        def thumbnail_data_url(self, path, time_seconds=0):
            assert path == "input.mp4"
            assert time_seconds == 1.25
            return "data:image/png;base64,abc"

    monkeypatch.setattr("deepframe_api.app.ffmpeg", FakeFFmpeg())

    response = client.post("/media/thumbnail", json={"path": "input.mp4", "time_seconds": 1.25})

    assert response.status_code == 200
    assert response.json() == {"data_url": "data:image/png;base64,abc"}


def test_media_file_endpoint_serves_local_video(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")

    response = client.get("/media/file", params={"path": str(media)})

    assert response.status_code == 200
    assert response.content == b"video"


def test_media_file_endpoint_accepts_windows_paths_under_wsl(monkeypatch, tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    monkeypatch.setattr("deepframe_api.app.local_path", lambda path: str(media) if path == r"C:\Videos\clip.mp4" else path)

    response = client.get("/media/file", params={"path": r"C:\Videos\clip.mp4"})

    assert response.status_code == 200
    assert response.content == b"video"


def test_media_file_endpoint_rejects_unsupported_extension(tmp_path):
    media = tmp_path / "clip.txt"
    media.write_text("nope", encoding="utf-8")

    response = client.get("/media/file", params={"path": str(media)})

    assert response.status_code == 400


def test_script_validation_endpoint_returns_scripts_and_validation(monkeypatch):
    class FakeScriptTools:
        def validate_chain(self, media_path, effect_chain):
            assert media_path == "input.mp4"
            assert effect_chain[0]["effect_id"] == "vs.knlmeanscl"
            return {
                "scripts": {"vapoursynth": "vs script", "avisynth": "avs script"},
                "validations": {
                    "vapoursynth": {"engine": "vapoursynth", "available": False, "ok": False, "command": []},
                    "avisynth": {"engine": "avisynth", "available": False, "ok": False, "command": []},
                },
            }

    monkeypatch.setattr("deepframe_api.app.script_tools", FakeScriptTools())

    response = client.post(
        "/effects/chain/validate",
        json={
            "media_path": "input.mp4",
            "effect_chain": [
                {
                    "id": "chain-1",
                    "effect_id": "vs.knlmeanscl",
                    "enabled": True,
                    "parameters": {},
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["scripts"]["vapoursynth"] == "vs script"
    assert response.json()["validations"]["vapoursynth"]["available"] is False


def test_browser_preview_endpoint_returns_proxy_preview(monkeypatch):
    class FakeFFmpeg:
        def browser_preview(self, media_path, start_seconds, duration_seconds):
            assert media_path == "input.mov"
            assert start_seconds == 1.5
            assert duration_seconds == 12
            return {"path": "/tmp/preview.mp4", "command": ["ffmpeg"], "duration_seconds": 12}

    monkeypatch.setattr("deepframe_api.app.ffmpeg", FakeFFmpeg())

    response = client.post(
        "/media/browser-preview",
        json={"path": "input.mov", "start_seconds": 1.5, "duration_seconds": 12},
    )

    assert response.status_code == 200
    assert response.json()["path"].endswith("preview.mp4")


def test_frame_cache_endpoint_returns_frame_list(monkeypatch):
    class FakeFFmpeg:
        def frame_cache(self, media_path, start_seconds, duration_seconds, fps, width):
            assert media_path == "input.mp4"
            assert start_seconds == 2
            assert duration_seconds == 4
            assert fps == 15
            assert width == 1280
            return {
                "cache_id": "abc",
                "start_seconds": 2,
                "duration_seconds": 4,
                "fps": 15,
                "frames": [{"filename": "frame-00001.jpg", "time_seconds": 2}],
            }

    monkeypatch.setattr("deepframe_api.app.ffmpeg", FakeFFmpeg())

    response = client.post(
        "/media/frame-cache",
        json={"path": "input.mp4", "start_seconds": 2, "duration_seconds": 4, "fps": 15, "width": 1280},
    )

    assert response.status_code == 200
    assert response.json()["frames"][0]["filename"] == "frame-00001.jpg"


def test_preview_render_endpoint_returns_preview_file(monkeypatch):
    class FakeScriptTools:
        def generate_chain(self, media_path, effect_chain):
            assert media_path == "C:\\videos\\input.mp4"
            return {"vapoursynth": "clip = core.std.BlankClip()\nclip.set_output()\n", "avisynth": "return BlankClip()\n"}

    class FakePreviewRenderer:
        vspipe_path = "/mnt/c/tools/VSPipe.exe"

        def render_vapoursynth(self, base_script, in_point, duration_seconds, metadata):
            assert "BlankClip" in base_script
            assert in_point == 1
            assert duration_seconds == 2
            assert metadata["format"]["duration"] == "10"
            return {
                "path": "/tmp/deepframe-preview/preview.mp4",
                "script_path": "/tmp/deepframe-preview/preview.vpy",
                "engine": "vapoursynth",
                "command": ["vspipe", "|", "ffmpeg"],
                "duration_seconds": 2,
            }

    monkeypatch.setattr("deepframe_api.app.script_tools", FakeScriptTools())
    monkeypatch.setattr("deepframe_api.app.preview_renderer", FakePreviewRenderer())

    response = client.post(
        "/preview/render",
        json={
            "project": {
                "media_path": "/mnt/c/videos/input.mp4",
                "in_point": 1,
                "out_point": 8,
                "metadata_cache": {"format": {"duration": "10"}},
                "effect_chain": [],
            },
            "engine": "vapoursynth",
            "duration_seconds": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["path"].endswith("preview.mp4")
    assert response.json()["engine"] == "vapoursynth"


def test_preview_render_endpoint_supports_avisynth(monkeypatch):
    class FakeScriptTools:
        def generate_chain(self, media_path, effect_chain):
            assert media_path == "C:\\videos\\input.mp4"
            return {"vapoursynth": "clip.set_output()\n", "avisynth": "clip = BlankClip()\nreturn clip\n"}

    class FakePreviewRenderer:
        avisynth_path = "/mnt/c/tools/avs2pipemod64.exe"

        def render_avisynth(self, base_script, in_point, duration_seconds, metadata):
            assert "BlankClip" in base_script
            return {
                "path": "/tmp/deepframe-preview/preview-avs.mp4",
                "script_path": "/tmp/deepframe-preview/preview.avs",
                "engine": "avisynth",
                "command": ["avs2pipemod64", "|", "ffmpeg"],
                "duration_seconds": duration_seconds,
            }

    monkeypatch.setattr("deepframe_api.app.script_tools", FakeScriptTools())
    monkeypatch.setattr("deepframe_api.app.preview_renderer", FakePreviewRenderer())

    response = client.post(
        "/preview/render",
        json={
            "project": {
                "media_path": "/mnt/c/videos/input.mp4",
                "in_point": 0,
                "out_point": 1,
                "metadata_cache": {},
                "effect_chain": [],
            },
            "engine": "avisynth",
            "duration_seconds": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["engine"] == "avisynth"


def test_preview_file_endpoint_serves_rendered_preview():
    preview_file = runtime_dir("preview") / "unit-preview.mp4"
    preview_file.write_bytes(b"preview")

    response = client.get("/preview/files/unit-preview.mp4")

    assert response.status_code == 200
    assert response.content == b"preview"


def test_api_requires_local_token_when_configured(monkeypatch):
    monkeypatch.setenv("DEEPFRAME_API_TOKEN", "secret")

    denied = client.get("/health")
    allowed = client.get("/health", headers={"Authorization": "Bearer secret"})

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_export_job_endpoints_start_status_and_cancel(monkeypatch):
    class FakeJobs:
        def start_project(self, project):
            return {"job_id": "job-1", "state": "running", "percent": 0.0, "command": ["ffmpeg"]}

        def status(self, job_id):
            assert job_id == "job-1"
            return {"job_id": job_id, "state": "running", "percent": 0.5, "command": ["ffmpeg"]}

        def cancel(self, job_id):
            assert job_id == "job-1"
            return {"job_id": job_id, "state": "canceled", "percent": 0.5, "command": ["ffmpeg"]}

    monkeypatch.setattr("deepframe_api.app.export_jobs", FakeJobs())

    started = client.post(
        "/export/jobs",
        json={
            "media_path": "input.mp4",
            "in_point": 0,
            "out_point": 1,
            "output_settings": {"output_path": "output.mp4"},
        },
    )
    status = client.get("/export/jobs/job-1")
    canceled = client.post("/export/jobs/job-1/cancel")

    assert started.status_code == 200
    assert started.json()["job_id"] == "job-1"
    assert status.json()["percent"] == 0.5
    assert canceled.json()["state"] == "canceled"


def test_export_rejects_enabled_effect_chain_instead_of_silently_copying_original():
    response = client.post(
        "/export/jobs",
        json={
            "media_path": "input.mp4",
            "in_point": 0,
            "out_point": 1,
            "effect_chain": [{"id": "chain-1", "effect_id": "vs.std.boxblur", "enabled": True}],
            "output_settings": {"output_path": "output.mp4"},
        },
    )

    assert response.status_code == 501
    assert "Effect-chain export" in response.json()["detail"]


def test_export_job_status_unknown_id_returns_404(monkeypatch):
    class FakeJobs:
        def status(self, job_id):
            raise KeyError(job_id)

    monkeypatch.setattr("deepframe_api.app.export_jobs", FakeJobs())

    response = client.get("/export/jobs/missing")

    assert response.status_code == 404
