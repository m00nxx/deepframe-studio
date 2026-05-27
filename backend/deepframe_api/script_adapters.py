from __future__ import annotations

from functools import lru_cache
import shutil
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from deepframe_api.effects import EffectRegistry
from deepframe_api.path_tools import is_windows_executable, project_root, runtime_dir, tool_path, wsl_to_windows_path

Runner = Callable[..., subprocess.CompletedProcess[str]]
Resolver = Callable[[str], str | None]


class VapourSynthAdapter:
    def __init__(
        self,
        vspipe_path: str | None = None,
        runner: Runner = subprocess.run,
        resolver: Resolver = shutil.which,
    ):
        self.vspipe_path = vspipe_path if vspipe_path is not None else resolve_vspipe(resolver, include_bundled=resolver is shutil.which)
        self.runner = runner

    def detect(self) -> dict[str, object]:
        return {
            "name": "vspipe",
            "engine": "vapoursynth",
            "detected": bool(self.vspipe_path),
            "path": self.vspipe_path or "vspipe",
            "version": self.version() or "",
        }

    def version(self) -> str | None:
        if not self.vspipe_path:
            return None
        try:
            result = self.runner(
                [self.vspipe_path, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(Path(self.vspipe_path).parent),
                env=tool_env(Path(self.vspipe_path).parent),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        output = (result.stdout or result.stderr or "").splitlines()
        return output[0] if result.returncode == 0 and output else None

    def validate_script(self, script: str) -> dict[str, object]:
        if not self.vspipe_path:
            return skipped_validation("vapoursynth", "vspipe")
        return validate_with_temp_script(
            engine="vapoursynth",
            tool="vspipe",
            suffix=".vpy",
            script=script,
            command_builder=lambda path: [self.vspipe_path or "vspipe", "--info", tool_path(path, self.vspipe_path), "-"],
            runner=self.runner,
            cwd=Path(self.vspipe_path).parent if self.vspipe_path else None,
            executable_path=self.vspipe_path,
        )


class AviSynthAdapter:
    def __init__(
        self,
        tool_path: str | None = None,
        runner: Runner = subprocess.run,
        resolver: Resolver = shutil.which,
    ):
        self.tool_path, self.tool_name = resolve_avisynth_tool(tool_path, resolver)
        self.runner = runner

    def detect(self) -> dict[str, object]:
        return {
            "name": self.tool_name,
            "engine": "avisynth",
            "detected": bool(self.tool_path),
            "path": self.tool_path or self.tool_name,
            "version": self.version() or "",
        }

    def version(self) -> str | None:
        if not self.tool_path:
            return None
        for args in (["--version"], ["-h"]):
            try:
                result = self.runner(
                    [self.tool_path, *args],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            output = (result.stdout or result.stderr or "").splitlines()
            if output:
                return output[0]
        return None

    def validate_script(self, script: str) -> dict[str, object]:
        if not self.tool_path:
            return skipped_validation("avisynth", self.tool_name)
        return validate_with_temp_script(
            engine="avisynth",
            tool=self.tool_name,
            suffix=".avs",
            script=script,
            command_builder=lambda path: self._validation_command(path),
            runner=self.runner,
            cwd=Path(self.tool_path).parent if self.tool_path else None,
            executable_path=self.tool_path,
        )

    def _validation_command(self, script_path: str) -> list[str]:
        tool = self.tool_path or "avs2yuv"
        converted_script_path = tool_path(script_path, self.tool_path)
        if "avs2pipe" in self.tool_name.lower() or tool.lower().endswith("avs2pipemod64.exe"):
            command = [tool]
            dll_path = resolve_avisynth_dll()
            if dll_path:
                command.append(f"-dll={tool_path(dll_path, self.tool_path)}")
            command.extend(["-info", converted_script_path])
            return command
        return [tool, converted_script_path, "-frames", "0", "-"]


class ScriptToolManager:
    def __init__(
        self,
        registry: EffectRegistry,
        vapoursynth: VapourSynthAdapter | None = None,
        avisynth: AviSynthAdapter | None = None,
    ):
        self.registry = registry
        self.vapoursynth = vapoursynth or VapourSynthAdapter()
        self.avisynth = avisynth or AviSynthAdapter()

    def detect(self) -> list[dict[str, object]]:
        return [self.vapoursynth.detect(), self.avisynth.detect()]

    def generate_chain(self, media_path: str, effect_chain: list[dict[str, Any]]) -> dict[str, str]:
        return self.registry.build_chain_scripts(media_path=media_path, effect_chain=effect_chain).model_dump()

    def validate_chain(self, media_path: str, effect_chain: list[dict[str, Any]]) -> dict[str, object]:
        scripts = self.generate_chain(media_path=media_path, effect_chain=effect_chain)
        vapoursynth_scripts = self.generate_chain(
            media_path=tool_path(media_path, self.vapoursynth.vspipe_path),
            effect_chain=effect_chain,
        )
        avisynth_scripts = self.generate_chain(
            media_path=tool_path(media_path, self.avisynth.tool_path),
            effect_chain=effect_chain,
        )
        return {
            "scripts": scripts,
            "validations": {
                "vapoursynth": self.vapoursynth.validate_script(vapoursynth_scripts["vapoursynth"]),
                "avisynth": self.avisynth.validate_script(avisynth_scripts["avisynth"]),
            },
        }


def skipped_validation(engine: str, tool: str) -> dict[str, object]:
    return {
        "engine": engine,
        "tool": tool,
        "available": False,
        "ok": False,
        "command": [],
        "stdout": "",
        "stderr": f"{tool} not found",
    }


def resolve_avisynth_tool(tool_path: str | None, resolver: Resolver) -> tuple[str | None, str]:
    if tool_path is not None:
        return tool_path, Path(tool_path).stem or "avs2yuv"
    for name in ("avs2yuv", "avs2pipemod"):
        resolved = resolver(name)
        if resolved:
            return resolved, name
    bundled = project_root() / "vendor" / "staxrip" / "bundle" / "Apps" / "Support" / "avs2pipemod" / "avs2pipemod64.exe"
    if bundled.exists():
        return str(bundled), "avs2pipemod64"
    return None, "avs2yuv"


def resolve_avisynth_dll() -> str | None:
    dll = project_root() / "vendor" / "staxrip" / "bundle" / "Apps" / "FrameServer" / "AviSynth" / "AviSynth.dll"
    return str(dll) if dll.exists() else None


def resolve_vspipe(resolver: Resolver, include_bundled: bool = True) -> str | None:
    resolved = resolver("vspipe") or resolver("VSPipe.exe")
    if resolved:
        return resolved
    if not include_bundled:
        return None
    bundled = project_root() / "vendor" / "staxrip" / "bundle" / "Apps" / "FrameServer" / "VapourSynth" / "VSPipe.exe"
    return str(bundled) if bundled.exists() else None


def tool_env(directory: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    wsl_path_dirs: list[str] = []
    windows_path_dirs: list[str] = []
    for path in runtime_dependency_dirs(directory):
        wsl_path_dirs.append(str(path))
        windows_path_dirs.append(wsl_to_windows_path(str(path)))
    if wsl_path_dirs:
        env["PATH"] = ";".join(windows_path_dirs) + ";" + os.pathsep.join(wsl_path_dirs + [env.get("PATH", "")])
    return env


@lru_cache(maxsize=16)
def runtime_dependency_dirs(directory: Path | None = None) -> tuple[Path, ...]:
    dirs: list[Path] = []
    if directory:
        dirs.append(directory)
    root = project_root() / "vendor" / "staxrip" / "bundle" / "Apps"
    candidates = [
        root / "Support",
        root / "Plugins" / "AVS",
        root / "Plugins" / "Dual",
        root / "Plugins" / "VS",
        root / "FrameServer" / "AviSynth",
        root / "FrameServer" / "VapourSynth",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        dirs.append(candidate)
        dirs.extend(path for path in candidate.rglob("*") if path.is_dir() and is_runtime_dependency_dir(path))
    return tuple(dict.fromkeys(dirs))


def is_runtime_dependency_dir(path: Path) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    if "/lib/site-packages/" in normalized or normalized.endswith("/lib/site-packages"):
        return False
    if "/lib/" in normalized and "/frameserver/vapoursynth/" in normalized:
        return False
    return True


def validate_with_temp_script(
    engine: str,
    tool: str,
    suffix: str,
    script: str,
    command_builder: Callable[[str], list[str]],
    runner: Runner,
    cwd: Path | None = None,
    executable_path: str | None = None,
) -> dict[str, object]:
    temp_dir = runtime_dir("script-validation") if is_windows_executable(executable_path) else None
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=suffix, delete=False, dir=temp_dir) as handle:
        handle.write(script)
        script_path = handle.name
    command = command_builder(script_path)
    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(cwd) if cwd else None,
            env=tool_env(cwd),
        )
        return {
            "engine": engine,
            "tool": tool,
            "available": True,
            "ok": result.returncode == 0,
            "command": command,
            "stdout": tail_text(result.stdout),
            "stderr": tail_text(result.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "engine": engine,
            "tool": tool,
            "available": True,
            "ok": False,
            "command": command,
            "stdout": tail_text(exc.stdout),
            "stderr": "validation timed out",
        }
    except OSError as exc:
        return {
            "engine": engine,
            "tool": tool,
            "available": False,
            "ok": False,
            "command": command,
            "stdout": "",
            "stderr": str(exc),
        }
    finally:
        Path(script_path).unlink(missing_ok=True)


def tail_text(value: str | bytes | None, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-limit:]
    return value[-limit:]
