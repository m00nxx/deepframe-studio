from pathlib import Path

import pytest

from deepframe_api.effects import AUTO_PARAMETER_VALUE, EffectDefinition, EffectRegistry, _filter_renderable_new_effects, _render_effect_template

EXPECTED_CATEGORIES = {
    "denoise",
    "deinterlace",
    "sharpen",
    "blur",
    "resize",
    "upscale",
    "repair",
    "stabilize",
    "color",
    "deband",
    "degrain",
    "artifact removal",
    "face restore",
    "frame interpolation",
    "encode",
    "custom",
}


def test_registry_loads_sample_effects():
    registry = EffectRegistry.load_default()

    effects = registry.list_effects()

    assert len(effects) >= 3
    assert {effect.id for effect in effects} >= {"vs.knlmeanscl", "vs.resize.bicubic"}


def test_registry_covers_supported_categories_and_recommendations_are_bounded():
    registry = EffectRegistry.load_default()
    effects = registry.list_effects()

    categories = {effect.category for effect in effects}
    recommended_counts = {
        category: sum(1 for effect in effects if effect.category == category and effect.recommended)
        for category in EXPECTED_CATEGORIES
    }

    assert EXPECTED_CATEGORIES <= categories
    assert all(count <= 3 for count in recommended_counts.values())
    assert recommended_counts["denoise"] >= 1


def test_registry_exposes_install_and_legal_metadata_to_frontend():
    registry = EffectRegistry.load_default()

    model = registry.get("vs.knlmeanscl").frontend_model()

    assert model["source_url"]
    assert model["license_status"] in {"redistributable", "manual_review", "unclear", "built_in", "mit", "gpl", "lgpl", "mixed"}
    assert model["install_policy"] in {"manual", "builtin", "metadata_only", "allowed_download", "bundled"}
    assert model["install_allowed"] is False
    assert "KNLMeansCL" in model["required_plugins"]
    assert model["renderable"] is True
    assert model["render_status"] == "renderable"


def test_registry_marks_scaffolds_as_not_renderable_to_frontend():
    registry = EffectRegistry.load_default()

    model = registry.get("ai.realesrgan").frontend_model()

    assert model["renderable"] is False
    assert model["render_status"] == "not_renderable"


def test_discovered_metadata_only_effects_are_not_exposed_as_usable_new_effects():
    registry = EffectRegistry.load_default()
    effect_ids = {effect.id for effect in registry.list_effects()}

    assert "external.avisynthwiki.avisynth.sharpen-soften-plugins.awarpsharp" not in effect_ids
    assert "external.vsrepo.vapoursynth.warp" not in effect_ids
    assert all(
        effect.renderable and effect.install_status == "installed"
        for effect in registry.list_effects()
        if effect.category in {"new", "new2", "new3"}
    )


def test_discovered_renderable_new_effects_keep_multiple_functions_from_same_plugin():
    discovered = [
        EffectDefinition(
            id="external.vsrepo.new2.edgemasks.cross",
            name="Cross",
            engine="vapoursynth",
            category="new2",
            required_plugins=["edgemasks"],
            install_status="installed",
            install_policy="bundled",
            script_template="clip = core.edgemasks.Cross(clip)",
        ),
        EffectDefinition(
            id="external.vsrepo.new2.edgemasks.sobel",
            name="Sobel",
            engine="vapoursynth",
            category="new2",
            required_plugins=["edgemasks"],
            install_status="installed",
            install_policy="bundled",
            script_template="clip = core.edgemasks.Sobel(clip)",
        ),
    ]

    filtered = _filter_renderable_new_effects(discovered, existing_effects=[])

    assert [effect.id for effect in filtered] == [effect.id for effect in discovered]


def test_discovered_renderable_new_effects_skip_existing_same_call():
    existing = [
        EffectDefinition(
            id="existing",
            name="Existing",
            engine="vapoursynth",
            category="sharpen",
            install_status="installed",
            install_policy="bundled",
            script_template="clip = core.edgemasks.Cross(clip)",
        )
    ]
    discovered = [
        EffectDefinition(
            id="external.vsrepo.new2.edgemasks.cross",
            name="Cross",
            engine="vapoursynth",
            category="new2",
            required_plugins=["edgemasks"],
            install_status="installed",
            install_policy="bundled",
            script_template="clip = core.edgemasks.Cross(clip)",
        )
    ]

    assert _filter_renderable_new_effects(discovered, existing_effects=existing) == []


def test_render_effect_template_omits_auto_parameters_from_generated_calls():
    script = _render_effect_template(
        "clip = core.cas.CAS(clip, sharpness={sharpness}, planes={planes}, opt={opt})",
        {"sharpness": AUTO_PARAMETER_VALUE, "planes": 0, "opt": AUTO_PARAMETER_VALUE},
    )

    assert script == "clip = core.cas.CAS(clip, planes=0)"


def test_render_effect_template_omits_quoted_auto_parameters():
    script = _render_effect_template(
        "clip = core.example.Filter(clip, mode='{mode}', amount={amount})",
        {"mode": AUTO_PARAMETER_VALUE, "amount": 2},
    )

    assert script == "clip = core.example.Filter(clip, amount=2)"


