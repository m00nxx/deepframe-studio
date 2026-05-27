from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, Field


DEFAULT_STAXRIP_SOURCE = Path("/mnt/c/StaxRip/sorgenti/Source/General/Package.vb")
DEFAULT_STAXRIP_INSTALL = Path("/mnt/c/StaxRip/StaxRip-v2.52.3-x64")


class StaxRipComponent(BaseModel):
    name: str
    kind: Literal["package", "plugin"]
    filename: str = ""
    filename32: str = ""
    description: str = ""
    web_url: str = ""
    download_url: str = ""
    avs_filter_names: list[str] = Field(default_factory=list)
    vs_filter_names: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    declared_locations: list[str] = Field(default_factory=list)
    expected_paths: list[str] = Field(default_factory=list)
    installed_paths: list[str] = Field(default_factory=list)
    license_files: list[str] = Field(default_factory=list)
    license_status: str = "manual_review"
    license_notes: str = ""


class StaxRipScanResult(BaseModel):
    source_file: str
    install_root: str
    total: int
    installed: int
    plugins: int
    packages: int
    components: list[StaxRipComponent]


class StaxRipFilterProfile(BaseModel):
    engine: Literal["vapoursynth", "avisynth"]
    category: str
    menu_path: list[str] = Field(default_factory=list)
    name: str
    script: str


def scan_staxrip(source_file: Path = DEFAULT_STAXRIP_SOURCE, install_root: Path = DEFAULT_STAXRIP_INSTALL) -> StaxRipScanResult:
    if not source_file.exists():
        raise FileNotFoundError(f"StaxRip Package.vb not found: {source_file}")

    components = parse_package_vb(source_file.read_text(encoding="utf-8-sig", errors="replace"))
    filename_index = _build_filename_index(install_root)
    enriched = [_enrich_component(component, install_root, filename_index) for component in components]
    installed = sum(1 for component in enriched if component.installed_paths)

    return StaxRipScanResult(
        source_file=str(source_file),
        install_root=str(install_root),
        total=len(enriched),
        installed=installed,
        plugins=sum(1 for component in enriched if component.kind == "plugin"),
        packages=sum(1 for component in enriched if component.kind == "package"),
        components=enriched,
    )


def parse_package_vb(text: str) -> list[StaxRipComponent]:
    components: list[StaxRipComponent] = []
    for kind, block in _iter_initializer_blocks(text):
        name = _string_property(block, "Name")
        filename = _string_property(block, "Filename")
        if not name and not filename:
            continue

        component = StaxRipComponent(
            name=name or Path(filename).stem,
            kind=kind,
            filename=filename,
            filename32=_string_property(block, "Filename32"),
            description=_string_property(block, "Description"),
            web_url=_string_property(block, "WebURL"),
            download_url=_string_property(block, "DownloadURL"),
            avs_filter_names=_array_property(block, "AvsFilterNames"),
            vs_filter_names=_array_property(block, "VsFilterNames"),
            dependencies=_array_property(block, "Dependencies"),
            declared_locations=_locations(block),
        )
        components.append(component)
    return components


def parse_filter_profiles(text: str, engine: Literal["vapoursynth", "avisynth"]) -> list[StaxRipFilterProfile]:
    profiles: list[StaxRipFilterProfile] = []
    category = ""
    current_name = ""
    current_path: list[str] = []
    current_script: list[str] = []

    def flush() -> None:
        nonlocal current_name, current_path, current_script
        if category and current_name:
            profiles.append(
                StaxRipFilterProfile(
                    engine=engine,
                    category=category,
                    menu_path=current_path,
                    name=current_name,
                    script="\n".join(current_script).strip(),
                )
            )
        current_name = ""
        current_path = []
        current_script = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("[") and line.endswith("]"):
            flush()
            category = line[1:-1].strip()
            continue

        multiline = line.startswith("    ") or line.startswith("\t")
        if multiline:
            if current_name:
                current_script.append(line[4:] if line.startswith("    ") else line[1:])
            continue

        flush()
        if "=" not in line or not category:
            continue
        left, right = line.split("=", 1)
        parts = [part.strip() for part in left.split("|") if part.strip()]
        if not parts:
            continue
        current_path = parts[:-1]
        current_name = parts[-1]
        current_script = [right.strip()]

    flush()
    return profiles


def _iter_initializer_blocks(text: str) -> list[tuple[Literal["package", "plugin"], str]]:
    blocks: list[tuple[Literal["package", "plugin"], str]] = []
    pattern = re.compile(r"Add\(New\s+(PluginPackage|Package)\s+With\s+\{", re.IGNORECASE)
    for match in pattern.finditer(text):
        index = match.end() - 1
        depth = 0
        in_string = False
        escaped_quote = False
        for pos in range(index, len(text)):
            char = text[pos]
            if in_string:
                if char == '"' and escaped_quote:
                    escaped_quote = False
                    continue
                if char == '"':
                    if pos + 1 < len(text) and text[pos + 1] == '"':
                        escaped_quote = True
                    else:
                        in_string = False
                else:
                    escaped_quote = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    kind: Literal["package", "plugin"] = "plugin" if match.group(1).lower() == "pluginpackage" else "package"
                    blocks.append((kind, text[index + 1 : pos]))
                    break
    return blocks


def _string_property(block: str, name: str) -> str:
    match = re.search(rf'\.{re.escape(name)}\s*=\s*"((?:[^"]|"")*)"', block)
    return _unescape_vb_string(match.group(1)) if match else ""


