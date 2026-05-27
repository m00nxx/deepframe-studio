import { emptyProject } from "@/data"
import type { EffectChainItem, MediaMetadata, ProjectState, Segment } from "@/types/domain"

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function numericValue(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}

function stringValue(value: unknown, fallback: string) {
  return typeof value === "string" ? value : fallback
}

function optionalString(value: unknown) {
  return typeof value === "string" ? value : undefined
}

function normalizeMetadata(value: unknown): MediaMetadata {
  if (!isRecord(value)) return emptyProject.metadata_cache

  const formatSource = isRecord(value.format) ? value.format : undefined
  const streams = Array.isArray(value.streams)
    ? value.streams.flatMap((stream) => {
        if (!isRecord(stream)) return []
        return [
          {
            codec_type: optionalString(stream.codec_type),
            codec_name: optionalString(stream.codec_name),
            width: numericValue(stream.width, Number.NaN),
            height: numericValue(stream.height, Number.NaN),
            avg_frame_rate: optionalString(stream.avg_frame_rate),
          },
        ]
      })
    : undefined

  return {
    ...(formatSource
      ? {
          format: {
            duration: optionalString(formatSource.duration),
            format_name: optionalString(formatSource.format_name),
            size: optionalString(formatSource.size),
            bit_rate: optionalString(formatSource.bit_rate),
          },
        }
      : {}),
    ...(streams
      ? {
          streams: streams.map((stream) => ({
            ...stream,
            width: Number.isFinite(stream.width) ? stream.width : undefined,
            height: Number.isFinite(stream.height) ? stream.height : undefined,
          })),
        }
      : {}),
  }
}

function normalizeSegments(value: unknown): Segment[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((segment, index) => {
    if (!isRecord(segment)) return []
    const start = numericValue(segment.start, 0)
    return [
      {
        id: stringValue(segment.id, `segment-${index + 1}`),
        name: stringValue(segment.name, `Segment ${index + 1}`),
        start,
        end: numericValue(segment.end, start),
      },
    ]
  })
}

function normalizeParameters(value: unknown): Record<string, string | number | boolean> {
  if (!isRecord(value)) return {}
  return Object.fromEntries(
    Object.entries(value).filter(([, parameterValue]) => {
      return ["string", "number", "boolean"].includes(typeof parameterValue)
    }),
  ) as Record<string, string | number | boolean>
}

function normalizeEffectChain(value: unknown): EffectChainItem[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((effect, index) => {
    if (!isRecord(effect)) return []
    return [
      {
        id: stringValue(effect.id, `effect-${index + 1}`),
        effect_id: stringValue(effect.effect_id, ""),
        name: stringValue(effect.name, "Custom effect"),
        engine: effect.engine === "avisynth" ? "avisynth" : "vapoursynth",
        category: stringValue(effect.category, "custom"),
        enabled: typeof effect.enabled === "boolean" ? effect.enabled : true,
        parameters: normalizeParameters(effect.parameters),
      },
    ]
  })
}

export function normalizeProjectFile(value: Partial<ProjectState>): ProjectState {
  const outputSettings: Record<string, unknown> = isRecord(value.output_settings) ? value.output_settings : {}
  return {
    ...emptyProject,
    ...value,
    media_path: stringValue(value.media_path, emptyProject.media_path),
    metadata_cache: normalizeMetadata(value.metadata_cache),
    in_point: numericValue(value.in_point, emptyProject.in_point),
    out_point: numericValue(value.out_point, emptyProject.out_point),
    segments: normalizeSegments(value.segments),
    selected_preset: stringValue(value.selected_preset, emptyProject.selected_preset),
    effect_chain: normalizeEffectChain(value.effect_chain),
    output_settings: {
      container: stringValue(outputSettings.container, emptyProject.output_settings.container),
      video_codec: stringValue(outputSettings.video_codec, emptyProject.output_settings.video_codec),
      audio_codec: stringValue(outputSettings.audio_codec, emptyProject.output_settings.audio_codec),
      crf: numericValue(outputSettings.crf, emptyProject.output_settings.crf),
      preset: stringValue(outputSettings.preset, emptyProject.output_settings.preset),
      output_path: stringValue(outputSettings.output_path, emptyProject.output_settings.output_path),
    },
    app_version: stringValue(value.app_version, emptyProject.app_version),
  }
}

export function serializeProjectFile(project: ProjectState) {
  return `${JSON.stringify(normalizeProjectFile(project), null, 2)}\n`
}

export function parseProjectFile(contents: string): ProjectState {
  try {
    const parsed: unknown = JSON.parse(contents)
    if (!isRecord(parsed)) {
      throw new Error("Project file must contain an object")
    }
    return normalizeProjectFile(parsed as Partial<ProjectState>)
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error("Invalid project JSON")
    }
    throw error
  }
}
