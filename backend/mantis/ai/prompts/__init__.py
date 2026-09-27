"""Prompt files for the AI features, loaded by name (e.g. ``load_prompt("post_summary.md")``)."""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text().strip()
