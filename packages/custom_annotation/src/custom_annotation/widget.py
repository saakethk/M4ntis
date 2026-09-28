"""AnyWidget-based inline annotator."""

from __future__ import annotations

import pathlib
from typing import Any, Sequence

import anywidget
import traitlets

from custom_annotation.model import AnnotationDocument

_STATIC = pathlib.Path(__file__).parent / "static" / "annotator.js"


class Annotator(anywidget.AnyWidget):
    """Interactive span labeler for plain text in Jupyter."""

    _esm = _STATIC

    text = traitlets.Unicode("").tag(sync=True)
    labels = traitlets.List(traitlets.Unicode()).tag(sync=True)
    active_label = traitlets.Unicode("LABEL").tag(sync=True)
    spans = traitlets.List(traitlets.Dict()).tag(sync=True)
    status = traitlets.Unicode("Select text, then click Add label.").tag(sync=True)

    def __init__(
        self,
        text: str,
        *,
        labels: Sequence[str] | None = None,
        document: AnnotationDocument | None = None,
        **kwargs: Any,
    ) -> None:
        if document is not None:
            self._document = document
        else:
            label_list = list(labels) if labels else ["LABEL"]
            self._document = AnnotationDocument(text=text, labels=label_list)
        super().__init__(
            text=self._document.text,
            labels=list(self._document.labels),
            active_label=self._document.labels[0],
            spans=[s.to_dict(text=self._document.text) for s in self._document.spans],
            **kwargs,
        )

    @property
    def document(self) -> AnnotationDocument:
        self._document.set_spans_from_dicts(self.spans)
        return self._document

    @traitlets.observe("spans")
    def _spans_changed(self, change: traitlets.Bunch) -> None:
        try:
            self._document.set_spans_from_dicts(change.new)
        except ValueError as exc:
            self.status = f"Invalid span: {exc}"

    def export_json(self, **kwargs: Any) -> str:
        return self.document.to_json(**kwargs)

    def export_csv(self) -> str:
        return self.document.to_csv()
