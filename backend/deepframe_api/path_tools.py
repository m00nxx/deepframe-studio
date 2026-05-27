from __future__ import annotations

from pathlib import Path
import re


def project_root() -> Path:
    return Path(__file__).parents[2]


def is_windows_executable(path: str | None) -> bool:
    return bool(path and path.lower().endswith(".exe"))


def wsl_to_windows_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if len(normalized) > 7 and normalized.startswith("/mnt/") and normalized[5].isalpha() and normalized[6] == "/":
        drive = normalized[5].upper()
        return f"{drive}:\\" + normalized[7:].replace("/", "\\")
    return normalized


def windows_to_wsl_path(path: str) -> str:
    if not re.match(r"^[a-zA-Z]:[\\/]", path):
        return path
    drive = path[0].lower()
    rest = path[3:].replace("\\", "/").lstrip("/")
    return f"/mnt/{drive}/{rest}"


def local_path(path: str) -> str:
    return windows_to_wsl_path(path.strip())


def tool_path(path: str, executable_path: str | None) -> str:
    if not is_windows_executable(executable_path):
        return local_path(path)
    return wsl_to_windows_path(path)


def runtime_dir(name: str) -> Path:
    path = project_root() / "artifacts" / name
    path.mkdir(parents=True, exist_ok=True)
    return path