def test_staxrip_awarpsharp2_profiles_are_the_renderable_awarpsharp_entries():
    registry = EffectRegistry.load_default()
    vs_effect = registry.get("staxrip.vapoursynth.line.sharpen.awarpsharpen2")
    avs_effect = registry.get("staxrip.avisynth.line.sharpen.awarpsharp2")

    assert vs_effect.renderable is True
    assert avs_effect.renderable is True
    assert {parameter.name for parameter in vs_effect.parameters} == {"blur"}
    assert {"thresh", "blur", "type", "depth", "chroma"} <= {parameter.name for parameter in avs_effect.parameters}

    scripts = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "staxrip.vapoursynth.line.sharpen.awarpsharpen2",
                "enabled": True,
                "parameters": {"blur": 3},
            }
        ],
    )

    assert "core.warp.AWarpSharp2(clip=clip, blur=3)" in scripts.vapoursynth


def test_sample_registry_does_not_enable_unreviewed_installers():
    registry = EffectRegistry.load_default()

    for effect in registry.list_effects():
        assert effect.install_allowed is False
        assert effect.install_policy in {"manual", "builtin", "metadata_only", "allowed_download", "bundled"}
        if effect.install_policy != "allowed_download":
            assert not effect.download_url


def test_registry_marks_staxrip_bundled_effects_installed_when_manifest_exists():
    manifest = Path(__file__).parents[2] / "vendor" / "staxrip" / "manifest.json"
    if not manifest.exists():
        pytest.skip("local StaxRip bundle manifest is not present")

    registry = EffectRegistry.load_default()

    assert registry.get("vs.knlmeanscl").install_status == "installed"
    assert registry.get("vs.knlmeanscl").install_policy == "bundled"
    assert registry.get("vs.cas").install_status == "installed"


def test_registry_includes_custom_vapoursynth_and_avisynth_entries():
    registry = EffectRegistry.load_default()

    assert registry.get("custom.vpy").engine == "vapoursynth"
    assert registry.get("custom.avs").engine == "avisynth"


