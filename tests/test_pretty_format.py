#!/usr/bin/env python3
"""Unit tests for tanat_utils.pretty_format."""

from tanat_utils.pretty_format import (
    format_header,
    format_section,
    format_kv,
    format_bullet,
    format_feature_section,
)

# ── format_header ─────────────────────────────────────────────────────────────


def test_format_header_box_structure():
    """Header must be exactly three lines with box-drawing borders (┌…┐ / │…│ / └…┘)."""
    result = format_header("My Title")
    lines = result.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("┌") and lines[0].endswith("┐")
    assert lines[1].startswith("│") and lines[1].endswith("│")
    assert lines[2].startswith("└") and lines[2].endswith("┘")


def test_format_header_contains_title():
    """The title string must appear verbatim inside the header box."""
    result = format_header("StateSequencePool Summary")
    assert "StateSequencePool Summary" in result


def test_format_header_title_centered():
    """The title must be horizontally centered between the │ borders (off-by-one tolerance)."""
    result = format_header("X")
    mid_line = result.split("\n")[1]
    inner = mid_line[1:-1]
    assert inner.strip() == "X"
    left_pad = len(inner) - len(inner.lstrip())
    right_pad = len(inner) - len(inner.rstrip())
    assert abs(left_pad - right_pad) <= 1


# ── format_section ────────────────────────────────────────────────────────────


def test_format_section_title_first_line():
    """The section title must be the very first line of the output."""
    result = format_section("Overview", ["line1", "line2"])
    lines = result.split("\n")
    assert lines[0] == "Overview"


def test_format_section_separator_second_line():
    """The second line must be a horizontal separator made solely of ─ characters."""
    result = format_section("Overview", ["line1"])
    lines = result.split("\n")
    assert set(lines[1]) <= {"─"}


def test_format_section_indented_lines():
    """Each body line must be indented by two spaces."""
    result = format_section("S", ["alpha", "beta"])
    assert "  alpha" in result
    assert "  beta" in result


def test_format_section_empty_lines():
    """An empty body must still render the title and separator without error."""
    result = format_section("Empty", [])
    assert "Empty" in result


# ── format_kv ─────────────────────────────────────────────────────────────────


def test_format_kv_contains_label_and_value():
    """Both the label and the value must appear in the output string."""
    result = format_kv("Sequences", "1,234")
    assert "Sequences" in result
    assert "1,234" in result


def test_format_kv_alignment():
    """Values must start at the same column regardless of label length."""
    result1 = format_kv("A", "1")
    result2 = format_kv("LongLabel", "2")
    idx1 = result1.index("1")
    idx2 = result2.index("2")
    assert idx1 == idx2


# ── format_bullet ─────────────────────────────────────────────────────────────


def test_format_bullet_starts_with_bullet():
    """Bullet lines must start with the • character."""
    result = format_bullet("heart_rate", "Numerical [45.0 → 180.0]")
    assert result.startswith("•")


def test_format_bullet_contains_label_and_detail():
    """Both the feature name and its detail string must appear in the output."""
    result = format_bullet("heart_rate", "Numerical [45.0 → 180.0]")
    assert "heart_rate" in result
    assert "Numerical [45.0 → 180.0]" in result


def test_format_bullet_alignment():
    """Detail strings must start at the same column regardless of label length."""
    result1 = format_bullet("hr", "Numerical")
    result2 = format_bullet("blood_pressure", "Numerical")
    idx1 = result1.index("Numerical")
    idx2 = result2.index("Numerical")
    assert idx1 == idx2


# ── format_feature_section ────────────────────────────────────────────────────


def test_format_feature_section_returns_none_when_empty():
    """An empty feature list must return None so callers can skip the section entirely."""
    assert format_feature_section("Entity Features", []) is None


def test_format_feature_section_title_includes_count():
    """The section title must include the total feature count in parentheses."""
    features = [("hr", "Numerical [45 → 180]"), ("bp", "Numerical [60 → 200]")]
    result = format_feature_section("Entity Features", features)
    assert result is not None
    assert "Entity Features (2)" in result


def test_format_feature_section_bullets_present():
    """Each feature must appear as a bullet line with its name and summary."""
    features = [("hr", "Numerical [45 → 180]")]
    result = format_feature_section("Entity Features", features)
    assert result is not None
    assert "• hr" in result
    assert "Numerical [45 → 180]" in result


def test_format_feature_section_no_truncation_when_below_limit():
    """All items must be shown when the list length is below max_items."""
    features = [(f"f{i}", f"summary{i}") for i in range(5)]
    result = format_feature_section("Features", features, max_items=10)
    assert result is not None
    assert "... and" not in result
    for name, _ in features:
        assert name in result


def test_format_feature_section_truncation():
    """Items beyond max_items must be hidden and a '... and N more' line appended."""
    features = [(f"f{i}", f"summary{i}") for i in range(15)]
    result = format_feature_section("Features", features, max_items=10)
    assert result is not None
    assert "... and 5 more" in result
    for i in range(10):
        assert f"f{i}" in result
    for i in range(10, 15):
        assert f"f{i}" not in result


def test_format_feature_section_exact_limit_no_truncation():
    """A list whose length equals max_items exactly must not trigger truncation."""
    features = [(f"f{i}", f"s{i}") for i in range(10)]
    result = format_feature_section("Features", features, max_items=10)
    assert result is not None
    assert "... and" not in result


def test_format_feature_section_one_over_limit():
    """A list with exactly one item over max_items must show '... and 1 more'."""
    features = [(f"f{i}", f"s{i}") for i in range(11)]
    result = format_feature_section("Features", features, max_items=10)
    assert result is not None
    assert "... and 1 more" in result
