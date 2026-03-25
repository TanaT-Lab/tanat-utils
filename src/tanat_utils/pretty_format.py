#!/usr/bin/env python3
"""
Pretty-formatting primitives for rich text representation of TanaT objects.

Provides box-drawing headers, titled sections, key-value lines, and
bullet lines.  No external dependencies.
"""

# ── Formatting constants ───────────────────────────────────────────────────────
_SECTION_WIDTH: int = 50  # total width of the top/bottom border lines
_KEY_WIDTH: int = 19  # left column width for key-value alignment
_LABEL_WIDTH: int = 20  # left column width for bullet alignment
_BULLET: str = "•"


def format_header(title: str) -> str:
    """Box-drawing header.

    Example::

        ┌──────────────────────────────────────────────────┐
        │            StateSequencePool Summary             │
        └──────────────────────────────────────────────────┘
    """
    inner = _SECTION_WIDTH - 2  # space between │ borders
    padded = f" {title} ".center(inner)
    top = "┌" + "─" * inner + "┐"
    mid = "│" + padded + "│"
    bot = "└" + "─" * inner + "┘"
    return f"{top}\n{mid}\n{bot}"


def format_section(title: str, lines: list[str]) -> str:
    """Titled section with a horizontal separator and indented lines.

    Example::

        Overview
        ─────────────────────────
          Sequences          1,234
          Store              ./my_store
    """
    sep = "─" * 25
    body = "\n".join(f"  {line}" for line in lines)
    return f"{title}\n{sep}\n{body}"


def format_kv(label: str, value: object) -> str:
    """Aligned key-value line.

    Example::

        Sequences          1,234
    """
    return f"{label:<{_KEY_WIDTH}}{value}"


def format_bullet(label: str, detail: str) -> str:
    """Bullet line with aligned label and detail.

    Example::

        • heart_rate        Numerical [45.0 → 180.0]
    """
    return f"{_BULLET} {label:<{_LABEL_WIDTH}}{detail}"


def format_feature_section(
    title: str,
    features: list[tuple[str, str]],
    max_items: int = 10,
) -> str | None:
    """Feature section with bullet list and truncation.

    Returns ``None`` if *features* is empty (caller skips the section).

    Args:
        title: Section title (count is appended automatically).
        features: List of (name, summary) tuples.
        max_items: Truncate after this many items.
    """
    if not features:
        return None
    bullets = [format_bullet(name, summary) for name, summary in features[:max_items]]
    if len(features) > max_items:
        bullets.append(f"... and {len(features) - max_items} more")
    return format_section(f"{title} ({len(features)})", bullets)
