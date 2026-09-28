from __future__ import annotations

import json

import pytest

from custom_annotation.model import AnnotationDocument, Span


def test_span_validation() -> None:
    doc_text = "hello"
    span = Span(start=0, end=5, label="X")
    span.validate_against(doc_text)
    with pytest.raises(ValueError):
        Span(start=3, end=2, label="X").validate_against(doc_text)


def test_document_json_roundtrip() -> None:
    doc = AnnotationDocument(
        text="Acme hired Jane.",
        labels=["ORG", "PERSON"],
        spans=[Span(start=0, end=4, label="ORG"), Span(start=11, end=15, label="PERSON")],
    )
    restored = AnnotationDocument.from_json(doc.to_json())
    assert restored.text == doc.text
    assert len(restored.spans) == 2
    assert restored.spans[0].label == "ORG"


def test_csv_export() -> None:
    doc = AnnotationDocument(
        text="abc",
        spans=[Span(start=0, end=1, label="A")],
    )
    rows = doc.to_csv_rows()
    assert rows[0]["text"] == "a"
    roundtrip = AnnotationDocument.from_csv(doc.text, doc.to_csv(), labels=["A"])
    assert roundtrip.spans[0].start == 0


def test_schema_field() -> None:
    doc = AnnotationDocument(text="x")
    payload = json.loads(doc.to_json())
    assert payload["schema"] == "custom_annotation/v1"
