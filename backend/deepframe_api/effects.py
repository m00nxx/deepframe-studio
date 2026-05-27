from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
import re
from pydantic import BaseModel, Field

from deepframe_api.path_tools import wsl_to_windows_path
from deepframe_api.staxrip import parse_filter_profiles


AUTO_PARAMETER_VALUE = "__deepframe_auto__"


class EffectParameter(BaseModel):
    name: str
    type: str
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    label: str = ""
    description: str = ""
    unit: str = ""
    options: list[str] = Field(default_factory=list)
    auto: bool = False
    auto_value: str = AUTO_PARAMETER_VALUE
    suggested: Any = None


class EffectDefinition(BaseModel):
    id: str
    name: str
    category: str
    engine: str = "vapoursynth"
    engines: list[str] = Field(default_factory=list)
    description: str = ""
    recommended: bool = False
    required_plugins: list[str] = Field(default_factory=list)
    install_status: str = "missing"
    install_method: str = ""
    install_policy: str = "manual"
    install_allowed: bool = False
    manual_steps: list[str] = Field(default_factory=list)
    source_url: str = ""
    download_url: str = ""
    license_status: str = "manual_review"
    license_notes: str = ""
    cpu_gpu_notes: str = ""
    parameters: list[EffectParameter] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    script_template: str = ""
    script_templates: dict[str, str] = Field(default_factory=dict)
    script_imports: list[str] = Field(default_factory=list)
    input_constraints: str = ""
    output_constraints: str = ""
    menu_path: list[str] = Field(default_factory=list)
    origin: str = "deepframe"
    suggested_category: str = ""
    discovery_source: str = ""
    discovery_tags: list[str] = Field(default_factory=list)
    validation_status: str = "metadata_only"

    @property
    def effect_id(self) -> str:
        return self.id

    @property
    def renderable_engines(self) -> list[str]:
        engines = [self.engine, *self.engines, *self.script_templates.keys()]
        result: list[str] = []
        for engine in dict.fromkeys(engines):
            template = self.script_templates.get(engine)
            if not template and self.origin != "staxrip" and self.engine == engine:
                template = self.script_template
            if _is_renderable_script_template(template):
                result.append(engine)
        return result

    @property
    def renderable(self) -> bool:
        return self.engine in self.renderable_engines and _runtime_available_for_render(self)

    @property
    def render_status(self) -> str:
        if self.renderable:
            return "renderable"
        if self.engine not in self.renderable_engines:
            return "not_renderable"
        return "missing_runtime"

    def frontend_model(self) -> dict[str, Any]:
        return {
            "effect_id": self.id,
            "name": self.name,
            "engine": self.engine,
            "category": self.category,
            "description": self.description,
            "recommended": self.recommended,
            "renderable": self.renderable,
            "render_status": self.render_status,
            "renderable_engines": self.renderable_engines,
            "required_plugins": self.required_plugins,
            "install_status": self.install_status,
            "install_method": self.install_method,
            "install_policy": self.install_policy,
            "install_allowed": self.install_allowed,
            "manual_steps": self.manual_steps,
            "source_url": self.source_url,
            "download_url": self.download_url,
            "license_status": self.license_status,
            "license_notes": self.license_notes,
            "cpu_gpu_notes": self.cpu_gpu_notes,
            "parameters": [parameter.model_dump() for parameter in self.parameters],
            "defaults": self.defaults,
            "script_template": self.script_template,
            "input_constraints": self.input_constraints,
            "output_constraints": self.output_constraints,
            "menu_path": self.menu_path,
            "origin": self.origin,
            "suggested_category": self.suggested_category,
            "discovery_source": self.discovery_source,
            "discovery_tags": self.discovery_tags,
            "validation_status": self.validation_status,
        }


class ChainScript(BaseModel):
    vapoursynth: str
    avisynth: str


