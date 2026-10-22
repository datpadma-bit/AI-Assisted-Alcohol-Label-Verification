"""Python-generated wrong answers.

Clef-omni is a comparison model: asked "is 'OLD TOM DISTILLERY' printed?" alone it answers ~0.05
even on a perfect label, but asked to pick between the expected value and plausible wrong ones it
picks the right one at ~0.9 and the wrong label's value at ~0.04. So for every application field
Python builds a multiple-choice question: the user's value, two decoys, and "none of these".
"""
from __future__ import annotations

import re

from .verifier_text import parse_abv, parse_volume_ml

_CLASS_POOL = [
    "Kentucky Straight Bourbon Whiskey", "Tennessee Whiskey", "Straight Rye Whiskey",
    "Blended Scotch Whisky", "Single Malt Scotch Whisky", "Vodka", "London Dry Gin",
    "Silver Tequila", "Dark Rum", "Brandy", "Red Wine", "Lager Beer",
]
_COUNTRY_POOL = ["Scotland", "Ireland", "Mexico", "France", "Canada", "Japan", "Italy", "Spain"]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def brand_decoys(brand: str) -> list[str]:
    words = brand.split()
    out = []
    if len(words) >= 2:
        out.append(" ".join(reversed(words)))                      # word order swapped
    out.append(re.sub(r"\s*(DISTILLERY|DISTILLERS|Distillery)$", "", brand).strip() + " DISTILLING CO."
               if re.search(r"distill", brand, re.I) else brand + " RESERVE")
    if len(words) >= 2:
        out.append(words[0] + " " + words[-1] + " & SONS")
    return _dedupe(out, brand)[:2]


def class_decoys(cls: str) -> list[str]:
    return [c for c in _CLASS_POOL if _norm(c) != _norm(cls)][:2]


def abv_decoys(abv_text: str) -> list[str]:
    pct = parse_abv(abv_text)
    if pct is None:
        return ["40% Alc./Vol. (80 Proof)", "50% Alc./Vol. (100 Proof)"]
    out = []
    for delta in (-5, +5, -3):
        v = pct + delta
        if v <= 0:
            continue
        out.append(_restyle_abv(abv_text, v))
    return _dedupe(out, abv_text)[:2]


def _restyle_abv(template: str, pct: float) -> str:
    """Rewrite the user's own format with a different number, so only the value differs."""
    s = re.sub(r"\d+(?:\.\d+)?(?=\s*%)", _fmt_num(pct), template)
    s = re.sub(r"\d+(?:\.\d+)?(?=\s*proof)", _fmt_num(pct * 2), s, flags=re.I)
    return s


def net_decoys(net_text: str) -> list[str]:
    ml = parse_volume_ml(net_text)
    if ml is None:
        return ["700 mL", "1 L"]
    cands = [700, 750, 1000, 375, 500, 1750]
    out = [f"{_fmt_num(v)} mL" if v < 1000 else f"{_fmt_num(v / 1000)} L"
           for v in cands if abs(v - ml) > 1]
    return out[:2]


def bottler_decoys(bottler: str) -> list[str]:
    words = bottler.split(",")[0].split()
    first = words[0] if words else "Acme"
    return _dedupe([f"{first} Spirits Co., Louisville, KY", f"Highland Bottling Ltd., Edinburgh"], bottler)[:2]


def origin_decoys(country: str) -> list[str]:
    return [c for c in _COUNTRY_POOL if _norm(c) != _norm(country)][:2]


def _dedupe(cands: list[str], expected: str) -> list[str]:
    seen, out = {_norm(expected)}, []
    for c in cands:
        if _norm(c) not in seen:
            seen.add(_norm(c))
            out.append(c)
    return out
