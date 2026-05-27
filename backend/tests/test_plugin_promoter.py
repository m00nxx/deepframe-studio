from __future__ import annotations

from deepframe_api.effects import EffectDefinition
from deepframe_api.plugin_promoter import (
    AUTO_PARAMETER_VALUE,
    build_vapoursynth_script_effects_from_files,
    build_vapoursynth_effects_from_introspection,
    categorize_external_effect,
    filter_introspection_by_namespaces,
    select_avisynth_win64_asset,
    should_skip_vsrepo_package,
    write_promoted_effects,
)


def test_vsrepo_promoter_skips_heavy_ai_model_packages():
    skipped, reason = should_skip_vsrepo_package(
        {
            "identifier": "vs-mlrt",
            "namespace": "vsmlrt_models",
            "name": "VapourSynth ML Runtime",
            "description": "TensorRT CUDA ONNX model runtime",
            "type": "VSPlugin",
        }
    )

    assert skipped is True
    assert "model" in reason or "runtime" in reason


def test_vsrepo_promoter_skips_underscore_model_package_names():
    skipped, reason = should_skip_vsrepo_package(
        {
            "identifier": "io.github.amusementclub.vsmlrt_models",
            "namespace": "vsmlrt_models",
            "name": "vsmlrt_models",
            "description": "",
            "type": "PyScript",
        }
    )

    assert skipped is True
    assert "model" in reason


def test_vsrepo_promoter_skips_gpu_runtime_packages():
    skipped, reason = should_skip_vsrepo_package(
        {
            "identifier": "com.wolframrhodium.bm3dsycl.runtimes",
            "namespace": "bm3dsycl_runtimes",
            "name": "BM3D SYCL runtimes",
            "description": "",
            "type": "VSPlugin",
        }
    )

    assert skipped is True
    assert "runtime" in reason


def test_vsrepo_promoter_skips_packages_with_heavy_transitive_runtime():
    skipped, reason = should_skip_vsrepo_package(
        {
            "identifier": "com.wolframrhodium.bm3dcpu",
            "namespace": "bm3dcpu",
            "name": "BM3DCPU",
            "description": "",
            "type": "VSPlugin",
        }
    )

    assert skipped is True
    assert "transitive" in reason


def test_vsrepo_promoter_generates_renderable_vapoursynth_effect_from_signature():
    effects = build_vapoursynth_effects_from_introspection(
        [
            {
                "package_id": "cas",
                "package_name": "CAS",
                "namespace": "cas",
                "function": "CAS",
                "signature": "CAS(clip: VideoNode, sharpness: float = 0.5, planes: Union[int, Sequence[int], NoneType] = None) -> VideoNode",
                "package_category": "Sharpen/Soften Plugins",
                "source_url": "https://example.invalid/cas",
            }
        ],
        existing_effects=[],
    )

    assert len(effects) == 1
    effect = effects[0]
    assert effect.id == "external.vsrepo.new2.cas.cas"
    assert effect.category == "new2"
    assert effect.suggested_category == "sharpen"
    assert effect.engine == "vapoursynth"
    assert effect.install_status == "installed"
    assert effect.renderable is True
    assert effect.render_status == "renderable"
    assert effect.defaults == {"sharpness": 0.5, "planes": AUTO_PARAMETER_VALUE}
    assert "core.cas.CAS(clip, sharpness={sharpness}, planes={planes})" in effect.script_template


def test_vsrepo_promoter_can_target_new3_bucket():
    effects = build_vapoursynth_effects_from_introspection(
        [
            {
                "package_id": "cas",
                "package_name": "CAS",
                "namespace": "cas",
                "function": "CAS",
                "signature": "CAS(clip: VideoNode, sharpness: float = 0.5) -> VideoNode",
                "package_category": "Sharpen/Soften Plugins",
            }
        ],
        existing_effects=[],
        bucket="new3",
    )

    assert effects[0].id == "external.vsrepo.new3.cas.cas"
    assert effects[0].category == "new3"
    assert effects[0].menu_path[0] == "new3"