class EffectRegistry:
    def __init__(self, effects: list[EffectDefinition]):
        seen: set[str] = set()
        for effect in effects:
            if effect.id in seen:
                raise ValueError(f"duplicate effect id: {effect.id}")
            seen.add(effect.id)
        self._effects = {effect.id: effect for effect in effects}

    @classmethod
    def load_default(cls) -> "EffectRegistry":
        return cls.load_from_file(default_effects_path())

    @classmethod
    def load_from_file(cls, path: Path) -> "EffectRegistry":
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        effects = [EffectDefinition.model_validate(item) for item in data.get("effects", [])]
        effects.extend(_load_staxrip_profile_effects())
        discovered_effects: list[EffectDefinition] = []
        discovered = discovered_effects_path()
        if discovered.exists():
            with discovered.open("r", encoding="utf-8") as handle:
                discovered_data = yaml.safe_load(handle) or {}
            discovered_effects = [EffectDefinition.model_validate(item) for item in discovered_data.get("effects", [])]
        combined = [*effects, *discovered_effects]
        _apply_staxrip_bundle_metadata(combined)
        effects.extend(_filter_renderable_new_effects(discovered_effects, effects))
        return cls(effects)

    def list_effects(self) -> list[EffectDefinition]:
        return sorted(self._effects.values(), key=lambda effect: effect.id)

    def get(self, effect_id: str) -> EffectDefinition:
        try:
            return self._effects[effect_id]
        except KeyError as exc:
            raise ValueError(f"unknown effect: {effect_id}") from exc

    def build_chain_scripts(
        self,
        media_path: str,
        effect_chain: list[dict[str, Any]],
    ) -> ChainScript:
        return ChainScript(
            vapoursynth=self._build_vapoursynth_script(media_path, effect_chain),
            avisynth=self._build_avisynth_script(media_path, effect_chain),
        )

    def _build_vapoursynth_script(
        self,
        media_path: str,
        effect_chain: list[dict[str, Any]],
    ) -> str:
        import_lines = [
            "import os, sys",
            "import vapoursynth as vs",
        ]
        script_path_lines = bundled_vapoursynth_script_path_lines()
        module_import_lines: list[str] = []
        body_lines = [
            "core = vs.core",
            "if not hasattr(vs, 'get_core'):",
            "    vs.get_core = lambda: core",
            *bundled_vapoursynth_plugin_load_lines(),
            f"clip = core.lsmas.LWLibavSource(source={media_path!r})",
        ]
        for item in effect_chain:
            if not item.get("enabled", True):
                continue
            effect = self.get(str(item.get("effect_id") or item["id"]))
            params = self._merged_parameters(effect, item)
            for import_line in effect.script_imports:
                if import_line not in module_import_lines:
                    module_import_lines.append(import_line)
            custom_template = params.get("script_template") if effect.category == "custom" else None
            template = self._template_for_engine(effect, "vapoursynth", custom_template)
            if template:
                rendered = _prepare_staxrip_script(_render_effect_template(str(template), params), effect, "vapoursynth")
                for import_line in _vapoursynth_module_imports(rendered):
                    if import_line not in module_import_lines:
                        module_import_lines.append(import_line)
                body_lines.append(rendered)
            else:
                body_lines.append(f"# {effect.id}: skipped for vapoursynth")
        body_lines.append("clip.set_output()")
        return "\n".join(import_lines + script_path_lines + module_import_lines + body_lines) + "\n"

    def _build_avisynth_script(
        self,
        media_path: str,
        effect_chain: list[dict[str, Any]],
    ) -> str:
        lines = [
            *bundled_avisynth_plugin_load_lines(),
            f'clip = LWLibavVideoSource("{escape_avisynth_string(media_path)}")',
        ]
        for item in effect_chain:
            if not item.get("enabled", True):
                continue
            effect = self.get(str(item.get("effect_id") or item["id"]))
            params = self._merged_parameters(effect, item)
            custom_template = params.get("script_template") if effect.category == "custom" else None
            template = self._template_for_engine(effect, "avisynth", custom_template)
            if template:
                lines.append(_prepare_staxrip_script(_render_effect_template(str(template), params), effect, "avisynth"))
            else:
                lines.append(f"# {effect.id}: skipped for avisynth")
        lines.append("return clip")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _template_for_engine(effect: EffectDefinition, engine: str, custom_template: Any = None) -> str:
        if custom_template:
            return str(custom_template)
        template = effect.script_templates.get(engine)
        if template:
            return template
        if effect.origin == "staxrip" or effect.engine != engine:
            return ""
        return effect.script_template

    @staticmethod
    def _merged_parameters(effect: EffectDefinition, item: dict[str, Any]) -> dict[str, Any]:
        params = dict(effect.defaults)
        item_params = item.get("parameters") or {}
        if isinstance(item_params, dict):
            params.update(item_params)
        return params


