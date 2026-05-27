from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from deepframe_api.effects import (
    AUTO_PARAMETER_VALUE,
    EffectDefinition,
    EffectParameter,
    _effect_identity_keys,
    _render_effect_template,
    _slug,
    _vapoursynth_module_imports,
    bundled_vapoursynth_plugin_load_lines,
    bundled_vapoursynth_script_dirs,
    bundled_vapoursynth_script_path_lines,
)
from deepframe_api.path_tools import project_root, wsl_to_windows_path
from deepframe_api.script_adapters import tool_env


HEAVY_PACKAGE_TOKENS = {
    "ai",
    "anime4k",
    "cuda-runtime",
    "cuda",
    "cugan",
    "cudnn",
    "dpir",
    "esrgan",
    "libtorch",
    "gpu",
    "hip",
    "model",
    "models",
    "ncnn",
    "onnx",
    "openvino",
    "opencl",
    "pytorch",
    "realesr",
    "realcugan",
    "runtime",
    "runtimes",
    "srmd",
    "sycl",
    "swinir",
    "tensorrt",
    "torch",
    "trt",
    "vsmlrt",
    "waifu",
}


PROMOTION_BUCKET = "new2"

HEAVY_TRANSITIVE_PACKAGES = {
    "com.vapoursynth.bm3d": "heavy_transitive_runtime",
    "com.wolframrhodium.bm3dcpu": "heavy_transitive_runtime",
    "com.holywu.depan": "missing_runtime_dependency",
}


def default_vapoursynth_runtime_dir() -> Path:
    return project_root() / "vendor" / "staxrip" / "bundle" / "Apps" / "FrameServer" / "VapourSynth"


def default_discovered_effects_path() -> Path:
    return project_root() / "backend" / "deepframe_api" / "resources" / "effects" / "discovered_effects.yaml"


