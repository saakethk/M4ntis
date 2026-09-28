"""Data model and export helpers for text spans."""

from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = "custom_annotation/v1"


@dataclass
class Span:
    """Character-offset span over document text (Python-style half-open [start, end))."""

    start: int
    end: int
    label: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    meta: dict[str, Any] = field(default_factory=dict)

    def validate_against(self, text: str) -> None:
        if self.start < 0 or self.end < 0:
            raise ValueError("span offsets must be non-negative")
        if self.start > self.end:
            raise ValueError("span start must be <= end")
        if self.end > len(text):
            raise ValueError("span end exceeds text length")
        if not self.label.strip():
            raise ValueError("span label must be non-empty")

    @property
    def text(self) -> str:
        return ""  # filled by document helpers

    def to_dict(self, *, text: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "label": self.label,
            "text": text[self.start : self.end],
            **({"meta": self.meta} if self.meta else {}),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Span:
        return cls(
            id=str(data.get("id", uuid.uuid4().hex[:12])),
            start=int(data["start"]),
            end=int(data["end"]),
            label=str(data["label"]),
            meta=dict(data.get("meta") or {}),
        )


@dataclass
class AnnotationDocument:
    text: str
    labels: list[str] = field(default_factory=lambda: ["LABEL"])
    spans: list[Span] = field(default_factory=list)
    schema: str = SCHEMA_VERSION
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.labels:
            self.labels = ["LABEL"]
        self.validate()

    def validate(self) -> None:
        for span in self.spans:
            span.validate_against(self.text)

    def add_span(self, start: int, end: int, label: str, *, meta: dict[str, Any] | None = None) -> Span:
        span = Span(start=start, end=end, label=label, meta=meta or {})
        span.validate_against(self.text)
        self.spans.append(span)
        return span

    def remove_span(self, span_id: str) -> None:
        self.spans = [s for s in self.spans if s.id != span_id]

    def set_spans_from_dicts(self, raw: Sequence[dict[str, Any]]) -> None:
        self.spans = [Span.from_dict(item) for item in raw]
        self.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "text": self.text,
            "labels": list(self.labels),
            "spans": [s.to_dict(text=self.text) for s in self.spans],
            **({"meta": self.meta} if self.meta else {}),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, payload: str | dict[str, Any]) -> AnnotationDocument:
        data = json.loads(payload) if isinstance(payload, str) else payload
        spans = [Span.from_dict(s) for s in data.get("spans", [])]
        doc = cls(
            text=str(data["text"]),
            labels=list(data.get("labels") or ["LABEL"]),
            spans=spans,
            schema=str(data.get("schema", SCHEMA_VERSION)),
            meta=dict(data.get("meta") or {}),
        )
        doc.validate()
        return doc

    def to_csv_rows(self) -> list[dict[str, str | int]]:
        rows: list[dict[str, str | int]] = []
        for span in self.spans:
            rows.append(
                {
                    "id": span.id,
                    "start": span.start,
                    "end": span.end,
                    "label": span.label,
                    "text": self.text[span.start : span.end],
                }
            )
        return rows

    def to_csv(self) -> str:
        buffer = io.StringIO()
        fieldnames = ["id", "start", "end", "label", "text"]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in self.to_csv_rows():
            writer.writerow(row)
        return buffer.getvalue()

    @classmethod
    def from_csv(cls, text: str, csv_payload: str, *, labels: Iterable[str] | None = None) -> AnnotationDocument:
        reader = csv.DictReader(io.StringIO(csv_payload))
        spans: list[Span] = []
        for row in reader:
            spans.append(
                Span(
                    id=row.get("id") or uuid.uuid4().hex[:12],
                    start=int(row["start"]),
                    end=int(row["end"]),
                    label=row["label"],
                )
            )
        doc = cls(text=text, labels=list(labels) if labels else ["LABEL"], spans=spans)
        doc.validate()
        return doc
