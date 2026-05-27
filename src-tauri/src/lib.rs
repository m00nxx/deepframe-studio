use std::{
    net::TcpStream,
    net::TcpListener,
    path::PathBuf,
    process::{Child, Command as StdCommand, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::Manager;
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use uuid::Uuid;

struct BackendState {
    url: String,
    token: String,
    sidecar_child: Mutex<Option<CommandChild>>,
    dev_child: Mutex<Option<Child>>,
    logs: Mutex<Vec<String>>,
}

impl Drop for BackendState {
    fn drop(&mut self) {
        if let Ok(mut child_slot) = self.sidecar_child.lock() {
            if let Some(child) = child_slot.take() {
                let _ = child.kill();
            }
        }
        if let Ok(mut child_slot) = self.dev_child.lock() {
            if let Some(child) = child_slot.as_mut() {
                let _ = child.kill();
            }
        }
    }
}

fn reserve_local_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(8765)
}

fn backend_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("backend")
}

fn wait_for_port(port: u16, timeout: Duration) -> bool {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(120));
    }
    false
}

fn spawn_sidecar(app: &tauri::AppHandle, port: u16, token: &str, logs: &mut Vec<String>) -> Option<CommandChild> {
    let backend = backend_dir();
    let command = app
        .shell()
        .sidecar("binaries/deepframe-sidecar")
        .ok()?
        .env("DEEPFRAME_BACKEND_DIR", backend)
        .env("DEEPFRAME_API_TOKEN", token)
        .args(["--host", "127.0.0.1", "--port", &port.to_string()]);

    match command.spawn() {
        Ok((mut rx, child)) => {
            tauri::async_runtime::spawn(async move {
                while let Some(_event) = rx.recv().await {}
            });
            Some(child)
        }
        Err(error) => {
            logs.push(format!("sidecar spawn failed: {error}"));
            None
        }
    }
}

fn spawn_dev_backend(port: u16, token: &str, logs: &mut Vec<String>) -> Option<Child> {
    let backend = backend_dir();
    let uv_child = StdCommand::new("uv")
        .current_dir(&backend)
        .env("UV_PROJECT_ENVIRONMENT", "/tmp/deepframe-api-tauri-venv")
        .env("DEEPFRAME_API_TOKEN", token)
        .args([
            "run",
            "--python",
            "3.12",
            "python",
            "-m",
            "deepframe_api.sidecar",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();

    match uv_child {
        Ok(child) => Some(child),
        Err(error) => {
            logs.push(format!("uv backend spawn failed: {error}"));
            StdCommand::new("python")
            .current_dir(&backend)
            .env("DEEPFRAME_API_TOKEN", token)
            .args([
                "-m",
                "deepframe_api.sidecar",
                "--host",
                "127.0.0.1",
                "--port",
                &port.to_string(),
            ])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|fallback_error| logs.push(format!("python backend spawn failed: {fallback_error}")))
            .ok()
        }
    }
}

#[tauri::command]
fn backend_url(state: tauri::State<'_, BackendState>) -> String {
    state.url.clone()
}

#[tauri::command]
fn backend_token(state: tauri::State<'_, BackendState>) -> String {
    state.token.clone()
}

#[tauri::command]
fn backend_logs(state: tauri::State<'_, BackendState>) -> Vec<String> {
    state.logs.lock().map(|logs| logs.clone()).unwrap_or_default()
}

fn validate_project_path(path: &str) -> Result<(), String> {
    let path = std::path::Path::new(path);
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("json"))
    {
        return Ok(());
    }
    Err("project path must be a .json file".to_string())
}

fn validate_preview_media_path(path: &str) -> Result<(), String> {
    let path = std::path::Path::new(path);
    let allowed_extensions = ["avi", "m2ts", "m4v", "mkv", "mov", "mp4", "mpeg", "mpg", "ts", "webm", "wmv"];
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| allowed_extensions.iter().any(|allowed| extension.eq_ignore_ascii_case(allowed)))
    {
        return Ok(());
    }
    Err("preview path must be a supported video file".to_string())
}

#[tauri::command]
fn read_project_file(path: String) -> Result<String, String> {
    validate_project_path(&path)?;
    std::fs::read_to_string(path).map_err(|error| error.to_string())
}

#[tauri::command]
fn write_project_file(path: String, contents: String) -> Result<(), String> {
    validate_project_path(&path)?;
    std::fs::write(path, contents).map_err(|error| error.to_string())
}

