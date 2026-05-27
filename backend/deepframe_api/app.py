from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi import Depends, Header, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from deepframe_api import __version__
from deepframe_api.effects import EffectRegistry
from deepframe_api.ffmpeg import ExportJobManager, FFmpegAdapter
from deepframe_api.path_tools import local_path, runtime_dir, tool_path
from deepframe_api.preview import PreviewRenderer
from deepframe_api.script_adapters import ScriptToolManager
from deepframe_api.staxrip import DEFAULT_STAXRIP_INSTALL, DEFAULT_STAXRIP_SOURCE, scan_staxrip
from deepframe_api.models import (
    ChainScriptRequest,
    DeepFrameProject,
    BrowserPreviewRequest,
    FrameCacheRequest,
    MediaProbeRequest,
    MediaThumbnailRequest,
    NormalizeProjectRequest,
    PreviewRenderRequest,
)

def require_local_token(
    authorization: str | None = Header(default=None),
    access_token: str | None = Query(default=None),
) -> None:
    expected = os.environ.get("DEEPFRAME_API_TOKEN")
    if not expected:
        return
    if authorization != f"Bearer {expected}" and access_token != expected:
        raise HTTPException(status_code=401, detail="invalid local sidecar token")


app = FastAPI(
    title="DeepFrame Studio API",
    version=__version__,
    dependencies=[Depends(require_local_token)],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "tauri://localhost",
        "http://tauri.localhost",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["authorization", "content-type"],
)
ffmpeg = FFmpegAdapter()
export_jobs = ExportJobManager(ffmpeg)
effects = EffectRegistry.load_default()
script_tools = ScriptToolManager(effects)
preview_renderer = PreviewRenderer(ffmpeg_path=ffmpeg.ffmpeg_path or "ffmpeg")


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "version": __version__}


@app.get("/tools/detect")
def tools_detect() -> list[dict[str, object]]:
    detection = ffmpeg.detect()
    return [
        {
            "name": "ffmpeg",
            "detected": bool(detection.ffmpeg_path),
            "path": detection.ffmpeg_path or "ffmpeg",
            "version": detection.ffmpeg_version or "",
        },
        {
            "name": "ffprobe",
            "detected": bool(detection.ffprobe_path),
            "path": detection.ffprobe_path or "ffprobe",
            "version": "",
        },
        *script_tools.detect(),
    ]


