#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from deepframe_api.effects import EffectRegistry
from deepframe_api.plugin_promoter import (
    build_vapoursynth_script_effects_from_files,
    build_vapoursynth_effects_from_introspection,
    default_discovered_effects_path,
    default_vapoursynth_runtime_dir,
    discover_local_vapoursynth_script_files,
    filter_introspection_by_namespaces,
    filter_validated_vapoursynth_effects,
    introspect_vapoursynth,
    load_vsrepo_packages,
    merge_introspection_with_packages,
    run_vsrepo_install,
    run_vsrepo_update,
    should_skip_vsrepo_package,
    vsrepo_install_key,
    write_promoted_effects,
)


RECOMMENDED_VSREPO_KEYS = {
    "com.holywu.cas",
    "com.nodame.asharp",
    "com.holywu.ctmf",
    "com.holywu.addgrain",
    "com.vapoursynth.removegrainvs",
    "com.vapoursynth.removegrainsf",
    "com.nodame.fluxsmooth",
    "com.vapoursynth.hqdn3d",
    "in.7086.neo_f3kdb",
    "tegaf.asi.xe",
    "fmtconv",
    "com.holywu.curve",
    "day.simultaneous.4",
    "com.holywu.tcanny",
    "com.holywu.edgemasks",
    "com.nodame.bifrost",
    "com.nodame.dedot",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Install, introspect, validate, and promote renderable external plugins.")
    parser.add_argument("--source", choices=["vsrepo", "local-vs-scripts"], default="vsrepo")
    parser.add_argument("--bucket", choices=["new2", "new3"], default="new2")
    parser.add_argument("--mode", choices=["recommended", "all-safe"], default="recommended")
    parser.add_argument("--package", action="append", default=[], help="VSRepo identifier/namespace/name to install. Can be repeated.")
    parser.add_argument("--install-limit", type=int, default=0, help="Limit install count after filtering. 0 means no limit.")
    parser.add_argument("--no-update", action="store_true", help="Skip vsrepo update.")
    parser.add_argument("--skip-install", action="store_true", help="Do not run vsrepo install; introspect and validate already installed packages.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; do not install or write promoted effects.")
    parser.add_argument("--output", type=Path, default=default_discovered_effects_path())
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "artifacts" / "plugin-promotion" / "promotion_report.json")
    args = parser.parse_args()

    runtime_dir = default_vapoursynth_runtime_dir()
    if not runtime_dir.exists():
        raise SystemExit(f"missing VapourSynth runtime: {runtime_dir}")

    if args.source == "local-vs-scripts":
        return promote_local_vapoursynth_scripts(args)

    if not args.no_update and not args.dry_run:
        update = run_vsrepo_update(runtime_dir)
        if update.returncode != 0:
            raise SystemExit((update.stderr or update.stdout or "vsrepo update failed")[-4000:])

    packages = load_vsrepo_packages(runtime_dir / "vspackages3.json")
    selected = select_vsrepo_packages(packages, mode=args.mode, requested=args.package)
    if args.install_limit > 0:
        selected = selected[: args.install_limit]

    report: dict[str, object] = {
        "selected_packages": [vsrepo_install_key(package) for package in selected],
        "installed": [],
        "skipped": [],
        "validated": [],
        "promoted": [],
    }
    for package in selected:
        skipped, reason = should_skip_vsrepo_package(package)
        key = vsrepo_install_key(package)
        if skipped:
            print(f"skip {key}: {reason}", flush=True)
            report["skipped"].append({"package": key, "reason": reason})  # type: ignore[index]
            continue
        if args.dry_run or args.skip_install:
            continue
        print(f"install {key}", flush=True)
        install = run_vsrepo_install(package, runtime_dir)
        print(f"  {'ok' if install.returncode == 0 else 'failed'}", flush=True)
        report["installed"].append(  # type: ignore[index]
            {
                "package": key,
                "ok": install.returncode == 0,
                "stdout": (install.stdout or "")[-2000:],
                "stderr": (install.stderr or "")[-2000:],
            }
        )

    promoted = []
    if not args.dry_run:
        print("introspect runtime", flush=True)
        introspection = introspect_vapoursynth(runtime_dir)
        merged = merge_introspection_with_packages(introspection, packages)
        promoted_namespaces = {
            str(package.get("namespace") or package.get("modulename") or "").lower()
            for package in selected
            if package.get("namespace") or package.get("modulename")
        }
        merged = filter_introspection_by_namespaces(merged, promoted_namespaces)
        existing = [effect for effect in EffectRegistry.load_default().list_effects() if effect.category != args.bucket]
        candidates = build_vapoursynth_effects_from_introspection(merged, existing_effects=existing, bucket=args.bucket)
        print("validate candidates", flush=True)
        valid, validations = filter_validated_vapoursynth_effects(candidates, runtime_dir)
        report["validated"] = validations
        report["promoted"] = [effect.id for effect in valid]
        promoted = valid
        write_promoted_effects(args.output, valid, replace_categories={args.bucket})

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"selected packages: {len(selected)}")
    print(f"promoted effects: {len(promoted)}")
    print(f"report: {args.report}")
    if not args.dry_run:
        print(f"registry: {args.output}")
    return 0


def promote_local_vapoursynth_scripts(args: argparse.Namespace) -> int:
    runtime_dir = default_vapoursynth_runtime_dir()
    existing = [effect for effect in EffectRegistry.load_default().list_effects() if effect.category != args.bucket]
    script_files = discover_local_vapoursynth_script_files()
    candidates = build_vapoursynth_script_effects_from_files(script_files, existing_effects=existing, bucket=args.bucket)
    report: dict[str, object] = {
        "source": "local-vs-scripts",
        "bucket": args.bucket,
        "script_files": [str(path) for path in script_files],
        "candidate_count": len(candidates),
        "validated": [],
        "promoted": [],
    }
    promoted = []
    if not args.dry_run:
        print(f"validate local script candidates: {len(candidates)}", flush=True)
        valid, validations = filter_validated_vapoursynth_effects(candidates, runtime_dir)
        report["validated"] = validations
        report["promoted"] = [effect.id for effect in valid]
        promoted = valid
        write_promoted_effects(args.output, valid, replace_categories={args.bucket})

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"candidate effects: {len(candidates)}")
    print(f"promoted effects: {len(promoted)}")
    print(f"report: {args.report}")
    if not args.dry_run:
        print(f"registry: {args.output}")
    return 0


def select_vsrepo_packages(
    packages: list[dict[str, object]],
    mode: str,
    requested: list[str],
) -> list[dict[str, object]]:
    requested_keys = {item.lower() for item in requested}
    result: list[dict[str, object]] = []
    for package in packages:
        keys = {
            str(package.get("identifier", "")).lower(),
            str(package.get("namespace", "")).lower(),
            str(package.get("modulename", "")).lower(),
            str(package.get("name", "")).lower(),
        }
        if requested_keys and not (keys & requested_keys):
            continue
        if not requested_keys and mode == "recommended" and not (keys & {item.lower() for item in RECOMMENDED_VSREPO_KEYS}):
            continue
        if not requested_keys and mode == "all-safe":
            skipped, _ = should_skip_vsrepo_package(package)  # type: ignore[arg-type]
            if skipped:
                continue
        result.append(package)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