def default_effects_path() -> Path:
    return Path(__file__).parent / "resources" / "effects" / "sample_effects.yaml"


def discovered_effects_path() -> Path:
    return Path(__file__).parent / "resources" / "effects" / "discovered_effects.yaml"


@lru_cache(maxsize=1)
def bundled_vapoursynth_plugin_load_lines() -> list[str]:
    plugin_root = Path(__file__).parents[2] / "vendor" / "staxrip" / "bundle" / "Apps" / "Plugins"
    plugin_dirs = [plugin_root / "VS", plugin_root / "Dual"]
    plugin_files: list[Path] = []
    for directory in plugin_dirs:
        if directory.exists():
            plugin_files.extend(sorted(directory.glob("*/*.dll"), key=lambda path: str(path).lower()))
    if not plugin_files:
        return []
    lines = [
        "def _deepframe_load_plugin(path):",
        "    try:",
        "        core.std.LoadPlugin(path, altsearchpath=True)",
        "    except Exception:",
        "        pass",
    ]
    lines.extend(f"_deepframe_load_plugin(r{wsl_to_windows_path(str(plugin_file))!r})" for plugin_file in plugin_files)
    return lines


@lru_cache(maxsize=1)
def bundled_vapoursynth_script_path_lines() -> list[str]:
    script_dirs = bundled_vapoursynth_script_dirs()
    if not script_dirs:
        return []
    lines = ["_deepframe_vs_script_dirs = ["]
    lines.extend(f"    r{wsl_to_windows_path(str(directory))!r}," for directory in script_dirs)
    lines.extend(
        [
            "]",
            "for _deepframe_vs_scripts in _deepframe_vs_script_dirs:",
            "    if os.path.isdir(_deepframe_vs_scripts) and _deepframe_vs_scripts not in sys.path:",
            "        sys.path.append(_deepframe_vs_scripts)",
        ]
    )
    return lines


@lru_cache(maxsize=1)
def bundled_vapoursynth_script_dirs() -> list[Path]:
    plugins_root = Path(__file__).parents[2] / "vendor" / "staxrip" / "bundle" / "Apps" / "Plugins" / "VS"
    frame_server_scripts = Path(__file__).parents[2] / "vendor" / "staxrip" / "bundle" / "Apps" / "FrameServer" / "VapourSynth" / "vs-scripts"
    script_dirs: set[Path] = set()
    if plugins_root.exists():
        script_dirs.update(path.parent for path in plugins_root.rglob("*.py"))
    if frame_server_scripts.exists():
        script_dirs.add(frame_server_scripts)
        script_dirs.update(path.parent for path in frame_server_scripts.rglob("*.py"))
    return sorted(script_dirs, key=lambda path: str(path).lower())


@lru_cache(maxsize=1)
def bundled_avisynth_plugin_load_lines() -> list[str]:
    plugin_root = Path(__file__).parents[2] / "vendor" / "staxrip" / "bundle" / "Apps" / "Plugins"
    support_root = Path(__file__).parents[2] / "vendor" / "staxrip" / "bundle" / "Apps" / "Support"
    plugin_dirs = [plugin_root / "AVS", plugin_root / "Dual"]
    plugin_files: list[Path] = []
    script_files: list[Path] = []
    support_files = sorted(support_root.glob("*/*.dll"), key=lambda path: str(path).lower()) if support_root.exists() else []
    for directory in plugin_dirs:
        if directory.exists():
            plugin_files.extend(sorted(directory.glob("*/*.dll"), key=lambda path: str(path).lower()))
            script_files.extend(sorted(directory.glob("*/*.avsi"), key=lambda path: str(path).lower()))
    lines: list[str] = []
    for support_file in support_files:
        lines.extend(
            [
                "try {",
                f'  LoadDll("{escape_avisynth_string(wsl_to_windows_path(str(support_file)))}")',
                "} catch (err_msg) {",
                "}",
            ]
        )
    for plugin_file in plugin_files:
        lines.extend(
            [
                "try {",
                f'  LoadPlugin("{escape_avisynth_string(wsl_to_windows_path(str(plugin_file)))}")',
                "} catch (err_msg) {",
                "}",
            ]
        )
    for script_file in script_files:
        lines.extend(
            [
                "try {",
                f'  Import("{escape_avisynth_string(wsl_to_windows_path(str(script_file)))}")',
                "} catch (err_msg) {",
                "}",
            ]
        )
    return lines


