"""Notebook display helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_annotation.widget import Annotator


def display(annotator: Annotator, **kwargs: Any) -> None:
    """Show an :class:`Annotator` in the active Jupyter front-end."""
    from IPython.display import display as ipy_display

    ipy_display(annotator, **kwargs)
