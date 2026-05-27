from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class Segment(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str | None = None
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    label: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "Segment":
        if self.end < self.start:
            raise ValueError("segment end must be greater than or equal to start")
        return self


class EffectChainItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    effect_id: str = ""
    name: str = ""
    engine: str = "vapoursynth"
    category: str = "custom"
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)


class OutputSettings(BaseModel):
    container: str = "mp4"
    video_codec: str = "copy"
    audio_codec: str = "copy"
    crf: int = 18
    preset: str = "medium"
    output_path: str = "output.mp4"


class DeepFrameProject(BaseModel):
    media_path: str = ""
    metadata_cache: dict[str, Any] = Field(default_factory=dict)
    in_point: float = Field(default=0, ge=0)
    out_point: float = Field(default=0, ge=0)
    segments: list[Segment] = Field(default_factory=list)
    selected_preset: str = "Stream copy"
    effect_chain: list[EffectChainItem] = Field(default_factory=list)
    output_settings: OutputSettings = Field(default_factory=OutputSettings)
    app_version: str = "0.2.0"

    @model_validator(mode="after")
    def validate_trim_range(self) -> "DeepFrameProject":
        if self.out_point and self.out_point < self.in_point:
            raise ValueError("out_point must be greater than or equal to in_point")
        return self


class MediaProbeRequest(BaseModel):
    path: str = Field(validation_alias=AliasChoices("path", "media_path"))


class MediaThumbnailRequest(BaseModel):
    path: str = Field(validation_alias=AliasChoices("path", "media_path"))
    time_seconds: float = Field(default=0, ge=0)


class FrameCacheRequest(BaseModel):
    path: str = Field(validation_alias=AliasChoices("path", "media_path"))
    start_seconds: float = Field(default=0, ge=0)
    duration_seconds: float = Field(default=30, gt=0, le=120)
    fps: float = Field(default=12, gt=0, le=30)
    width: int = Field(default=960, ge=240, le=1920)


class BrowserPreviewRequest(BaseModel):
    path: str = Field(validation_alias=AliasChoices("path", "media_path"))
    start_seconds: float = Field(default=0, ge=0)
    duration_seconds: float = Field(default=30, gt=0, le=120)


class ExportCommandRequest(BaseModel):
    input_path: str
    output_path: str
    in_point: float | None = Field(default=None, ge=0)
    out_point: float | None = Field(default=None, ge=0)
    preset: str = "copy"
    overwrite: bool = True


class NormalizeProjectRequest(BaseModel):
    project: DeepFrameProject


class ChainScriptRequest(BaseModel):
    media_path: str
    effect_chain: list[EffectChainItem] = Field(default_factory=list)


class PreviewRenderRequest(BaseModel):
    project: DeepFrameProject
    engine: str = "vapoursynth"
    start_seconds: float | None = Field(default=None, ge=0)
    duration_seconds: float = Field(default=5.0, gt=0, le=30)