def test_vsrepo_promoter_enriches_optional_none_parameters_as_auto_controls():
    effects = build_vapoursynth_effects_from_introspection(
        [
            {
                "package_id": "cas",
                "package_name": "CAS",
                "namespace": "cas",
                "function": "CAS",
                "signature": "CAS(clip: VideoNode, sharpness: Optional[float] = None, planes: Union[int, Sequence[int], NoneType] = None, opt: Optional[int] = None) -> VideoNode",
                "package_category": "Sharpen/Soften Plugins",
            }
        ],
        existing_effects=[],
    )

    effect = effects[0]
    assert {parameter.name for parameter in effect.parameters} == {"sharpness", "planes", "opt"}
    assert effect.defaults == {
        "sharpness": AUTO_PARAMETER_VALUE,
        "planes": AUTO_PARAMETER_VALUE,
        "opt": AUTO_PARAMETER_VALUE,
    }
    assert all(parameter.auto for parameter in effect.parameters)
    assert all(parameter.auto_value == AUTO_PARAMETER_VALUE for parameter in effect.parameters)
    assert "sharpness={sharpness}" in effect.script_template


def test_vsrepo_promoter_skips_functions_that_need_extra_required_clips():
    effects = build_vapoursynth_effects_from_introspection(
        [
            {
                "package_id": "masked",
                "package_name": "Masked",
                "namespace": "masked",
                "function": "Merge",
                "signature": "Merge(clipa: VideoNode, clipb: VideoNode, weight: float = 0.5) -> VideoNode",
                "package_category": "Misc",
            }
        ],
        existing_effects=[],
    )

    assert effects == []


def test_vsrepo_promoter_deduplicates_against_existing_callable_effects():
    existing = [
        EffectDefinition(
            id="staxrip.vapoursynth.line.sharpen.awarpsharpen2",
            name="AWarpSharpen2",
            engine="vapoursynth",
            category="sharpen",
            install_status="installed",
            install_policy="bundled",
            script_template="clip = core.warp.AWarpSharp2(clip=clip, blur={blur})",
        )
    ]

    effects = build_vapoursynth_effects_from_introspection(
        [
            {
                "package_id": "warp",
                "package_name": "AWarpSharp2",
                "namespace": "warp",
                "function": "AWarpSharp2",
                "signature": "AWarpSharp2(clip: VideoNode, thresh: Optional[int] = None, blur: Optional[int] = None) -> VideoNode",
                "package_category": "Sharpen/Soften Plugins",
            }
        ],
        existing_effects=existing,
    )

    assert effects == []


def test_vsrepo_promoter_keeps_multiple_functions_from_same_plugin():
    effects = build_vapoursynth_effects_from_introspection(
        [
            {
                "package_id": "edgemasks",
                "package_name": "EdgeMasks",
                "namespace": "edgemasks",
                "function": "Cross",
                "signature": "Cross(clip: VideoNode) -> VideoNode",
                "package_category": "Other",
            },
            {
                "package_id": "edgemasks",
                "package_name": "EdgeMasks",
                "namespace": "edgemasks",
                "function": "Sobel",
                "signature": "Sobel(clip: VideoNode) -> VideoNode",
                "package_category": "Other",
            },
        ],
        existing_effects=[],
    )

    assert [effect.id for effect in effects] == [
        "external.vsrepo.new2.edgemasks.cross",
        "external.vsrepo.new2.edgemasks.sobel",
    ]