def escape_avisynth_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n")


def _render_effect_template(template: str, params: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(params.get(key, match.group(0)))

    rendered = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, template)
    return _remove_auto_arguments(rendered)


def _remove_auto_arguments(script: str) -> str:
    auto = re.escape(AUTO_PARAMETER_VALUE)
    value_pattern = rf"(?:r?['\"])?{auto}(?:['\"])?"
    script = re.sub(rf",\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*{value_pattern}", "", script)
    script = re.sub(rf"\(\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*{value_pattern}\s*,\s*", "(", script)
    script = re.sub(rf"\(\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*{value_pattern}\s*\)", "()", script)
    return script


def _is_renderable_script_template(template: str | None) -> bool:
    if not template:
        return False
    return any(line.strip() and not line.lstrip().startswith("#") for line in template.splitlines())


def _runtime_available_for_render(effect: EffectDefinition) -> bool:
    if effect.install_status == "installed":
        return True
    return effect.install_policy in {"builtin", "bundled"} and effect.install_status != "missing"


def _prepare_staxrip_script(script: str, effect: EffectDefinition, engine: str) -> str:
    if effect.origin != "staxrip":
        return script
    cleaned = _remove_unresolved_macro_arguments(script)
    if engine == "avisynth":
        return _make_avisynth_filter_explicit(cleaned)
    return cleaned


def _remove_unresolved_macro_arguments(script: str) -> str:
    script = re.sub(r",\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*%[^%,)]+%", "", script)
    return script


