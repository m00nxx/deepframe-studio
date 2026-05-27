from deepframe_api.models import DeepFrameProject


def test_project_model_normalizes_segments_and_effect_chain_defaults():
    project = DeepFrameProject(
        media_path="/media/source.mp4",
        in_point=0,
        out_point=10,
        segments=[{"start": 1, "end": 2, "label": "keep"}],
        selected_preset="h264",
        output_settings={"container": "mp4", "video_codec": "copy"},
        app_version="0.1.0",
    )

    assert project.metadata_cache == {}
    assert project.effect_chain == []
    assert project.segments[0].start == 1


def test_project_model_rejects_out_point_before_in_point():
    try:
        DeepFrameProject(media_path="/media/source.mp4", in_point=5, out_point=4)
    except ValueError as exc:
        assert "out_point" in str(exc)
    else:
        raise AssertionError("expected validation error")
