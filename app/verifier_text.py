"""Deterministic text helpers (pure Python, no model)."""
from __future__ import annotations

import re

_ABV_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PROOF_RE = re.compile(r"(\d+(?:\.\d+)?)\s*proof", re.I)
_VOL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|fl\.?\s*oz|oz)\b", re.I)


def parse_abv(text: str) -> float | None:
    """ABV as a percentage, derived from proof if that is all there is."""
    m = _ABV_RE.search(text)
    if m:
        return float(m.group(1))
    m = _PROOF_RE.search(text)
    if m:
        return float(m.group(1)) / 2
    return None


def parse_volume_ml(text: str) -> float | None:
    m = _VOL_RE.search(text)
    if not m:
        return None
    val = float(m.group(1))
    unit = re.sub(r"[\s.]", "", m.group(2).lower())
    if unit == "ml":
        return val
    if unit == "l":
        return val * 1000
    if unit in ("floz", "oz"):
        return val * 29.5735
    return None


def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