@app.post("/media/probe")
def media_probe(request: MediaProbeRequest) -> dict[str, object]:
    try:
        return ffmpeg.probe(request.path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/media/thumbnail")
def media_thumbnail(request: MediaThumbnailRequest) -> dict[str, str]:
    try:
        return {"data_url": ffmpeg.thumbnail_data_url(request.path, request.time_seconds)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/media/frame-cache")
def media_frame_cache(request: FrameCacheRequest) -> dict[str, object]:
    try:
        return ffmpeg.frame_cache(
            media_path=request.path,
            start_seconds=request.start_seconds,
            duration_seconds=request.duration_seconds,
            fps=request.fps,
            width=request.width,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/media/frame-cache/{cache_id}/{filename}")
def media_frame_cache_file(cache_id: str, filename: str) -> FileResponse:
    if "/" in cache_id or "\\" in cache_id or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid frame cache path")
    path = runtime_dir("frame-cache") / cache_id / filename
    if not path.exists() or not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise HTTPException(status_code=404, detail="frame not found")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/media/file")
def media_file(path: str) -> FileResponse:
    media_path = Path(local_path(path))
    if not media_path.exists() or not media_path.is_file():
        raise HTTPException(status_code=404, detail="media file not found")
    if media_path.suffix.lower().lstrip(".") not in SUPPORTED_MEDIA_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported media file extension")
    return FileResponse(media_path)


@app.post("/media/browser-preview")
def media_browser_preview(request: BrowserPreviewRequest) -> dict[str, object]:
    try:
        return ffmpeg.browser_preview(
            media_path=request.path,
            start_seconds=request.start_seconds,
            duration_seconds=request.duration_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/export/command")
def export_command(request: DeepFrameProject) -> dict[str, list[str]]:
    try:
        reject_effect_export_if_needed(request)
        settings = request.output_settings
        preset = "copy" if settings.video_codec == "copy" and settings.audio_codec == "copy" else "h264"
        command = ffmpeg.build_export_command(
            input_path=request.media_path,
            output_path=settings.output_path,
            in_point=request.in_point,
            out_point=request.out_point,
            preset=preset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"command": command}


@app.post("/export/jobs")
def export_job_start(request: DeepFrameProject) -> dict[str, object]:
    try:
        reject_effect_export_if_needed(request)
        return export_jobs.start_project(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/export/jobs/{job_id}")
def export_job_status(job_id: str) -> dict[str, object]:
    try:
        return export_jobs.status(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/export/jobs/{job_id}/cancel")
def export_job_cancel(job_id: str) -> dict[str, object]:
    try:
        return export_jobs.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/projects/normalize")
def projects_normalize(request: NormalizeProjectRequest) -> dict[str, DeepFrameProject]:
    return {"project": request.project}


@app.get("/effects")
def effects_list() -> list[dict[str, object]]:
    return [effect.frontend_model() for effect in effects.list_effects()]


@app.post("/effects/chain/script")
def effects_chain_script(request: ChainScriptRequest) -> dict[str, str]:
    try:
        script = script_tools.generate_chain(
            media_path=request.media_path,
            effect_chain=[item.model_dump() for item in request.effect_chain],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return script


@app.post("/effects/chain/validate")
def effects_chain_validate(request: ChainScriptRequest) -> dict[str, object]:
    try:
        return script_tools.validate_chain(
            media_path=request.media_path,
            effect_chain=[item.model_dump() for item in request.effect_chain],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/preview/render")
def preview_render(request: PreviewRenderRequest) -> dict[str, object]:
    if not request.project.media_path:
        raise HTTPException(status_code=400, detail="media_path is required")
    try:
        if request.engine not in {"vapoursynth", "avisynth"}:
            raise ValueError("engine must be vapoursynth or avisynth")
        frameserver_path = preview_renderer.vspipe_path if request.engine == "vapoursynth" else preview_renderer.avisynth_path
        scripts = script_tools.generate_chain(
            media_path=tool_path(request.project.media_path, frameserver_path),
            effect_chain=[item.model_dump() for item in request.project.effect_chain],
        )
        if request.engine == "avisynth":
            return preview_renderer.render_avisynth(
                base_script=scripts["avisynth"],
                in_point=request.start_seconds if request.start_seconds is not None else request.project.in_point,
                duration_seconds=request.duration_seconds,
                metadata=request.project.metadata_cache,
            )
        return preview_renderer.render_vapoursynth(
            base_script=scripts["vapoursynth"],
            in_point=request.start_seconds if request.start_seconds is not None else request.project.in_point,
            duration_seconds=request.duration_seconds,
            metadata=request.project.metadata_cache,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/preview/files/{filename}")
def preview_file(filename: str) -> FileResponse:
    path = runtime_dir("preview") / Path(filename).name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="preview file not found")
    return FileResponse(path, media_type="video/mp4")


def reject_effect_export_if_needed(project: DeepFrameProject) -> None:
    if any(item.enabled for item in project.effect_chain):
        raise HTTPException(
            status_code=501,
            detail="Effect-chain export is not implemented yet. Use Preview to render a short processed range; final effect export is next.",
        )


SUPPORTED_MEDIA_EXTENSIONS = {
    "avi",
    "m2ts",
    "m4v",
    "mkv",
    "mov",
    "mp4",
    "mpeg",
    "mpg",
    "ts",
    "webm",
    "wmv",
}


@app.get("/integrations/staxrip/scan")
def integrations_staxrip_scan(source_file: str = str(DEFAULT_STAXRIP_SOURCE), install_root: str = str(DEFAULT_STAXRIP_INSTALL)) -> dict[str, object]:
    try:
        return scan_staxrip(source_file=Path(source_file), install_root=Path(install_root)).model_dump()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
