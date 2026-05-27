from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BINARIES = ROOT / "src-tauri" / "binaries"


def target_triple() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "x86_64-pc-windows-msvc"
    if system == "darwin":
        return "aarch64-apple-darwin" if machine in {"arm64", "aarch64"} else "x86_64-apple-darwin"
    return "x86_64-unknown-linux-gnu"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=target_triple())
    args = parser.parse_args()

    BINARIES.mkdir(parents=True, exist_ok=True)
    name = "deepframe-sidecar"
    extension = ".exe" if "windows" in args.target else ""
    output = BINARIES / f"{name}-{args.target}{extension}"

    subprocess.run(
        [
            "uv",
            "run",
            "--python",
            "3.12",
            "--with",
            "pyinstaller",
            "pyinstaller",
            "--onefile",
            "--collect-data",
            "deepframe_api",
            "--name",
            name,
            str(BACKEND / "sidecar_entry.py"),
        ],
        cwd=BACKEND,
        check=True,
    )

    built = BACKEND / "dist" / f"{name}{extension}"
    shutil.copy2(built, output)
    output.chmod(0o755)
    print(output)


if __name__ == "__main__":
    main()
