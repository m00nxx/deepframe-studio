import { invoke, isTauri } from "@tauri-apps/api/core"

import type {
  ChainValidationResult,
  BrowserPreviewResult,
  EffectChainItem,
  EffectDescriptor,
  ExportJobStatus,
  FrameCacheResult,
  MediaMetadata,
  MediaThumbnail,
  ProjectState,
  RenderPreviewResult,
  ToolStatus,
} from "@/types/domain"

const DEFAULT_API_URL = import.meta.env.VITE_DEEPFRAME_API_URL ?? "http://127.0.0.1:8765"

async function getBackendUrl() {
  if (!isTauri()) return DEFAULT_API_URL
  try {
    return await invoke<string>("backend_url")
  } catch {
    return DEFAULT_API_URL
  }
}

async function getBackendToken() {
  if (!isTauri()) return import.meta.env.VITE_DEEPFRAME_API_TOKEN ?? ""
  try {
    return await invoke<string>("backend_token")
  } catch {
    return import.meta.env.VITE_DEEPFRAME_API_TOKEN ?? ""
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const baseUrl = await getBackendUrl()
  const token = await getBackendToken()
  const headers = init?.body
    ? {
        "content-type": "application/json",
        ...init?.headers,
      }
    : init?.headers
  const authorizedHeaders = token
    ? {
        ...headers,
        authorization: `Bearer ${token}`,
      }
    : headers
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: authorizedHeaders,
  })
  if (!response.ok) {
    const detail = await response.text()
    let message = detail
    try {
      const parsed = JSON.parse(detail) as { detail?: unknown }
      if (typeof parsed.detail === "string") {
        message = parsed.detail
      } else if (parsed.detail) {
        message = JSON.stringify(parsed.detail)
      }
    } catch {
      message = detail
    }
    throw new Error(message || `${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ ok: boolean; version: string }>("/health"),
  detectTools: () => request<ToolStatus[]>("/tools/detect"),
  effects: () => request<EffectDescriptor[]>("/effects"),
  probeMedia: (path: string) =>
    request<MediaMetadata>("/media/probe", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  thumbnail: (path: string, timeSeconds = 0) =>
    request<MediaThumbnail>("/media/thumbnail", {
      method: "POST",
      body: JSON.stringify({ path, time_seconds: timeSeconds }),
    }),
  frameCache: (path: string, startSeconds = 0, durationSeconds = 30, fps = 12, width = 960) =>
    request<FrameCacheResult>("/media/frame-cache", {
      method: "POST",
      body: JSON.stringify({ path, start_seconds: startSeconds, duration_seconds: durationSeconds, fps, width }),
    }),
  exportCommand: (project: ProjectState) =>
    request<{ command: string[] }>("/export/command", {
      method: "POST",
      body: JSON.stringify(project),
    }),
  startExport: (project: ProjectState) =>
    request<ExportJobStatus>("/export/jobs", {
      method: "POST",
      body: JSON.stringify(project),
    }),
  exportJob: (jobId: string) => request<ExportJobStatus>(`/export/jobs/${encodeURIComponent(jobId)}`),
  cancelExport: (jobId: string) =>
    request<ExportJobStatus>(`/export/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    }),
  chainScript: (mediaPath: string, chain: EffectChainItem[]) =>
    request<{ vapoursynth: string; avisynth: string }>("/effects/chain/script", {
      method: "POST",
      body: JSON.stringify({ media_path: mediaPath, effect_chain: chain }),
    }),
  validateChain: (mediaPath: string, chain: EffectChainItem[]) =>
    request<ChainValidationResult>("/effects/chain/validate", {
      method: "POST",
      body: JSON.stringify({ media_path: mediaPath, effect_chain: chain }),
    }),
  renderPreview: (
    project: ProjectState,
    durationSeconds = 5,
    engine: "vapoursynth" | "avisynth" = "vapoursynth",
    startSeconds?: number,
  ) =>
    request<RenderPreviewResult>("/preview/render", {
      method: "POST",
      body: JSON.stringify({ project, engine, duration_seconds: durationSeconds, start_seconds: startSeconds }),
    }),
  browserPreview: (path: string, startSeconds = 0, durationSeconds = 30) =>
    request<BrowserPreviewResult>("/media/browser-preview", {
      method: "POST",
      body: JSON.stringify({ path, start_seconds: startSeconds, duration_seconds: durationSeconds }),
    }),
  previewFileUrl: async (path: string) => {
    const baseUrl = await getBackendUrl()
    const token = await getBackendToken()
    const filename = path.split(/[\\/]/).pop() ?? path
    const query = token ? `?access_token=${encodeURIComponent(token)}` : ""
    return `${baseUrl}/preview/files/${encodeURIComponent(filename)}${query}`
  },
  mediaFileUrl: async (path: string) => {
    const baseUrl = await getBackendUrl()
    const token = await getBackendToken()
    const params = new URLSearchParams({ path })
    if (token) params.set("access_token", token)
    return `${baseUrl}/media/file?${params.toString()}`
  },
  frameCacheFileUrl: async (cacheId: string, filename: string) => {
    const baseUrl = await getBackendUrl()
    const token = await getBackendToken()
    const query = token ? `?access_token=${encodeURIComponent(token)}` : ""
    return `${baseUrl}/media/frame-cache/${encodeURIComponent(cacheId)}/${encodeURIComponent(filename)}${query}`
  },
}
