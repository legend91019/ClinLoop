from __future__ import annotations
import re


def normalize_clinical_event(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