def _make_avisynth_filter_explicit(script: str) -> str:
    lines: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if _is_bare_avisynth_call(stripped):
            lines.append(f"clip = clip.{stripped}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _is_bare_avisynth_call(line: str) -> bool:
    match = re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(", line)
    if not match:
        return False
    return "=" not in line[: match.end()] and not line.startswith("#")


def _vapoursynth_module_imports(script: str) -> list[str]:
    available = _bundled_vapoursynth_python_modules()
    if not available:
        return []
    ignored = {"clip", "core", "os", "sys", "vs"}
    modules: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\.", script):
        module = match.group(1)
        if module in ignored:
            continue
        if module.lower() in available:
            modules.extend(_collect_vapoursynth_python_dependencies_cached(module))
    return [f"import {module}" for module in dict.fromkeys(modules)]


@lru_cache(maxsize=1)
def _bundled_vapoursynth_python_modules() -> dict[str, Path]:
    return {path.stem.lower(): path for directory in bundled_vapoursynth_script_dirs() for path in directory.glob("*.py")}


@lru_cache(maxsize=None)
def _collect_vapoursynth_python_dependencies_cached(module: str) -> tuple[str, ...]:
    ignored = {"clip", "core", "os", "sys", "vs"}
    available = _bundled_vapoursynth_python_modules()
    return tuple(_collect_vapoursynth_python_dependencies(module, available, ignored))


def _collect_vapoursynth_python_dependencies(
    module: str,
    available: dict[str, Path],
    ignored: set[str],
    seen: set[str] | None = None,
) -> list[str]:
    seen = seen or set()
    canonical_path = available.get(module.lower())
    if not canonical_path:
        return []
    canonical = canonical_path.stem
    if canonical.lower() in seen:
        return []
    seen.add(canonical.lower())

    dependencies: list[str] = []
    try:
        text = canonical_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for imported in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", text, flags=re.MULTILINE):
        if imported in ignored or imported.lower() not in available:
            continue
        dependencies.extend(_collect_vapoursynth_python_dependencies(imported, available, ignored, seen))
    dependencies.append(canonical)
    return dependencies


def _load_staxrip_profile_effects() -> list[EffectDefinition]:
    source_root = Path("/mnt/c/StaxRip/sorgenti/Source/Video")
    files = [
        ("vapoursynth", source_root / "VapourSynthFilterProfileDefaults.txt"),
        ("avisynth", source_root / "AviSynthFilterProfileDefaults.txt"),
    ]
    effects: list[EffectDefinition] = []
    seen_ids: dict[str, int] = {}
    for engine, path in files:
        if not path.exists():
            continue
        profiles = parse_filter_profiles(path.read_text(encoding="utf-8-sig", errors="replace"), engine)  # type: ignore[arg-type]
        for profile in profiles:
            if not profile.script or profile.script.startswith("#"):
                continue
            if _is_context_only_staxrip_profile(profile):
                parameterized = _safe_noop_profile_script("Context-only StaxRip profile; not safe as an effect-chain filter.")
            else:
                parameterized = _parameterize_staxrip_profile_script(profile.script)
            base_effect_id = _staxrip_effect_id(engine, profile.category, profile.menu_path, profile.name)
            seen_ids[base_effect_id] = seen_ids.get(base_effect_id, 0) + 1
            effect_id = base_effect_id if seen_ids[base_effect_id] == 1 else f"{base_effect_id}-{seen_ids[base_effect_id]}"
            effects.append(
                EffectDefinition(
                    id=effect_id,
                    name=profile.name,
                    engine=engine,
                    category=_normalize_staxrip_category(profile.category),
                    description="StaxRip filter profile: " + " > ".join([profile.category, *profile.menu_path, profile.name]),
                    recommended=False,
                    required_plugins=_guess_required_plugins(profile),
                    install_status="installed",
                    install_policy="bundled",
                    install_allowed=False,
                    install_method="Bundled from local StaxRip profile defaults; runtime plugin availability is checked separately when known.",
                    source_url="",
                    license_status="manual_review",
                    license_notes="Imported from StaxRip filter profile defaults; component license is resolved through the StaxRip manifest when possible.",
                    parameters=parameterized["parameters"],
                    defaults=parameterized["defaults"],
                    script_template=parameterized["template"],
                    script_templates={engine: parameterized["template"]},
                    input_constraints="StaxRip profile macro placeholders may need project-context resolution.",
                    output_constraints="Depends on selected profile.",
                    menu_path=[profile.category, *profile.menu_path],
                    origin="staxrip",
                )
            )
    return effects


def _parameterize_staxrip_profile_script(script: str) -> dict[str, Any]:
    script = _resolve_staxrip_profile_macros(script)
    script = _stabilize_staxrip_profile_script(script)
    if "$" in script:
        return _raw_staxrip_profile_script(script)
    script = _remove_unresolved_macro_arguments(script)
    if re.search(r"%[A-Za-z0-9_]+%", script):
        return _safe_noop_profile_script("Unresolved StaxRip project placeholder; skipped until project context is available.")
    parameters: list[EffectParameter] = []
    defaults: dict[str, Any] = {}
    seen: set[str] = set()
    replacements: list[tuple[int, int, str]] = []

    def add_parameter(name: str, value: Any, raw: str, start: int, end: int, quoted: bool = False) -> None:
        if name in seen or name.lower() in {"clip"} or _is_macro_value(str(value)):
            return
        seen.add(name)
        parameter = _staxrip_parameter(name, value)
        parameters.append(parameter)
        defaults[name] = value
        placeholder = f"{{{name}}}"
        replacement = f"{raw[0]}{placeholder}{raw[-1]}" if quoted and len(raw) >= 2 else placeholder
        replacements.append((start, end, replacement))

    named_pattern = re.compile(
        r"(?P<prefix>[(,]\s*)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
        r"(?P<raw>(?P<quote>['\"])(?P<quoted>.*?)(?P=quote)|(?P<bare>[^,\)\r\n]+))"
    )
    for match in list(named_pattern.finditer(script)):
        name = match.group("name")
        raw = match.group("raw").strip()
        if raw.startswith("%"):
            continue
        value = _parse_staxrip_value(match.group("quoted") if match.group("quote") else raw)
        add_parameter(name, value, raw, match.start("raw"), match.end("raw"), quoted=bool(match.group("quote")))

    if not parameters:
        positional = re.search(r"\((?P<raw>\s*-?\d+(?:\.\d+)?\s*)(?=\)|,)", script)
        if positional:
            raw = positional.group("raw")
            value = _parse_staxrip_value(raw.strip())
            add_parameter("value", value, raw, positional.start("raw"), positional.end("raw"), quoted=False)

    if not parameters:
        raw = _raw_staxrip_profile_script(script)
        parameters = raw["parameters"]
        defaults = raw["defaults"]
        template = raw["template"]
    else:
        template = _apply_template_replacements(script, replacements)

    return {"parameters": parameters, "defaults": defaults, "template": template}


def _stabilize_staxrip_profile_script(script: str) -> str:
    if "havsfunc.QTGMC(clip," in script and "EdiMode=" not in script:
        script = script.replace("havsfunc.QTGMC(clip,", "havsfunc.QTGMC(clip, EdiMode='EEDI3',", 1)
    if "havsfunc.QTGMC(clip," in script:
        script = re.sub(r"\bSourceMatch\s*=\s*3\b", "SourceMatch=0", script)
    if "havsfunc.santiag(" in script:
        script = re.sub(r"\bopencl\s*=\s*True\b", "opencl=False", script)
    return script


def _raw_staxrip_profile_script(script: str) -> dict[str, Any]:
    return _safe_noop_profile_script("Unsupported interactive StaxRip profile; paste reviewed script to render.", include_raw=True)


def _safe_noop_profile_script(reason: str, include_raw: bool = False) -> dict[str, Any]:
    parameters = []
    defaults: dict[str, Any] = {}
    if include_raw:
        parameters = [
            EffectParameter(
                name="raw_script",
                type="string",
                default="",
                label="Script",
                description=reason,
            )
        ]
        defaults = {"raw_script": ""}
    return {
        "parameters": parameters,
        "defaults": defaults,
        "template": f"# {reason}",
    }


def _is_context_only_staxrip_profile(profile: Any) -> bool:
    path = " > ".join([profile.category, *profile.menu_path, profile.name]).lower()
    exact_names = {
        "animeivtc",
        "bm3dcpu",
        "convertfromdoublewidth",
        "cropresize",
        "dejump",
        "denoise md",
        "denoise mf",
        "dfttest2",
        "dither resize16 in linear light",
        "exactdedup",
        "fft3dgpu",
        "fix horizontal rainbow",
        "format",
        "gradfun3 16-bit",
        "gradfun3_16bit",
        "mdegrain3",
        "nnedi3 rpow2",
        "placebo",
        "qtgmc with repair",
        "removegrain with repair",
        "removegrain16 with repair16",
        "resamplehq",
        "resizemt",
        "set max memory",
        "svpflow",
        "to rgb / yuv",
        "to rgb/yuv",
        "unspec",
        "vfrtocfr",
    }
    if profile.name.lower() in exact_names:
        return True
    if profile.category.lower() == "source":
        return True
    if "assumefps source" in path or "anamorphic to standard" in path:
        return True
    if "colorspace > matrix" in path or "colorspace > primaries" in path or "colorspace > transfer" in path:
        return True
    if "cube" in path:
        return True
    return False


def _resolve_staxrip_profile_macros(script: str) -> str:
    previous = script
    for _ in range(12):
        resolved = re.sub(r"\$(select|enter_text|browse_file)(?::([^$]*))?\$", _staxrip_macro_value, previous, flags=re.IGNORECASE)
        if resolved == previous:
            return resolved
        previous = resolved
    return previous


def _staxrip_macro_value(match: re.Match[str]) -> str:
    macro = match.group(1).lower()
    payload = match.group(2) or ""
    if macro == "select":
        return _staxrip_select_default(payload)
    if macro == "enter_text":
        return _staxrip_enter_text_default(payload)
    return ""


def _staxrip_select_default(payload: str) -> str:
    parts = [part.strip() for part in payload.split(";") if part.strip()]
    if not parts:
        return ""
    options = parts[1:] if parts[0].lower().startswith("msg:") else parts
    if not options:
        return ""
    chosen = next((option for option in options if "slower" in option.lower()), "")
    if not chosen:
        chosen = next((option for option in options if "default" in option.lower()), options[0])
    if "|" in chosen:
        chosen = chosen.split("|", 1)[1].strip()
    return chosen.strip().strip('"')


def _staxrip_enter_text_default(payload: str) -> str:
    default_match = re.search(r"default:\s*([+-]?\d+(?:\.\d+)?)", payload, flags=re.IGNORECASE)
    if default_match:
        return default_match.group(1)
    range_match = re.search(r"range:\s*([+-]?\d+(?:\.\d+)?)\s+to\s+([+-]?\d+(?:\.\d+)?)", payload, flags=re.IGNORECASE)
    if range_match:
        return range_match.group(1)
    return "0"


def _apply_template_replacements(script: str, replacements: list[tuple[int, int, str]]) -> str:
    if not replacements:
        return script
    parts: list[str] = []
    cursor = 0
    for start, end, replacement in sorted(replacements, key=lambda item: item[0]):
        parts.append(script[cursor:start])
        parts.append(replacement)
        cursor = end
    parts.append(script[cursor:])
    return "".join(parts)


def _parse_staxrip_value(value: str) -> Any:
    stripped = value.strip()
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    try:
        if re.match(r"^-?\d+$", stripped):
            return int(stripped)
        if re.match(r"^-?\d+\.\d+$", stripped):
            return float(stripped)
    except ValueError:
        pass
    return stripped


def _is_macro_value(value: str) -> bool:
    return value.strip().startswith("%") and value.strip().endswith("%")


def _staxrip_parameter(name: str, value: Any) -> EffectParameter:
    label = name.replace("_", " ")
    description = f"StaxRip parameter `{name}` from the imported filter profile."
    if isinstance(value, bool):
        return EffectParameter(name=name, type="bool", default=value, label=label, description=description)
    if isinstance(value, int) and not isinstance(value, bool):
        min_value, max_value, step = _staxrip_numeric_bounds(name, float(value), is_float=False)
        return EffectParameter(
            name=name,
            type="int",
            default=value,
            min=min_value,
            max=max_value,
            step=step,
            label=label,
            description=description,
        )
    if isinstance(value, float):
        min_value, max_value, step = _staxrip_numeric_bounds(name, value, is_float=True)
        return EffectParameter(
            name=name,
            type="float",
            default=value,
            min=min_value,
            max=max_value,
            step=step,
            label=label,
            description=description,
        )
    return EffectParameter(name=name, type="string", default=value, label=label, description=description)


def _staxrip_numeric_bounds(name: str, value: float, is_float: bool) -> tuple[float, float, float]:
    lowered = name.lower()
    if any(token in lowered for token in ["threshold", "thresh"]):
        upper = max(100.0, value * 2)
        return 0.0, upper, 0.1 if is_float else 1.0
    if any(token in lowered for token in ["strength", "amount", "sharp", "value"]):
        upper = max(100.0, value * 2)
        return 0.0, upper, 0.1 if is_float else 1.0
    if lowered in {"ss_x", "ss_y"}:
        return 0.5, 4.0, 0.05
    upper = max(10.0, value * 2 if value > 0 else 10.0)
    lower = min(0.0, value * 2 if value < 0 else 0.0)
    return lower, upper, 0.1 if is_float else 1.0


def _staxrip_effect_id(engine: str, category: str, menu_path: list[str], name: str) -> str:
    return "staxrip." + ".".join([_slug(engine), _slug(category), *[_slug(part) for part in menu_path], _slug(name)])


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "effect"


def _normalize_staxrip_category(category: str) -> str:
    mapping = {
        "field": "deinterlace",
        "frame rate": "frame interpolation",
        "line": "sharpen",
        "misc": "custom",
        "noise": "denoise",
        "restoration": "repair",
    }
    return mapping.get(category.lower(), category.lower())


def _guess_required_plugins(profile: Any) -> list[str]:
    haystack = " ".join([profile.name, *profile.menu_path, profile.script])
    candidates = [
        "AddGrain",
        "AddGrainC",
        "BM3D",
        "BM3DCPU",
        "BM3DCUDA",
        "BM3DCUDA_RTC",
        "CAS",
        "DFTTest",
        "DeGrainMedian",
        "DeNoiseMD",
        "DeNoiseMF",
        "DeHalo_alpha",
        "FFT3D",
        "HQDN3D",
        "KNLMeansCL",
        "MCTemporalDenoise",
        "mClean",
        "MDegrain",
        "QTGMC",
        "SMDegrain",
        "VagueDenoiser",
        "f3kdb",
        "neo_f3kdb",
    ]
    return [candidate for candidate in candidates if candidate.lower() in haystack.lower()]


def _apply_staxrip_bundle_metadata(effects: list[EffectDefinition]) -> None:
    manifest_path = Path(__file__).parents[2] / "vendor" / "staxrip" / "manifest.json"
    if not manifest_path.exists():
        return

    import json

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    components = manifest.get("components", [])
    for effect in effects:
        if effect.install_status == "installed" or not effect.required_plugins:
            continue
        matches = [
            component
            for component in components
            if component.get("installed_paths") and _component_matches_required_plugin(component, effect.required_plugins)
        ]
        if not matches:
            continue

        licenses = sorted({match.get("license_status", "manual_review") for match in matches})
        effect.install_status = "installed"
        effect.install_policy = "bundled"
        effect.install_method = "Bundled from local StaxRip import."
        effect.license_status = licenses[0] if len(licenses) == 1 else "mixed"
        effect.license_notes = "Detected in local StaxRip bundle; review manifest before redistribution."


def _filter_renderable_new_effects(
    discovered_effects: list[EffectDefinition],
    existing_effects: list[EffectDefinition],
) -> list[EffectDefinition]:
    existing_keys = _render_call_identity_keys(existing_effects)
    filtered: list[EffectDefinition] = []
    for effect in discovered_effects:
        if effect.category not in {"new", "new2", "new3"}:
            continue
        if not effect.renderable:
            continue
        keys = _render_call_identity_keys([effect])
        if keys & existing_keys:
            continue
        filtered.append(effect)
        existing_keys.update(keys)
    return filtered


def _render_call_identity_keys(effects: list[EffectDefinition]) -> set[str]:
    keys: set[str] = set()
    for effect in effects:
        templates = [effect.script_template, *effect.script_templates.values()]
        for template in templates:
            for token in re.findall(r"\b(?:core\.)?([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*\(", template):
                keys.add(f"call:{effect.engine}:{token.lower()}")
    return keys


def _effect_identity_keys(effects: list[EffectDefinition]) -> set[str]:
    keys: set[str] = set()
    for effect in effects:
        keys.add(f"name:{effect.engine}:{_slug(effect.name)}")
        for plugin in effect.required_plugins:
            for token in _requirement_tokens(plugin.lower()):
                keys.add(f"plugin:{effect.engine}:{token}")
        for token in re.findall(r"\b(?:core\.)?([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*\(", effect.script_template):
            keys.add(f"call:{effect.engine}:{token.lower()}")
    return keys


def _component_matches_required_plugin(component: dict[str, Any], required_plugins: list[str]) -> bool:
    component_tokens = _component_identity_tokens(component)
    for plugin in required_plugins:
        needle = plugin.lower()
        for token in _requirement_tokens(needle):
            if token in component_tokens:
                return True
    return False


def _component_identity_tokens(component: dict[str, Any]) -> set[str]:
    values = [
        str(component.get("name", "")),
        str(component.get("filename", "")),
        *[str(item) for item in component.get("avs_filter_names", [])],
        *[str(item) for item in component.get("vs_filter_names", [])],
    ]
    tokens: set[str] = set()
    for value in values:
        lowered = value.lower()
        tokens.add(lowered)
        tokens.update(re.findall(r"[a-z0-9_.+-]{3,}", lowered))
        tokens.update(part for part in re.split(r"[^a-z0-9]+", lowered) if len(part) >= 3)
    return tokens


def _requirement_tokens(value: str) -> list[str]:
    ignored = {
        "adapter",
        "compatible",
        "dependencies",
        "files",
        "future",
        "model",
        "optional",
        "plugin",
        "plugins",
        "script",
    }
    return [token for token in re.findall(r"[a-z0-9_.+-]{3,}", value) if token not in ignored]