def test_registry_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "effects.yaml"
    path.write_text(
        """
effects:
  - id: duplicate
    name: One
    category: denoise
  - id: duplicate
    name: Two
    category: denoise
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate effect id"):
        EffectRegistry.load_from_file(path)


def test_registry_generates_vapoursynth_script_scaffold():
    registry = EffectRegistry.load_default()

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "vs.knlmeanscl",
                "enabled": True,
                "parameters": {"strength": 0.25},
            }
        ],
    )

    assert "import vapoursynth as vs" in script.vapoursynth
    assert "core.lsmas.LWLibavSource" in script.vapoursynth
    assert "KNLMeansCL" in script.vapoursynth


def test_registry_autoloads_bundled_vapoursynth_plugins_before_source_filter():
    registry = EffectRegistry.load_default()

    script = registry.build_chain_scripts(media_path="/mnt/c/media/source.mp4", effect_chain=[])

    assert "core.std.LoadPlugin" in script.vapoursynth
    assert "LSMASHSource.dll" in script.vapoursynth
    assert script.vapoursynth.index("core.std.LoadPlugin") < script.vapoursynth.index("core.lsmas.LWLibavSource")


def test_registry_script_generation_uses_defaults_for_missing_parameters():
    registry = EffectRegistry.load_default()

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "vs.knlmeanscl",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert "s=1.2" in script.vapoursynth


def test_registry_script_generation_adds_required_vapoursynth_imports():
    registry = EffectRegistry.load_default()

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "vs.qtgmc",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert "import havsfunc" in script.vapoursynth
    assert "havsfunc.QTGMC" in script.vapoursynth


def test_staxrip_avisynth_effect_is_not_inserted_into_vapoursynth_script():
    registry = EffectRegistry.load_default()

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "staxrip.avisynth.line.sharpen.lsfmod",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert 'LSFmod(defaults="slow"' not in script.vapoursynth
    assert "skipped for vapoursynth" in script.vapoursynth
    assert 'clip = clip.LSFmod(defaults="slow"' in script.avisynth
    assert "%target_width%" not in script.avisynth


def test_staxrip_vapoursynth_script_imports_bundled_python_modules():
    registry = EffectRegistry.load_default()
    effect = registry.get("staxrip.vapoursynth.line.sharpen.lsfmod")

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "staxrip.vapoursynth.line.sharpen.lsfmod",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert "sys.path.append" in script.vapoursynth
    assert "import havsfunc" in script.vapoursynth
    assert "import mvsfunc" in script.vapoursynth
    assert "import adjust" in script.vapoursynth
    assert "clip = havsfunc.LSFmod(clip" in script.vapoursynth
    assert "clip" not in {parameter.name for parameter in effect.parameters}
    assert effect.script_template.startswith("clip = havsfunc.LSFmod(clip, defaults=")


def test_staxrip_profile_parameters_are_editable_and_rendered_into_script():
    registry = EffectRegistry.load_default()
    effect = registry.get("staxrip.avisynth.line.sharpen.psharpen")

    assert {parameter.name for parameter in effect.parameters} >= {"strength", "threshold", "ss_x", "ss_y"}
    assert effect.defaults["strength"] == 25
    assert "{strength}" in effect.script_template

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "staxrip.avisynth.line.sharpen.psharpen",
                "enabled": True,
                "parameters": {"strength": 40},
            }
        ],
    )

    assert "clip = clip.pSharpen(strength=40, threshold=75" in script.avisynth


def test_staxrip_positional_profile_parameter_is_editable():
    registry = EffectRegistry.load_default()
    effect = registry.get("staxrip.avisynth.line.sharpen.multisharpen")

    assert effect.parameters[0].name == "value"
    assert effect.defaults["value"] == 1
    assert effect.script_template == "MultiSharpen({value})"


def test_staxrip_interactive_macros_are_resolved_before_script_generation():
    registry = EffectRegistry.load_default()
    effect = registry.get("staxrip.avisynth.line.anti-aliasing.santiag")

    assert "$" not in effect.script_template
    assert {"strh", "strv", "type"} <= {parameter.name for parameter in effect.parameters}
    assert effect.defaults["strh"] == 1
    assert effect.defaults["strv"] == 1
    assert effect.defaults["type"] == "nnedi3"

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "staxrip.avisynth.line.anti-aliasing.santiag",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert "$" not in script.avisynth
    assert 'clip = clip.santiag(strh=1, strv=1, type="nnedi3"' in script.avisynth


def test_qtgmc_profiles_use_valid_default_presets_and_import_order():
    registry = EffectRegistry.load_default()
    avs_qtgmc = registry.get("staxrip.avisynth.field.deinterlace.qtgmc.qtgmc")
    vs_qtgmc = registry.get("staxrip.vapoursynth.field.deinterlace.qtgmc.qtgmc")

    assert avs_qtgmc.defaults["preset"] == "Slower"
    assert vs_qtgmc.defaults["Preset"] == "Slower"
    assert vs_qtgmc.defaults["SourceMatch"] == 0
    assert "EdiMode" in vs_qtgmc.script_template

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "vs.qtgmc",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert "sys.path.append" in script.vapoursynth
    assert "import havsfunc" in script.vapoursynth
    assert script.vapoursynth.index("sys.path.append") < script.vapoursynth.index("import havsfunc")
    assert "TFF=True" in script.vapoursynth
    assert "EdiMode='EEDI3'" in script.vapoursynth


def test_all_staxrip_profile_templates_are_free_of_interactive_macros():
    registry = EffectRegistry.load_default()

    remaining = [
        effect.id
        for effect in registry.list_effects()
        if effect.origin == "staxrip" and ("$" in effect.script_template or any("$" in str(value) for value in effect.defaults.values()))
    ]

    assert remaining == []


def test_staxrip_templates_with_literal_braces_do_not_break_parameter_rendering():
    registry = EffectRegistry.load_default()

    vs_script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "staxrip.vapoursynth.frame-rate.svpflow.core",
                "enabled": True,
                "parameters": {},
            }
        ],
    ).vapoursynth

    assert "{pel:1,scale:{up:0},gpu:1,full:false,rc:true}" in vs_script
    assert "src=clip" in vs_script


def test_context_only_staxrip_profiles_are_noop_in_effect_chain():
    registry = EffectRegistry.load_default()

    scripts = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "staxrip.vapoursynth.source.lwlibavsource",
                "enabled": True,
                "parameters": {},
            },
            {
                "id": "chain-2",
                "effect_id": "staxrip.vapoursynth.resize.advanced.resamplehq",
                "enabled": True,
                "parameters": {},
            },
        ],
    )

    assert "%source_file%" not in scripts.vapoursynth
    assert "%target_width%" not in scripts.vapoursynth
    assert "not safe as an effect-chain filter" in scripts.vapoursynth


def test_vapoursynth_santiag_defaults_to_cpu_safe_mode():
    registry = EffectRegistry.load_default()

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "staxrip.vapoursynth.line.anti-aliasing.santiag",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert "opencl=False" in script.vapoursynth


def test_sample_bm3d_converts_subsampled_preview_input():
    registry = EffectRegistry.load_default()

    script = registry.build_chain_scripts(
        media_path="/media/source.mp4",
        effect_chain=[
            {
                "id": "chain-1",
                "effect_id": "vs.bm3d",
                "enabled": True,
                "parameters": {},
            }
        ],
    )

    assert "format=vs.YUV444PS" in script.vapoursynth
    assert "core.bm3d.Basic" in script.vapoursynth
    assert "format=vs.YUV420P8" in script.vapoursynth


def test_registry_escapes_avisynth_source_paths():
    registry = EffectRegistry.load_default()

    script = registry.build_chain_scripts(
        media_path='C:\\Video "quoted"\\clip.avs',
        effect_chain=[],
    )

    assert 'C:\\\\Video \\"quoted\\"\\\\clip.avs' in script.avisynth
    assert "LoadPlugin" in script.avisynth
    assert "LSMASHSource.dll" in script.avisynth
