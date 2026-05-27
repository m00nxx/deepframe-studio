export type ToolStatus = {
  name: string
  detected: boolean
  path: string
  version?: string
  engine?: "vapoursynth" | "avisynth" | string
}

export type MediaStream = {
  codec_type?: string
  codec_name?: string
  width?: number
  height?: number
  avg_frame_rate?: string
}

export type MediaMetadata = {
  format?: {
    duration?: string
    format_name?: string
    size?: string
    bit_rate?: string
  }
  streams?: MediaStream[]
}

export type MediaThumbnail = {
  data_url: string
}

export type FrameCacheFrame = {
  filename: string
  time_seconds: number
}

export type FrameCacheResult = {
  cache_id: string
  start_seconds: number
  duration_seconds: number
  fps: number
  frames: FrameCacheFrame[]
}

export type RenderPreviewResult = {
  path: string
  script_path?: string
  engine: "vapoursynth" | "avisynth" | string
  command: string[]
  duration_seconds: number
}

export type BrowserPreviewResult = {
  path: string
  command: string[]
  duration_seconds: number
}

export type Segment = {
  id: string
  name: string
  start: number
  end: number
}

export type EffectParameter = {
  name: string
  type: "int" | "float" | "bool" | "enum" | "string" | string
  default?: string | number | boolean
  min?: number
  max?: number
  step?: number
  label?: string
  description?: string
  unit?: string
  options?: string[]
  auto?: boolean
  auto_value?: string
  suggested?: string | number | boolean
}

export type EffectDescriptor = {
  effect_id: string
  name: string
  engine: "vapoursynth" | "avisynth"
  category: string
  description: string
  recommended: boolean
  renderable?: boolean
  render_status?: "renderable" | "ok" | "supported" | "not_renderable" | "non_renderable" | string
  renderable_engines?: Array<"vapoursynth" | "avisynth" | string>
  required_plugins?: string[]
  install_status: "installed" | "missing" | "manual" | string
  install_method?: string
  install_policy?: "manual" | "builtin" | "metadata_only" | "allowed_download" | string
  install_allowed?: boolean
  manual_steps?: string[]
  source_url?: string
  download_url?: string
  license_status?: "redistributable" | "manual_review" | "unclear" | "built_in" | string
  cpu_gpu_notes?: string
  license_notes?: string
  script_template?: string
  parameters?: EffectParameter[]
  defaults?: Record<string, string | number | boolean>
  input_constraints?: string
  output_constraints?: string
  menu_path?: string[]
  origin?: string
}

export type EffectChainItem = {
  id: string
  effect_id: string
  name: string
  engine: "vapoursynth" | "avisynth"
  category: string
  enabled: boolean
  parameters: Record<string, string | number | boolean>
}

export type ProjectState = {
  media_path: string
  metadata_cache: MediaMetadata
  in_point: number
  out_point: number
  segments: Segment[]
  selected_preset: string
  effect_chain: EffectChainItem[]
  output_settings: {
    container: string
    video_codec: string
    audio_codec: string
    crf: number
    preset: string
    output_path: string
  }
  app_version: string
}

export type ExportJobState = "queued" | "running" | "cancel_requested" | "completed" | "failed" | "canceled"

export type ExportJobStatus = {
  job_id: string
  state: ExportJobState
  command: string[]
  duration_seconds?: number | null
  percent: number
  progress: {
    frame?: number | null
    fps?: number | null
    bitrate?: string | null
    out_time_seconds?: number | null
    speed?: string | null
    progress?: string | null
  }
  return_code?: number | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
  stderr_tail?: string[]
}

export type ScriptValidationStatus = {
  engine: "vapoursynth" | "avisynth"
  tool?: string
  available: boolean
  ok: boolean
  command: string[]
  stdout?: string
  stderr?: string
}

export type ChainValidationResult = {
  scripts: {
    vapoursynth: string
    avisynth: string
  }
  validations: {
    vapoursynth: ScriptValidationStatus
    avisynth: ScriptValidationStatus
  }
}
