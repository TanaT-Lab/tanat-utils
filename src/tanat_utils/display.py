#!/usr/bin/env python3
"""
Display mixin providing box-drawing progress output for long-running operations.
"""

import time
from contextlib import contextmanager
from typing import Generator

from tqdm import tqdm


class DisplayIndentManager:
    """Class-level indentation state for nested component display.

    Allows nested components to automatically use the correct indentation
    level when :class:`DisplayMixin` methods are called.
    """

    _indent_level: int = 0
    _indent_prefix: str = "│   "

    @classmethod
    def get_indent(cls) -> str:
        """Return the current indentation string."""
        return cls._indent_prefix * cls._indent_level

    @classmethod
    def increase(cls) -> None:
        """Increase indentation by one level."""
        cls._indent_level += 1

    @classmethod
    def decrease(cls) -> None:
        """Decrease indentation by one level (floor: 0)."""
        cls._indent_level = max(0, cls._indent_level - 1)

    @classmethod
    @contextmanager
    def nested(cls) -> Generator[None, None, None]:
        """Context manager that increases indentation for the duration of the block."""
        cls.increase()
        try:
            yield
        finally:
            cls.decrease()


class DisplayMixin:
    """Mixin that adds box-drawing build progress output to a class.

    Intended for builder classes that run multi-step pipelines.
    Progress is written via :func:`tqdm.write` so it interleaves cleanly
    with any :class:`tqdm` progress bars active in the same terminal.

    Display style::

        ┌─ ComponentName
        │
        │ Step 1/4: Sorting & preparing data
        │
        │ Step 2/4: Building sequence index
        │
        │ Step 3/4: Writing entity & temporal features
        │
        │ Step 4/4: Computing & writing metadata
        │
        └─ Done (1,234 sequences · 56,789 entities · 2.34s)

    """

    def _get_indent(self) -> str:
        """Return the current indentation string (for nested display)."""
        return DisplayIndentManager.get_indent()

    def _display_header(self, title: str | None = None) -> None:
        """Print the opening line and start the internal timer.

        Args:
            title: Header text.  Defaults to the class name.
        """
        self._start_time: float = time.perf_counter()
        label = title or self.__class__.__name__
        indent = self._get_indent()
        tqdm.write(f"{indent}┌─ {label}")

    def _display_step(
        self, step: int, total: int, description: str, *, is_main: bool = True
    ) -> None:
        """Print a step marker preceded by a blank │ line.

        Args:
            step:        1-indexed step number.
            total:       Total number of steps.
            description: Short description of the step.
            is_main:     If ``True`` (default) use the primary ``Step N/M`` format;
                         ``False`` uses a compact sub-step format.
        """
        self._display_blank_line()
        indent = self._get_indent()
        if is_main:
            tqdm.write(f"{indent}│ Step {step}/{total}: {description}")
        else:
            tqdm.write(f"{indent}│   ({step}/{total}) {description}")

    def _display_message(self, message: str) -> None:
        """Print an informational line inside the current box.

        Args:
            message: The message text.
        """
        indent = self._get_indent()
        tqdm.write(f"{indent}│ {message}")

    def _display_blank_line(self) -> None:
        """Print an empty │ line (visual spacing)."""
        indent = self._get_indent()
        tqdm.write(f"{indent}│")

    def _create_progress_bar(self, total: int, desc: str = "Progress") -> tqdm:
        """Create a :class:`tqdm` progress bar with correct box indentation.

        Emits a blank │ line before the bar so it visually sits inside
        the enclosing box.

        Args:
            total: Total number of items.
            desc:  Bar label.

        Returns:
            A configured :class:`tqdm` instance ready to use as a context
            manager or iterate directly.
        """
        self._display_blank_line()
        indent = self._get_indent()
        return tqdm(total=total, desc=f"{indent}│ {desc}")

    def _display_footer(self, summary: str | None = None) -> None:
        """Print the closing line with elapsed time and an optional summary.

        Args:
            summary: Free-form summary text prepended to the elapsed time.
                     Pass ``None`` to show elapsed time only.
        """
        elapsed = time.perf_counter() - getattr(self, "_start_time", 0.0)
        elapsed_str = f"{elapsed:.2f}s"
        summary_str = f"{summary} · {elapsed_str}" if summary else elapsed_str
        indent = self._get_indent()
        tqdm.write(f"{indent}│")
        tqdm.write(f"{indent}└─ Done ({summary_str})")

    @contextmanager
    def _nested_display(self) -> Generator[None, None, None]:
        """Context manager that indents all display output within the block.

        Use when calling a sub-component that also uses :class:`DisplayMixin`
        so its output appears nested inside the current box.
        """
        indent = self._get_indent()
        tqdm.write(f"{indent}│")
        with DisplayIndentManager.nested():
            yield