def test_write_promoted_effects_replaces_only_requested_bucket(tmp_path):
    path = tmp_path / "discovered.yaml"
    existing_new2 = EffectDefinition(
        id="external.vsrepo.new2.keep.keep",
        name="Keep",
        engine="vapoursynth",
        category="new2",
        install_status="installed",
        install_policy="bundled",
        script_template="clip = core.std.BlankClip()",
    )
    old_new3 = EffectDefinition(
        id="external.vsrepo.new3.old.old",
        name="Old",
        engine="vapoursynth",
        category="new3",
        install_status="installed",
        install_policy="bundled",
        script_template="clip = core.std.BlankClip()",
    )
    new_new3 = EffectDefinition(
        id="external.local-vs-script.new3.fine.fine",
        name="Fine",
        engine="vapoursynth",
        category="new3",
        install_status="installed",
        install_policy="bundled",
        script_template="clip = fine.Fine(clip)",
    )
    write_promoted_effects(path, [existing_new2, old_new3])

    write_promoted_effects(path, [new_new3], replace_categories={"new3"})

    text = path.read_text(encoding="utf-8")
    assert "external.vsrepo.new2.keep.keep" in text
    assert "external.local-vs-script.new3.fine.fine" in text
    assert "external.vsrepo.new3.old.old" not in text


def test_local_vapoursynth_script_promoter_builds_new3_with_parameters(tmp_path):
    script = tmp_path / "fine.py"
    script.write_text(
        """
def Fine(clip, strength=1.25, planes=None, mode='soft'):
    return clip

def NeedsMask(clip, mask):
    return clip
""".strip()
        + "\n",
        encoding="utf-8",
    )

    effects = build_vapoursynth_script_effects_from_files([script], existing_effects=[], bucket="new3")

    assert [effect.name for effect in effects] == ["Fine"]
    effect = effects[0]
    assert effect.id == "external.local-vs-script.new3.fine.fine"
    assert effect.category == "new3"
    assert effect.script_imports == ["import fine"]
    assert effect.defaults == {
        "strength": 1.25,
        "planes": AUTO_PARAMETER_VALUE,
        "mode": "soft",
    }
    assert "clip = fine.Fine(clip, strength={strength}, planes={planes}, mode='{mode}')" in effect.script_template


def test_local_vapoursynth_script_promoter_allows_required_geometry_parameters(tmp_path):
    script = tmp_path / "resizepack.py"
    script.write_text(
        """
def ResizeIt(clip, width, height, kernel='spline36'):
    return clip

def NeedsReference(clip, ref):
    return clip
""".strip()
        + "\n",
        encoding="utf-8",
    )

    effects = build_vapoursynth_script_effects_from_files([script], existing_effects=[], bucket="new3")

    assert [effect.name for effect in effects] == ["ResizeIt"]
    assert effects[0].defaults == {"width": 128, "height": 72, "kernel": "spline36"}
    assert "width={width}, height={height}" in effects[0].script_template


def test_avisynth_promoter_selects_verified_win64_asset():
    asset = select_avisynth_win64_asset(
        {
            "name": "EEDI3",
            "releases": [
                {
                    "version": "0.9",
                    "win64": {
                        "url": "https://example.invalid/EEDI3.7z",
                        "files": {"x64/eedi3.dll": "a" * 64},
                    },
                }
            ],
        }
    )

    assert asset["url"].endswith("EEDI3.7z")
    assert asset["files"] == {"x64/eedi3.dll": "a" * 64}


def test_external_category_mapping_keeps_raw_new_bucket_separate():
    assert categorize_external_effect("Sharpen/Soften Plugins", ["plugin"]) == "sharpen"
    assert categorize_external_effect("Denoising", []) == "denoise"
    assert categorize_external_effect("Other", ["Constant Time Median Filtering"]) == "denoise"
    assert categorize_external_effect("Dot Crawl and Rainbows", ["Bifrost"]) == "repair"
    assert categorize_external_effect("Unknown Experimental", []) == "custom"


def test_introspection_filter_keeps_only_selected_external_namespaces():
    items = [
        {"namespace": "std", "function": "BoxBlur"},
        {"namespace": "resize", "function": "Bicubic"},
        {"namespace": "cas", "function": "CAS"},
        {"namespace": "ctmf", "function": "CTMF"},
    ]

    filtered = filter_introspection_by_namespaces(items, {"cas", "ctmf"})

    assert [item["namespace"] for item in filtered] == ["cas", "ctmf"]
