"""Tests for pipeline config: normalize, default, describe, stage_tool."""

from app.services.pipeline import (
    default_pipeline_config,
    describe_pipeline,
    normalize_pipeline_config,
    stage_tool,
)


def test_default_pipeline_config():
    """default_pipeline_config returns a dict with all stages."""
    cfg = default_pipeline_config()
    assert isinstance(cfg, dict)
    assert cfg["text"] == "pymupdf"
    assert cfg["structure"] == "docling"
    assert cfg["ocr"] == "tesseract"
    assert cfg["math"] == "none"
    assert cfg["figures"] == "pymupdf"
    assert cfg["figure_scoring"] == "heuristic"


def test_normalize_none_returns_default():
    """None input returns the default config."""
    assert normalize_pipeline_config(None) == default_pipeline_config()


def test_normalize_empty_dict_returns_default():
    """Empty dict returns the default config (fills missing stages)."""
    result = normalize_pipeline_config({})
    assert result == default_pipeline_config()


def test_normalize_preserves_valid_tool():
    """Valid stage→tool mappings are preserved."""
    cfg = {"text": "pymupdf", "structure": "none"}
    result = normalize_pipeline_config(cfg)
    assert result["text"] == "pymupdf"
    assert result["structure"] == "none"
    # Remaining stages filled with defaults
    assert result["ocr"] == "tesseract"


def test_normalize_ignores_unknown_tool():
    """Unknown tool id falls back to stage default."""
    cfg = {"ocr": "nonexistent_tool"}
    result = normalize_pipeline_config(cfg)
    assert result["ocr"] == "tesseract"  # default, not the unknown tool


def test_normalize_ignores_unknown_stage():
    """Unknown stage id is silently dropped."""
    cfg = {"bogus_stage": "something"}
    result = normalize_pipeline_config(cfg)
    assert "bogus_stage" not in result


def test_normalize_accepts_none_for_optional_stages():
    """Optional stages accept 'none' as a valid tool."""
    cfg = {"structure": "none", "ocr": "none", "math": "none"}
    result = normalize_pipeline_config(cfg)
    assert result["structure"] == "none"
    assert result["ocr"] == "none"
    assert result["math"] == "none"


def test_normalize_handles_non_dict():
    """Non-dict input (e.g. list, string) returns default."""
    assert normalize_pipeline_config(["not", "a", "dict"]) == default_pipeline_config()
    assert normalize_pipeline_config("string") == default_pipeline_config()


def test_describe_pipeline_returns_stages():
    """describe_pipeline returns a list of stage dicts with tools."""
    stages = describe_pipeline()
    assert len(stages) >= 4
    for stage in stages:
        assert "id" in stage
        assert "label" in stage
        assert "selected" in stage
        assert "tools" in stage
        for tool in stage["tools"]:
            assert "id" in tool
            assert "available" in tool


def test_describe_pipeline_with_custom_config():
    """describe_pipeline reflects a custom config selection."""
    cfg = {"ocr": "none", "math": "none"}
    stages = describe_pipeline(cfg)
    ocr = next(s for s in stages if s["id"] == "ocr")
    assert ocr["selected"] == "none"
    math = next(s for s in stages if s["id"] == "math")
    assert math["selected"] == "none"


def test_stage_tool_with_valid_config():
    """stage_tool returns the selected tool for a stage."""
    cfg = {"ocr": "rapidocr"}
    assert stage_tool(cfg, "ocr") == "rapidocr"
    assert stage_tool(cfg, "text") == "pymupdf"  # default


def test_stage_tool_unknown_stage():
    """stage_tool returns 'none' for unknown stage id."""
    assert stage_tool({}, "bogus") == "none"


def test_pipeline_config_idempotent():
    """normalize o normalize returns the same config."""
    cfg = normalize_pipeline_config({"math": "none"})
    assert normalize_pipeline_config(cfg) == cfg
