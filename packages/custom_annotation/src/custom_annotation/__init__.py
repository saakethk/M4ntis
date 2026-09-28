"""Jupyter inline text annotation."""

from custom_annotation.display import display
from custom_annotation.model import AnnotationDocument, Span
from custom_annotation.widget import Annotator

__all__ = [
    "Annotator",
    "AnnotationDocument",
    "Span",
    "display",
]

__version__ = "0.1.0"