def _array_property(block: str, name: str) -> list[str]:
    values = _brace_property(block, name)
    if not values:
        return []
    return [_unescape_vb_string(value) for value in re.findall(r'"((?:[^"]|"")*)"', values)]


def _locations(block: str) -> list[str]:
    locations = []
    single = _path_combine_property(block, "Location")
    if single:
        locations.append(single)

    multiple = _brace_property(block, "Locations")
    if multiple:
        locations.extend(_extract_path_combines(multiple))
        locations.extend(_unescape_vb_string(value) for value in re.findall(r'"((?:[^"]|"")*)"', multiple) if "\\" in value or "/" in value)

    return _dedupe(locations)


def _brace_property(block: str, name: str) -> str:
    match = re.search(rf"\.{re.escape(name)}\s*=\s*\{{", block)
    if not match:
        return ""
    start = match.end() - 1
    depth = 0
    in_string = False
    for pos in range(start, len(block)):
        char = block[pos]
        if char == '"':
            if in_string and pos + 1 < len(block) and block[pos + 1] == '"':
                continue
            in_string = not in_string
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return block[start + 1 : pos]
    return ""


def _path_combine_property(block: str, name: str) -> str:
    match = re.search(rf"\.{re.escape(name)}\s*=\s*IO\.Path\.Combine\((.*?)\)", block, flags=re.DOTALL)
    if not match:
        return _string_property(block, name)
    return _path_from_args(match.group(1))


def _extract_path_combines(text: str) -> list[str]:
    return [_path_from_args(match.group(1)) for match in re.finditer(r"IO\.Path\.Combine\((.*?)\)", text, flags=re.DOTALL)]


def _path_from_args(args: str) -> str:
    parts = [_unescape_vb_string(value) for value in re.findall(r'"((?:[^"]|"")*)"', args)]
    return "/".join(part.strip("\\/") for part in parts if part)


def _enrich_component(component: StaxRipComponent, install_root: Path, filename_index: dict[str, list[Path]] | None = None) -> StaxRipComponent:
    expected_paths = _expected_paths(component, install_root, filename_index or {})
    installed_paths = [str(path) for path in expected_paths if path.exists()]
    license_files = _license_files(expected_paths, install_root)
    status, notes = _classify_license(component, license_files)

    data = component.model_dump()
    data.update(
        expected_paths=[str(path) for path in expected_paths],
        installed_paths=installed_paths,
        license_files=[str(path) for path in license_files],
        license_status=status,
        license_notes=notes,
    )
    return StaxRipComponent.model_validate(data)


def _expected_paths(component: StaxRipComponent, install_root: Path, filename_index: dict[str, list[Path]]) -> list[Path]:
    if not component.filename:
        return []

    roots: list[Path] = []
    apps_root = install_root / "Apps"
    for location in component.declared_locations:
        roots.append(apps_root.joinpath(*location.replace("\\", "/").split("/")))

    if component.kind == "plugin":
        if component.avs_filter_names and component.vs_filter_names:
            roots.append(apps_root / "Plugins" / "Dual" / component.name)
        elif component.avs_filter_names:
            roots.append(apps_root / "Plugins" / "AVS" / component.name)
        elif component.vs_filter_names:
            roots.append(apps_root / "Plugins" / "VS" / component.name)

    paths = _dedupe_paths([root / component.filename for root in roots])
    if not paths or not any(path.exists() for path in paths):
        paths.extend(filename_index.get(component.filename.lower(), []))
    return _dedupe_paths(paths)


def _build_filename_index(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    if not root.exists():
        return index
    for path in root.rglob("*"):
        if path.is_file():
            index.setdefault(path.name.lower(), []).append(path)
    return index


def _license_files(expected_paths: list[Path], install_root: Path) -> list[Path]:
    dirs = _dedupe_paths([path.parent for path in expected_paths if path.parent.exists()])
    files: list[Path] = []
    patterns = ("license", "licence", "copying", "notice", "gpl", "lgpl", "readme")
    for directory in dirs:
        for path in directory.iterdir():
            if path.is_file() and any(token in path.name.lower() for token in patterns):
                files.append(path)

    root_license = install_root / "License.txt"
    if root_license.exists():
        files.append(root_license)
    return _dedupe_paths(files)


def _classify_license(component: StaxRipComponent, license_files: list[Path]) -> tuple[str, str]:
    haystack = " ".join([component.name, component.description, component.web_url, component.download_url]).lower()
    if any(token in haystack for token in ("non-free", "nonfree", "dolby encoding engine", "qaac", "apple application support", "nero")):
        return "manual_review", "metadata mentions a restricted or separately licensed component"

    text = ""
    for path in license_files[:8]:
        try:
            text += "\n" + path.read_text(encoding="utf-8", errors="ignore")[:12000].lower()
        except OSError:
            continue

    if "gnu general public license" in text or re.search(r"\bgpl\b", text):
        return "gpl", "local license text mentions GPL"
    if "gnu lesser general public license" in text or "lgpl" in text:
        return "lgpl", "local license text mentions LGPL"
    if "mit license" in text:
        return "mit", "local license text mentions MIT"
    if "apache license" in text:
        return "apache", "local license text mentions Apache"
    if "bsd license" in text or "redistribution and use in source and binary forms" in text:
        return "bsd", "local license text looks BSD-style"
    if license_files:
        return "manual_review", "license/readme files found but need review"
    return "manual_review", "no local license file found for this component"


def _unescape_vb_string(value: str) -> str:
    return value.replace('""', '"').strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe_paths(values: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for value in values:
        key = str(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