#[tauri::command]
fn allow_preview_file(app: tauri::AppHandle, path: String) -> Result<(), String> {
    validate_preview_media_path(&path)?;
    app.asset_protocol_scope()
        .allow_file(path)
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn pick_system_path(kind: String) -> Result<String, String> {
    let script = system_dialog_script(&kind).ok_or_else(|| "unknown dialog kind".to_string())?;
    let mut child = StdCommand::new("powershell.exe")
        .args(["-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("system dialog unavailable: {error}"))?;

    let started = Instant::now();
    loop {
        if child.try_wait().map_err(|error| error.to_string())?.is_some() {
            break;
        }
        if started.elapsed() > Duration::from_secs(30) {
            let _ = child.kill();
            return Err("system dialog timed out".to_string());
        }
        thread::sleep(Duration::from_millis(100));
    }

    let output = child
        .wait_with_output()
        .map_err(|error| format!("system dialog output unavailable: {error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let selected = String::from_utf8_lossy(&output.stdout)
        .lines()
        .last()
        .unwrap_or("")
        .trim()
        .to_string();
    Ok(normalize_system_dialog_path(&selected))
}

fn system_dialog_script(kind: &str) -> Option<&'static str> {
    match kind {
        "video_open" => Some(
            r#"Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Filter = 'Video files (*.mp4;*.mkv;*.mov;*.avi;*.m4v;*.webm)|*.mp4;*.mkv;*.mov;*.avi;*.m4v;*.webm|All files (*.*)|*.*'
$dialog.Multiselect = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.FileName }"#,
        ),
        "project_open" => Some(
            r#"Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Filter = 'DeepFrame project (*.deepframe.json;*.json)|*.deepframe.json;*.json|JSON (*.json)|*.json|All files (*.*)|*.*'
$dialog.Multiselect = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.FileName }"#,
        ),
        "project_save" => Some(
            r#"Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.SaveFileDialog
$dialog.Filter = 'DeepFrame project (*.deepframe.json;*.json)|*.deepframe.json;*.json|JSON (*.json)|*.json'
$dialog.DefaultExt = 'json'
$dialog.OverwritePrompt = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.FileName }"#,
        ),
        "export_save" => Some(
            r#"Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.SaveFileDialog
$dialog.Filter = 'MP4 video (*.mp4)|*.mp4|Matroska video (*.mkv)|*.mkv|All files (*.*)|*.*'
$dialog.DefaultExt = 'mp4'
$dialog.OverwritePrompt = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.FileName }"#,
        ),
        _ => None,
    }
}

fn normalize_system_dialog_path(path: &str) -> String {
    if is_wsl_environment() {
        return windows_path_to_wsl_path(path).unwrap_or_else(|| path.to_string());
    }
    path.to_string()
}

fn is_wsl_environment() -> bool {
    std::fs::read_to_string("/proc/version")
        .map(|version| version.to_ascii_lowercase().contains("microsoft") || version.to_ascii_lowercase().contains("wsl"))
        .unwrap_or(false)
}

fn windows_path_to_wsl_path(path: &str) -> Option<String> {
    let bytes = path.as_bytes();
    if bytes.len() < 3 || bytes[1] != b':' || (bytes[2] != b'\\' && bytes[2] != b'/') || !bytes[0].is_ascii_alphabetic() {
        return None;
    }
    let drive = (bytes[0] as char).to_ascii_lowercase();
    let rest = path[3..].replace('\\', "/");
    Some(format!("/mnt/{drive}/{}", rest.trim_start_matches('/')))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let configured_url = std::env::var("DEEPFRAME_API_URL").ok();
            let token = std::env::var("DEEPFRAME_API_TOKEN").unwrap_or_else(|_| Uuid::new_v4().to_string());
            let mut logs = Vec::new();
            let mut sidecar_child = None;
            let mut dev_child = None;
            let url = if let Some(url) = configured_url {
                url
            } else {
                let mut selected_port = 8765;
                for _ in 0..4 {
                    let port = reserve_local_port();
                    selected_port = port;
                    sidecar_child = spawn_sidecar(app.handle(), port, &token, &mut logs);
                    if sidecar_child.is_none() {
                        dev_child = spawn_dev_backend(port, &token, &mut logs);
                    }
                    if wait_for_port(port, Duration::from_secs(5)) {
                        break;
                    }
                    if let Some(child) = sidecar_child.take() {
                        let _ = child.kill();
                    }
                    if let Some(child) = dev_child.as_mut() {
                        let _ = child.kill();
                    }
                    dev_child = None;
                    logs.push(format!("backend did not become ready on port {port}"));
                }
                format!("http://127.0.0.1:{selected_port}")
            };

            app.manage(BackendState {
                url,
                token,
                sidecar_child: Mutex::new(sidecar_child),
                dev_child: Mutex::new(dev_child),
                logs: Mutex::new(logs),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_url,
            backend_token,
            backend_logs,
            read_project_file,
            write_project_file,
            allow_preview_file,
            pick_system_path,
        ])
        .run(tauri::generate_context!())
        .expect("error while running DeepFrame Studio")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converts_windows_paths_to_wsl_paths() {
        assert_eq!(
            windows_path_to_wsl_path(r"C:\Users\me\Videos\clip.mp4"),
            Some("/mnt/c/Users/me/Videos/clip.mp4".to_string())
        );
        assert_eq!(
            windows_path_to_wsl_path("D:/Media/source video.mkv"),
            Some("/mnt/d/Media/source video.mkv".to_string())
        );
        assert_eq!(windows_path_to_wsl_path("/mnt/c/video.mp4"), None);
    }
}