def load_vsrepo_packages(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    packages = data.get("packages", []) if isinstance(data, dict) else data
    return [package for package in packages if isinstance(package, dict)]


def should_skip_vsrepo_package(package: dict[str, Any]) -> tuple[bool, str]:
    key = vsrepo_install_key(package).lower()
    if key in HEAVY_TRANSITIVE_PACKAGES:
        return True, HEAVY_TRANSITIVE_PACKAGES[key]
    text = " ".join(
        str(package.get(key, ""))
        for key in ("identifier", "namespace", "name", "description", "category", "type")
    ).lower()
    tokens = set(re.findall(r"[a-z0-9]+", text.replace("_", " ").replace("-", " ")))
    hit = sorted(tokens & HEAVY_PACKAGE_TOKENS)
    if hit:
        return True, f"heavy_or_model_package:{hit[0]}"
    if package.get("type") not in {"VSPlugin", "PyScript"}:
        return True, f"unsupported_type:{package.get('type', 'unknown')}"
    return False, ""


def vsrepo_install_key(package: dict[str, Any]) -> str:
    return str(package.get("identifier") or package.get("namespace") or package.get("modulename") or package.get("name"))


def run_vsrepo_update(runtime_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    runtime_dir = runtime_dir or default_vapoursynth_runtime_dir()
    return subprocess.run(
        [str(runtime_dir / "python.exe"), "vsrepo.py", "update"],
        cwd=str(runtime_dir),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=tool_env(runtime_dir),
    )


def run_vsrepo_install(package: dict[str, Any], runtime_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    runtime_dir = runtime_dir or default_vapoursynth_runtime_dir()
    return subprocess.run(
        [str(runtime_dir / "python.exe"), "vsrepo.py", "install", vsrepo_install_key(package)],
        cwd=str(runtime_dir),
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
        env=tool_env(runtime_dir),
    )


def introspect_vapoursynth(runtime_dir: Path | None = None, output_path: Path | None = None) -> list[dict[str, Any]]:
    runtime_dir = runtime_dir or default_vapoursynth_runtime_dir()
    output_path = output_path or (project_root() / "artifacts" / "plugin-promotion" / "vapoursynth_introspection.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    script_path = output_path.with_suffix(".vpy")
    script_path.write_text(_vapoursynth_introspection_script(wsl_to_windows_path(str(output_path))), encoding="utf-8")
    command = [str(runtime_dir / "VSPipe.exe"), "--info", wsl_to_windows_path(str(script_path)), "-"]
    result = subprocess.run(
        command,
        cwd=str(runtime_dir),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=tool_env(runtime_dir),
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "VapourSynth introspection failed")[-4000:])
    return json.loads(output_path.read_text(encoding="utf-8"))


def _vapoursynth_introspection_script(output_path: str) -> str:
    return f"""
import inspect
import json
from pathlib import Path
import vapoursynth as vs

core = vs.core
items = []
for plugin in core.plugins():
    namespace = getattr(plugin, "namespace", "")
    identifier = getattr(plugin, "identifier", "")
    plugin_name = getattr(plugin, "name", "")
    for function_name in dir(plugin):
        if function_name.startswith("_"):
            continue
        function = getattr(plugin, function_name)
        if function.__class__.__name__ != "Function":
            continue
        try:
            signature = str(inspect.signature(function))
        except Exception as exc:
            signature = ""
        items.append({{
            "identifier": identifier,
            "namespace": namespace,
            "plugin_name": plugin_name,
            "function": function_name,
            "signature": signature,
        }})
Path({output_path!r}).write_text(json.dumps(items, indent=2, sort_keys=True), encoding="utf-8")
""".strip() + "\n"


def merge_introspection_with_packages(
    introspection: list[dict[str, Any]],
    packages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_namespace = {str(package.get("namespace") or package.get("modulename") or "").lower(): package for package in packages}
    by_identifier = {str(package.get("identifier") or "").lower(): package for package in packages}
    merged: list[dict[str, Any]] = []
    for item in introspection:
        package = by_identifier.get(str(item.get("identifier", "")).lower()) or by_namespace.get(str(item.get("namespace", "")).lower()) or {}
        merged.append(
            {
                **item,
                "package_id": vsrepo_install_key(package) if package else str(item.get("identifier") or item.get("namespace")),
                "package_name": package.get("name") or item.get("plugin_name") or item.get("namespace"),
                "package_category": package.get("category") or "",
                "source_url": package.get("github") or package.get("website") or "",
                "description": package.get("description") or item.get("plugin_name") or "",
            }
        )
    return merged


def filter_introspection_by_namespaces(
    introspection: list[dict[str, Any]],
    namespaces: set[str],
) -> list[dict[str, Any]]:
    normalized = {namespace.lower() for namespace in namespaces if namespace}
    return [item for item in introspection if str(item.get("namespace", "")).lower() in normalized]


def build_vapoursynth_effects_from_introspection(
    introspection: list[dict[str, Any]],
    existing_effects: list[EffectDefinition],
    bucket: str = PROMOTION_BUCKET,
) -> list[EffectDefinition]:
    existing_keys = _call_identity_keys(existing_effects)
    effects: list[EffectDefinition] = []
    for item in introspection:
        parsed = parse_vapoursynth_signature(str(item.get("signature") or ""))
        if not parsed or not parsed["clip_parameter"]:
            continue
        if parsed["required_video_parameters"]:
            continue
        namespace = str(item.get("namespace") or "").strip()
        function = str(item.get("function") or "").strip()
        if not namespace or not function:
            continue
        suggested_category = categorize_external_effect(
            str(item.get("package_category") or ""),
            [str(item.get("package_name") or ""), str(item.get("description") or ""), function, namespace],
        )
        parameters = [_parameter_from_signature(param) for param in parsed["optional_parameters"]]
        parameters = [parameter for parameter in parameters if parameter is not None]
        defaults = {parameter.name: parameter.default for parameter in parameters}
        args = [_template_argument(parameter) for parameter in parameters]
        suffix = ", " + ", ".join(args) if args else ""
        script_template = f"clip = core.{namespace}.{function}(clip{suffix})"
        effect = EffectDefinition(
            id=f"external.vsrepo.{bucket}.{_slug(namespace)}.{_slug(function)}",
            name=function,
            engine="vapoursynth",
            category=bucket,
            suggested_category=suggested_category,
            description=str(item.get("description") or f"VapourSynth {namespace}.{function}"),
            recommended=False,
            required_plugins=[namespace],
            install_status="installed",
            install_policy="bundled",
            install_allowed=False,
            install_method="Installed into bundled VapourSynth runtime through VSRepo and validated locally.",
            source_url=str(item.get("source_url") or ""),
            license_status="manual_review",
            license_notes="Installed from VSRepo metadata; review upstream license before redistribution.",
            parameters=parameters,
            defaults=defaults,
            script_template=script_template,
            script_templates={"vapoursynth": script_template},
            input_constraints="Validated on a synthetic VapourSynth clip; real-source constraints may vary by plugin.",
            output_constraints="Usually same dimensions unless the filter changes geometry.",
            menu_path=[bucket, suggested_category, str(item.get("package_category") or "").strip() or "VSRepo"],
            origin="external",
            discovery_source="vsrepo_runtime",
            discovery_tags=["vsrepo", "installed", "validated_candidate"],
            validation_status="runtime_validated",
        )
        keys = _call_identity_keys([effect])
        if keys & existing_keys:
            continue
        effects.append(effect)
        existing_keys.update(keys)
    return effects


CLIP_PARAMETER_NAMES = {"clip", "src", "input", "c", "video"}


def build_vapoursynth_script_effects_from_files(
    script_files: list[Path],
    existing_effects: list[EffectDefinition],
    bucket: str = "new3",
) -> list[EffectDefinition]:
    existing_keys = _call_identity_keys(existing_effects) | _effect_identity_keys(existing_effects)
    effects: list[EffectDefinition] = []
    for script_file in sorted(script_files, key=lambda path: str(path).lower()):
        module = script_file.stem
        try:
            tree = ast.parse(script_file.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            effect = _effect_from_vapoursynth_script_function(module, node, script_file, bucket)
            if effect is None:
                continue
            keys = _call_identity_keys([effect]) | _effect_identity_keys([effect])
            if keys & existing_keys:
                continue
            effects.append(effect)
            existing_keys.update(keys)
    return effects


def discover_local_vapoursynth_script_files() -> list[Path]:
    return sorted(
        {
            script_file
            for directory in bundled_vapoursynth_script_dirs()
            for script_file in directory.glob("*.py")
            if _is_promotable_vapoursynth_script_file(script_file)
        },
        key=lambda path: str(path).lower(),
    )


def _is_promotable_vapoursynth_script_file(script_file: Path) -> bool:
    if script_file.name.startswith("_"):
        return False
    if (script_file.parent / "__init__.py").exists() and script_file.stem.lower() != script_file.parent.name.lower():
        return False
    return True


def _effect_from_vapoursynth_script_function(
    module: str,
    node: ast.FunctionDef,
    script_file: Path,
    bucket: str,
) -> EffectDefinition | None:
    args = list(node.args.args)
    if not args:
        return None
    clip_arg = args[0].arg
    if clip_arg.lower() not in CLIP_PARAMETER_NAMES:
        return None
    required_count = len(args) - len(node.args.defaults)
    required_defaults: dict[str, Any] = {}
    for arg in args[1:required_count]:
        default = _required_script_parameter_default(arg.arg)
        if default is MISSING:
            return None
        required_defaults[arg.arg] = default
    if required_count > 1 and len(required_defaults) != required_count - 1:
        return None

    default_by_name = {**required_defaults, **_function_defaults_by_name(args, node.args.defaults)}
    keyword_defaults = _keyword_defaults_by_name(node.args.kwonlyargs, node.args.kw_defaults)
    parameter_defaults = {**default_by_name, **keyword_defaults}
    parameters: list[EffectParameter] = []
    defaults: dict[str, Any] = {}
    for name, default in parameter_defaults.items():
        if name == clip_arg:
            continue
        parameter = _parameter_from_script_default(name, default)
        if parameter is None:
            continue
        parameters.append(parameter)
        defaults[name] = parameter.default

    args_template = [_template_argument(parameter) for parameter in parameters]
    suffix = ", " + ", ".join(args_template) if args_template else ""
    function_name = node.name
    script_template = f"clip = {module}.{function_name}(clip{suffix})"
    suggested_category = categorize_external_effect("", [module, function_name, script_file.name])
    return EffectDefinition(
        id=f"external.local-vs-script.{bucket}.{_slug(module)}.{_slug(function_name)}",
        name=function_name,
        engine="vapoursynth",
        category=bucket,
        suggested_category=suggested_category,
        description=f"Bundled VapourSynth script function {module}.{function_name} from the local StaxRip/GitHub script bundle.",
        recommended=False,
        required_plugins=[module],
        install_status="installed",
        install_policy="bundled",
        install_allowed=False,
        install_method="Bundled from local script import and promoted only after local render validation.",
        source_url="",
        license_status="manual_review",
        license_notes="Local script bundle entry; review upstream script license before redistribution.",
        parameters=parameters,
        defaults=defaults,
        script_template=script_template,
        script_templates={"vapoursynth": script_template},
        script_imports=[f"import {module}"],
        input_constraints="Validated on a synthetic VapourSynth clip; real-source constraints may vary by script.",
        output_constraints="Depends on selected script function.",
        menu_path=[bucket, suggested_category, module],
        origin="external",
        discovery_source="local_vapoursynth_script_bundle",
        discovery_tags=["local_script", "staxrip_bundle", "validated_candidate"],
        validation_status="runtime_validated",
    )


def _function_defaults_by_name(args: list[ast.arg], defaults: list[ast.expr]) -> dict[str, Any]:
    if not defaults:
        return {}
    names = [arg.arg for arg in args[-len(defaults) :]]
    result: dict[str, Any] = {}
    for name, value in zip(names, defaults, strict=True):
        parsed = _literal_ast_default(value)
        if parsed is not MISSING:
            result[name] = parsed
    return result


def _keyword_defaults_by_name(args: list[ast.arg], defaults: list[ast.expr | None]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arg, value in zip(args, defaults, strict=True):
        if value is None:
            continue
        parsed = _literal_ast_default(value)
        if parsed is not MISSING:
            result[arg.arg] = parsed
    return result


def _literal_ast_default(value: ast.expr) -> Any:
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return MISSING


def _parameter_from_script_default(name: str, default: Any) -> EffectParameter | None:
    label = name.replace("_", " ")
    description = f"VapourSynth script parameter `{name}` from the bundled function signature."
    if default is None:
        geometry_default = _optional_geometry_parameter_default(name)
        if geometry_default is not MISSING:
            return EffectParameter(
                name=name,
                type="int",
                default=geometry_default,
                min=1,
                max=8192,
                step=1,
                label=label,
                description=description,
            )
        inferred_type = _infer_script_optional_parameter_type(name)
        if inferred_type is None:
            return None
        suggested = _suggested_auto_value(inferred_type, name)
        kwargs = _parameter_bounds(inferred_type, name, suggested)
        return EffectParameter(
            name=name,
            type=inferred_type,
            default=AUTO_PARAMETER_VALUE,
            label=label,
            description=f"{description} Auto omits this argument and lets the script use its internal default.",
            auto=True,
            auto_value=AUTO_PARAMETER_VALUE,
            suggested=suggested,
            **kwargs,
        )
    if isinstance(default, bool):
        return EffectParameter(name=name, type="bool", default=default, label=label, description=description)
    if isinstance(default, int) and not isinstance(default, bool):
        return EffectParameter(name=name, type="int", default=default, min=0, max=max(10, default * 4), step=1, label=label, description=description)
    if isinstance(default, float):
        upper = max(1.0, abs(default) * 4)
        return EffectParameter(name=name, type="float", default=default, min=0, max=upper, step=0.05, label=label, description=description)
    if isinstance(default, str) and len(default) <= 80:
        return EffectParameter(name=name, type="string", default=default, label=label, description=description)
    return None


def _infer_script_optional_parameter_type(name: str) -> str | None:
    lowered = name.lower()
    if lowered in {"planes", "plane", "opt", "cpuopt", "nsize", "nns", "qual", "pscrn"}:
        return "int"
    if any(token in lowered for token in ["enabled", "show", "opencl", "chroma", "tff", "full"]):
        return "bool"
    if any(token in lowered for token in ["preset", "mode", "kernel", "matrix", "device", "type"]):
        return "string"
    if any(token in lowered for token in ["sigma", "threshold", "thresh", "sharp", "strength", "amount", "radius", "limit"]):
        return "float"
    return None


def _required_script_parameter_default(name: str) -> Any:
    geometry_default = _optional_geometry_parameter_default(name)
    if geometry_default is not MISSING:
        return geometry_default
    return MISSING


def _optional_geometry_parameter_default(name: str) -> Any:
    lowered = name.lower()
    if lowered in {"width", "target_width", "descale_width", "ow"} or lowered.endswith("_width"):
        return 128
    if lowered in {"height", "target_height", "descale_height", "oh"} or lowered.endswith("_height"):
        return 72
    if lowered == "w":
        return 128
    if lowered == "h":
        return 72
    return MISSING


def _call_identity_keys(effects: list[EffectDefinition]) -> set[str]:
    keys: set[str] = set()
    for effect in effects:
        for template in [effect.script_template, *effect.script_templates.values()]:
            for token in re.findall(r"\b(?:core\.)?([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*\(", template):
                keys.add(f"call:{effect.engine}:{token.lower()}")
    return keys


def parse_vapoursynth_signature(signature: str) -> dict[str, Any] | None:
    match = re.search(r"\((?P<params>.*)\)", signature)
    if not match:
        return None
    params: list[dict[str, Any]] = []
    for position, part in enumerate(split_top_level_commas(match.group("params"))):
        param = _parse_signature_parameter(part)
        if param is None:
            continue
        param["position"] = position
        params.append(param)
    if not params:
        return None
    clip_parameter = next((param for param in params if is_video_param(param) and param["position"] == 0), None)
    required_video_parameters = [
        param
        for param in params
        if is_video_param(param) and param is not clip_parameter and param["default"] is MISSING
    ]
    optional_parameters = [
        param
        for param in params
        if not is_video_param(param) and param["default"] is not MISSING and is_supported_default(param["default"])
    ]
    return {
        "clip_parameter": clip_parameter,
        "required_video_parameters": required_video_parameters,
        "optional_parameters": optional_parameters,
    }


MISSING = object()


def _parse_signature_parameter(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if not raw or raw.startswith("*"):
        return None
    if ":" not in raw:
        return None
    name, rest = raw.split(":", 1)
    name = name.strip()
    annotation = rest.strip()
    default: Any = MISSING
    if "=" in annotation:
        annotation, default_raw = annotation.rsplit("=", 1)
        default = parse_signature_default(default_raw.strip())
    return {
        "name": name,
        "annotation": annotation.strip(),
        "default": default,
        "position": -1,
    }


def split_top_level_commas(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for index, char in enumerate(value):
        if quote:
            if char == quote and value[index - 1 : index] != "\\":
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return [part.strip() for part in parts if part.strip()]


def parse_signature_default(value: str) -> Any:
    if value == "None":
        return None
    if value in {"True", "False"}:
        return value == "True"
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def is_video_param(param: dict[str, Any]) -> bool:
    return "VideoNode" in str(param.get("annotation", ""))


def is_supported_default(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _parameter_from_signature(param: dict[str, Any]) -> EffectParameter | None:
    default = param["default"]
    name = str(param["name"])
    annotation = str(param.get("annotation") or "")
    label = name.replace("_", " ")
    description = f"VapourSynth parameter `{name}` from the plugin signature."
    if default is None:
        inferred_type = _infer_optional_parameter_type(annotation, name)
        if inferred_type is None:
            return None
        suggested = _suggested_auto_value(inferred_type, name)
        kwargs = _parameter_bounds(inferred_type, name, suggested)
        return EffectParameter(
            name=name,
            type=inferred_type,
            default=AUTO_PARAMETER_VALUE,
            label=label,
            description=f"{description} Auto omits this argument and lets the plugin use its internal default.",
            auto=True,
            auto_value=AUTO_PARAMETER_VALUE,
            suggested=suggested,
            **kwargs,
        )
    if isinstance(default, bool):
        return EffectParameter(name=name, type="bool", default=default, label=label, description=description)
    if isinstance(default, int) and not isinstance(default, bool):
        return EffectParameter(name=name, type="int", default=default, min=0, max=max(10, default * 4), step=1, label=label, description=description)
    if isinstance(default, float):
        upper = max(1.0, abs(default) * 4)
        return EffectParameter(name=name, type="float", default=default, min=0, max=upper, step=0.05, label=label, description=description)
    if isinstance(default, str) and len(default) <= 80:
        return EffectParameter(name=name, type="string", default=default, label=label, description=description)
    return None


def _infer_optional_parameter_type(annotation: str, name: str) -> str | None:
    lowered = f"{annotation} {name}".lower()
    if any(token in lowered for token in ["videonode", "func", "callable"]):
        return None
    if "bool" in lowered:
        return "bool"
    if "float" in lowered:
        return "float"
    if any(token in lowered for token in ["str", "bytes", "bytearray"]):
        return "string"
    if "int" in lowered:
        return "int"
    return None


def _suggested_auto_value(parameter_type: str, name: str) -> Any:
    lowered = name.lower()
    if parameter_type == "bool":
        return False
    if parameter_type == "string":
        return ""
    if parameter_type == "float":
        if any(token in lowered for token in ["sigma", "threshold", "thresh", "sharp", "strength", "amount"]):
            return 1.0
        return 0.0
    if lowered in {"planes", "plane"}:
        return 0
    if lowered in {"opt", "cpuopt"}:
        return 0
    if "radius" in lowered or lowered in {"range", "blur", "taps"}:
        return 1
    return 0


def _parameter_bounds(parameter_type: str, name: str, suggested: Any) -> dict[str, Any]:
    if parameter_type not in {"int", "float"}:
        return {}
    lowered = name.lower()
    step = 0.05 if parameter_type == "float" else 1
    if lowered in {"planes", "plane"}:
        return {"min": 0, "max": 3, "step": 1}
    if lowered in {"opt", "cpuopt"}:
        return {"min": 0, "max": 4, "step": 1}
    if "radius" in lowered or lowered in {"range", "blur", "taps"}:
        return {"min": 0, "max": 64, "step": step}
    if any(token in lowered for token in ["sigma", "threshold", "thresh"]):
        return {"min": 0, "max": 32, "step": step}
    if any(token in lowered for token in ["strength", "amount", "sharp", "scale"]):
        return {"min": 0, "max": 8 if parameter_type == "float" else 255, "step": step}
    if isinstance(suggested, (int, float)):
        return {"min": min(0, suggested), "max": max(10, suggested * 4 if suggested else 10), "step": step}
    return {}


def _template_argument(parameter: EffectParameter) -> str:
    if parameter.type == "string":
        return f"{parameter.name}='{{{parameter.name}}}'"
    return f"{parameter.name}={{{parameter.name}}}"


def categorize_external_effect(package_category: str, tags: list[str]) -> str:
    text = " ".join([package_category, *tags]).lower()
    mapping = [
        ("deinterlace", ["deinterlac", "field", "ivtc", "inverse telecine"]),
        ("deband", ["deband", "banding", "gradfun"]),
        ("repair", ["repair", "restore", "dehalo", "dering", "artifact", "deblock", "dedot", "dot crawl", "rainbow", "mask", "exinpand", "inpand"]),
        ("sharpen", ["sharpen", "sharp", "warp", "edge", "seesaw"]),
        ("denoise", ["denois", "noise", "smooth", "grain", "median", "nrdb", "xclean", "stpresso", "spresso"]),
        ("blur", ["blur"]),
        ("resize", ["resize", "scale", "descale", "resample", "format"]),
        ("color", ["color", "levels", "curve", "hdr", "tonemap", "lut", "matrix", "depth"]),
        ("frame interpolation", ["frame", "interpolat", "fps", "motion"]),
        ("stabilize", ["stabil"]),
        ("encode", ["encode"]),
    ]
    for category, needles in mapping:
        if any(needle in text for needle in needles):
            return category
    return "custom"


def validate_vapoursynth_effect(effect: EffectDefinition, runtime_dir: Path | None = None) -> dict[str, Any]:
    runtime_dir = runtime_dir or default_vapoursynth_runtime_dir()
    validation_dir = project_root() / "artifacts" / "plugin-promotion" / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    script_path = validation_dir / f"{effect.id}.vpy"
    params = dict(effect.defaults)
    rendered = _render_effect_template(effect.script_template, params)
    imports: list[str] = []
    for import_line in [*effect.script_imports, *_vapoursynth_module_imports(rendered)]:
        if import_line not in imports:
            imports.append(import_line)
    script = "\n".join(
        [
            "import os, sys",
            "import vapoursynth as vs",
            *bundled_vapoursynth_script_path_lines(),
            "core = vs.core",
            "if not hasattr(vs, 'get_core'):",
            "    vs.get_core = lambda: core",
            *bundled_vapoursynth_plugin_load_lines(),
            *imports,
            "clip = core.std.BlankClip(width=128, height=72, length=64, format=vs.YUV420P8)",
            rendered,
            "clip.set_output()",
            "",
        ]
    )
    script_path.write_text(script, encoding="utf-8")
    command = [str(runtime_dir / "VSPipe.exe"), "--info", wsl_to_windows_path(str(script_path)), "-"]
    try:
        result = subprocess.run(
            command,
            cwd=str(runtime_dir),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=tool_env(runtime_dir),
        )
        return {
            "effect_id": effect.id,
            "ok": result.returncode == 0,
            "command": command,
            "stdout": (result.stdout or "")[-1200:],
            "stderr": (result.stderr or "")[-1200:],
        }
    except subprocess.TimeoutExpired:
        return {"effect_id": effect.id, "ok": False, "command": command, "stdout": "", "stderr": "timeout"}


def filter_validated_vapoursynth_effects(effects: list[EffectDefinition], runtime_dir: Path | None = None) -> tuple[list[EffectDefinition], list[dict[str, Any]]]:
    valid: list[EffectDefinition] = []
    reports: list[dict[str, Any]] = []
    for effect in effects:
        report = validate_vapoursynth_effect(effect, runtime_dir=runtime_dir)
        reports.append(report)
        if report["ok"]:
            valid.append(effect)
    return valid, reports


def select_avisynth_win64_asset(package: dict[str, Any]) -> dict[str, Any]:
    for release in package.get("releases", []):
        asset = release.get("win64") if isinstance(release, dict) else None
        if asset and asset.get("url") and asset.get("files"):
            return {"url": asset["url"], "files": _normalize_avs_files(asset["files"]), "version": release.get("version", "")}
    return {}


def _normalize_avs_files(files: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in files.items():
        if isinstance(value, str):
            normalized[name] = value
        elif isinstance(value, list) and len(value) >= 2:
            normalized[str(value[0])] = str(value[1])
    return normalized


def write_promoted_effects(path: Path, effects: list[EffectDefinition], replace_categories: set[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    replace = set(replace_categories or {effect.category for effect in effects})
    incoming_by_id = {effect.id: effect for effect in effects}
    merged: list[EffectDefinition] = []
    if path.exists():
        existing_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in existing_data.get("effects", []):
            effect = EffectDefinition.model_validate(item)
            if effect.category in replace or effect.id in incoming_by_id:
                continue
            merged.append(effect)
    merged.extend(incoming_by_id.values())
    data = {
        "metadata": {
            "generated_by": "plugin_promoter",
            "policy": (
                "Runtime registry only. New/new2/new3 entries are installed, deduplicated, "
                "templated, and locally render-validated."
            ),
        },
        "effects": [effect.model_dump(exclude_none=True) for effect in merged],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")
