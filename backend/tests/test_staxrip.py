from pathlib import Path

from deepframe_api.staxrip import parse_filter_profiles, parse_package_vb, scan_staxrip


PACKAGE_FIXTURE = """
Shared Property Tool As Package = Add(New Package With {
    .Name = "Tool One",
    .Filename = "tool.exe",
    .Description = "Tool desc.",
    .WebURL = "https://example.com/tool",
    .DownloadURL = "https://example.com/tool/releases",
    .Location = IO.Path.Combine("Encoders", "Tool One")})

Shared Property DualPlugin As Package = Add(New PluginPackage With {
    .Name = "Dual Plugin",
    .Filename = "dual.dll",
    .Description = "Plugin desc.",
    .WebURL = "https://github.com/example/dual",
    .AvsFilterNames = {"DualAvs"},
    .VsFilterNames = {"dual.VS"}})

Shared Property AvsPlugin As Package = Add(New PluginPackage With {
    .Name = "AVS Plugin",
    .Filename = "avs.dll",
    .AvsFilterNames = {"AvsOnly"}})
"""


def test_parse_package_vb_extracts_urls_filters_and_locations():
    components = parse_package_vb(PACKAGE_FIXTURE)

    tool = components[0]
    dual = components[1]

    assert tool.name == "Tool One"
    assert tool.kind == "package"
    assert tool.declared_locations == ["Encoders/Tool One"]
    assert tool.download_url == "https://example.com/tool/releases"
    assert dual.kind == "plugin"
    assert dual.avs_filter_names == ["DualAvs"]
    assert dual.vs_filter_names == ["dual.VS"]


def test_scan_staxrip_resolves_package_and_plugin_paths(tmp_path: Path):
    source_file = tmp_path / "Package.vb"
    install_root = tmp_path / "StaxRip"
    source_file.write_text(PACKAGE_FIXTURE, encoding="utf-8")

    tool = install_root / "Apps" / "Encoders" / "Tool One" / "tool.exe"
    dual = install_root / "Apps" / "Plugins" / "Dual" / "Dual Plugin" / "dual.dll"
    avs = install_root / "Apps" / "Plugins" / "AVS" / "AVS Plugin" / "avs.dll"
    license_file = dual.parent / "LICENSE.txt"
    for path in (tool, dual, avs, license_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("MIT License" if path == license_file else "binary", encoding="utf-8")

    result = scan_staxrip(source_file, install_root)

    assert result.total == 3
    assert result.installed == 3
    assert result.plugins == 2
    assert any(component.license_status == "mit" for component in result.components)


def test_parse_filter_profiles_keeps_category_menu_path_and_multiline_script():
    profiles = parse_filter_profiles(
        """
[Noise]
BM3DCUDA | BM3DCUDA =
    clip = core.resize.Bicubic(clip, format=vs.YUV420PS)
    clip = core.bm3dcuda.BM3D(clip, sigma=3.0)
KNLMeansCL = clip = core.knlm.KNLMeansCL(clip)
""",
        "vapoursynth",
    )

    assert profiles[0].category == "Noise"
    assert profiles[0].menu_path == ["BM3DCUDA"]
    assert profiles[0].name == "BM3DCUDA"
    assert "core.bm3dcuda.BM3D" in profiles[0].script
    assert profiles[1].name == "KNLMeansCL"
