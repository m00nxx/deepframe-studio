import { open, save } from "@tauri-apps/plugin-dialog"
import { invoke, isTauri } from "@tauri-apps/api/core"

async function pickSystemPath(kind: string) {
  if (import.meta.env.VITE_DEEPFRAME_USE_WINDOWS_DIALOG !== "1") return null
  if (!isTauri()) return null
  try {
    return await invoke<string>("pick_system_path", { kind })
  } catch {
    return null
  }
}

export async function pickVideoPath() {
  try {
    const selected = await open({
      multiple: false,
      filters: [
        {
          name: "Video",
          extensions: ["mp4", "mkv", "mov", "avi", "m4v", "webm"],
        },
      ],
    })
    return typeof selected === "string" ? selected : ""
  } catch {
    const systemPath = await pickSystemPath("video_open")
    if (systemPath !== null) return systemPath
    return window.prompt("Video path") ?? ""
  }
}

export async function pickProjectPathForSave() {
  try {
    return (
      (await save({
        filters: [{ name: "DeepFrame Project", extensions: ["deepframe.json", "json"] }],
      })) ?? ""
    )
  } catch {
    const systemPath = await pickSystemPath("project_save")
    if (systemPath !== null) return systemPath
    return window.prompt("Project save path") ?? ""
  }
}

export async function pickProjectPathForOpen() {
  try {
    const selected = await open({
      multiple: false,
      filters: [{ name: "DeepFrame Project", extensions: ["deepframe.json", "json"] }],
    })
    return typeof selected === "string" ? selected : ""
  } catch {
    const systemPath = await pickSystemPath("project_open")
    if (systemPath !== null) return systemPath
    return window.prompt("Project open path") ?? ""
  }
}

export async function pickExportPath() {
  try {
    return (
      (await save({
        filters: [
          { name: "MP4", extensions: ["mp4"] },
          { name: "Matroska", extensions: ["mkv"] },
        ],
      })) ?? ""
    )
  } catch {
    const systemPath = await pickSystemPath("export_save")
    if (systemPath !== null) return systemPath
    return window.prompt("Export output path") ?? ""
  }
}
