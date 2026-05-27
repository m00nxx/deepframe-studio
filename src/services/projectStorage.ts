import { invoke } from "@tauri-apps/api/core"

export async function readProjectFile(path: string) {
  return invoke<string>("read_project_file", { path })
}

export async function writeProjectFile(path: string, contents: string) {
  await invoke("write_project_file", { path, contents })
}
