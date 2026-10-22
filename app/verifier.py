"""Label verification logic.

Clef-omni is the witness: it looks at the image and answers fixed questions with probabilities.
Python is the judge: it writes the questions the way a human reviewer looks at a label
(WHAT is printed? HOW is the header written?), builds wrong answers from the user's inputs so
Clef has something to compare against, zooms where needed, cross-checks the answers, and turns
them into Match / Needs review / Mismatch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from . import decoys
from .config import settings
from .verifier_text import normalize_name, parse_abv, parse_volume_ml  # noqa: F401  (re-exported)

GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or operate "
    "machinery, and may cause health problems."
)
WARNING_HEADER = "GOVERNMENT WARNING:"
WARNING_CLAUSES = [c.strip() for c in re.split(r"(?=\(\d\))", GOVERNMENT_WARNING.split(": ", 1)[1])
                   if c.strip()]


class ApplicationData(BaseModel):
    brand_name: str = Field(..., min_length=1)
    class_type: str = Field(..., min_length=1)
    alcohol_content: str = Field(..., min_length=1)
    net_contents: str = Field(..., min_length=1)
    bottler_name_address: str | None = None
    country_of_origin: str | None = None  # imports only

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        """Trim whitespace; blank optional fields become None, blank required fields fail."""
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("brand_name", "class_type", "alcohol_content", "net_contents", mode="before")
    @classmethod
    def _required(cls, v, info):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"{info.field_name} is required and cannot be blank")
        return v


class Verdict(str, Enum):
    MATCH = "match"
    NEEDS_REVIEW = "needs_review"
    MISMATCH = "mismatch"


@dataclass
class FieldResult:
    field: str
    label: str
    verdict: Verdict
    confidence: float  # probability that the check passes
    note: str = ""
    seen: str = ""     # what the model thinks the label actually shows (from the choice answer)


@dataclass
class ChoiceResult:
    field: str
    choice: str
    description: str
    confidence: float
    probabilities: dict[str, float]


@dataclass
class VerificationResult:
    overall: Verdict
    legibility: str
    fields: list[FieldResult] = field(default_factory=list)
    details: list[ChoiceResult] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.value,
            "legibility": self.legibility,
            "error": self.error,
            "details": [
                {
                    "field": d.field,
                    "choice": d.choice,
                    "description": d.description,
                    "confidence": round(d.confidence, 3),
                    "probabilities": {k: round(v, 3) for k, v in d.probabilities.items()},
                }
                for d in self.details
            ],
            "fields": [
                {
                    "field": f.field,
                    "label": f.label,
                    "verdict": f.verdict.value,
                    "confidence": round(f.confidence, 3),
                    "note": f.note,
                    "seen": f.seen,
                }
                for f in self.fields
            ],
        }


_LEGIBILITY = ["unreadable", "partially readable", "fully readable"]

# (match_at, mismatch_at). Measured on sample labels:
#   identity choices: correct value 0.86-0.96, wrong value 0.04
#   warning clauses:  correct sentence 0.6-0.9, reworded 0.01-0.2
#   header case:      ALL CAPS 0.9, Title Case 0.44
IDENTITY_THRESHOLDS = (0.75, 0.25)
CLAUSE_THRESHOLDS = (0.5, 0.2)
HEADER_THRESHOLDS = (0.8, 0.3)

_IDENTITY: list[tuple[str, str, str, Any]] = [
    # qid, label, question, decoy builder
    ("brand", "Brand name", "WHAT brand name is printed on the label?", decoys.brand_decoys),
    ("class_type", "Class / type", "WHAT class/type designation is printed on the label?", decoys.class_decoys),
    ("abv", "Alcohol content", "WHAT alcohol content is printed on the label?", decoys.abv_decoys),
    ("net_contents", "Net contents", "WHAT net contents is printed on the label?", decoys.net_decoys),
    ("bottler", "Bottler name & address", "WHAT bottler/producer name and address is printed on the label?",
     decoys.bottler_decoys),
    ("origin", "Country of origin", "WHAT country of origin is printed on the label?", decoys.origin_decoys),
]
_APP_FIELD = {"brand": "brand_name", "class_type": "class_type", "abv": "alcohol_content",
              "net_contents": "net_contents", "bottler": "bottler_name_address", "origin": "country_of_origin"}


def _choice(question: str, expected: str, wrong: list[str]) -> dict[str, Any]:
    # Option IDs are visible to the model and measurably change its answer. On the sample labels
    # the brand question scores 0.84-0.87 with ids expected/d1/d2/none but only 0.3-0.4 with
    # wrong_1/wrong_2 or a/b/c/d. Keep these ids as they are.
    criteria = {"expected": expected}
    for i, w in enumerate(wrong, 1):
        criteria[f"d{i}"] = w
    criteria["none"] = "none of these"
    return {"type": "choice", "instructions": question, "criteria": criteria}


# ---------------------------------------------------------------------------------------------
# Pass 1: the whole label
# ---------------------------------------------------------------------------------------------

def build_label_questions(app: ApplicationData) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    state = {"task": "You are a compliance agent inspecting an alcohol beverage label image. "
                     "Answer each question only from what is printed on the label."}
    q: dict[str, dict[str, Any]] = {}
    for qid, _label, question, make_decoys in _IDENTITY:
        value = getattr(app, _APP_FIELD[qid])
        if not value:
            continue
        q[qid] = _choice(question, value, make_decoys(value))

    q["warning_present"] = {"type": "noul", "instructions":
                            "A government health warning paragraph is printed on the label. True?"}
    for i, clause in enumerate(WARNING_CLAUSES, 1):
        q[f"warning_clause_{i}"] = {"type": "noul", "instructions":
                                    f'This sentence is printed in the warning with exactly these words: "{clause}". True?'}

    q["abv_format"] = {
        "type": "choice",
        "instructions": "HOW is the alcohol content expressed on the label?",
        "criteria": {
            "percent_and_proof": "Both % Alc./Vol. and Proof",
            "percent_only": "Only % Alc./Vol. or % ABV",
            "proof_only": "Only Proof",
            "not_found": "No alcohol content on the label",
        },
    }
    q["legibility"] = {
        "type": "score",
        "instructions": "HOW readable is the text on this label image?",
        "criteria": _LEGIBILITY,
    }
    return state, q


# ---------------------------------------------------------------------------------------------
# Pass 2: a Python-made zoomed crop of the warning paragraph
# ---------------------------------------------------------------------------------------------

def build_header_questions(isolated: bool = True) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if isolated:
        task = ("This image is a zoomed crop of the government warning paragraph from an "
                "alcohol beverage label. Look closely at the letters of the header.")
    else:
        task = ("This is an alcohol beverage label. Find the government warning paragraph and "
                "look closely at the letters of its header.")
    state = {"task": task}
    q = {
        "header_title_case": {"type": "noul", "instructions":
                              "The warning header is written as 'Government Warning' in title case, "
                              "with lowercase letters after the first G and W. True?"},
        "header_style": {
            "type": "choice",
            "instructions": "HOW is the warning header written?",
            "criteria": {
                "caps": "every letter is a capital: GOVERNMENT WARNING",
                "title": "only the first letters are capitals: Government Warning",
                "other": "something else",
            },
        },
        "header_bold": {"type": "noul", "instructions":
                        "The words GOVERNMENT WARNING are printed in thicker, bolder letters than "
                        "the sentences that follow them. True?"},
    }
    return state, q


# ---------------------------------------------------------------------------------------------
# Reading Clef answers
# ---------------------------------------------------------------------------------------------

def prob(answer: Any) -> float:
    """Clef `noul` answer -> probability of true. Live shape: {"type": "noul", "noul": 0.95}."""
    if isinstance(answer, (int, float)):
        return float(answer)
    if isinstance(answer, dict):
        for k in ("noul", "probability", "p", "true"):
            if k in answer:
                return float(answer[k])
        probs = answer.get("probabilities")
        if isinstance(probs, dict) and "true" in probs:
            return float(probs["true"])
    raise ValueError(f"Cannot read probability from {answer!r}")


def choice_probs(answer: Any) -> dict[str, float]:
    if isinstance(answer, dict) and isinstance(answer.get("probabilities"), dict):
        return {k: float(v) for k, v in answer["probabilities"].items()}
    return {}


def verdict_for(p: float, thresholds: tuple[float, float] | None = None) -> Verdict:
    match_at, mismatch_at = thresholds or (settings.match_threshold, settings.mismatch_threshold)
    if p >= match_at:
        return Verdict.MATCH
    if p <= mismatch_at:
        return Verdict.MISMATCH
    return Verdict.NEEDS_REVIEW


# ---------------------------------------------------------------------------------------------
# The judge
# ---------------------------------------------------------------------------------------------

def interpret(label_answers: dict[str, Any], header_answers: dict[str, Any] | None,
              app: ApplicationData, paragraph_isolated: bool = True) -> VerificationResult:
    fields: list[FieldResult] = []
    _, questions = build_label_questions(app)

    # Identity fields: P(expected) is the confidence; the top wrong option is what the label "shows"
    for qid, label, _question, _mk in _IDENTITY:
        if qid not in label_answers:
            continue
        probs = choice_probs(label_answers[qid])
        if not probs:
            continue
        p = probs.get("expected", 0.0)
        v = verdict_for(p, IDENTITY_THRESHOLDS)
        top = max(probs, key=probs.get)
        seen = questions[qid]["criteria"].get(top, top) if top != "expected" else ""
        note = ""
        if v != Verdict.MATCH and seen:
            note = f"Label appears to show: {seen}"
        if v == Verdict.MATCH and top != "expected":
            v, note = Verdict.NEEDS_REVIEW, f"Model leaned towards: {seen}"
        fields.append(FieldResult(qid, label, v, p, note, seen))

    if "warning_present" in label_answers:
        p = prob(label_answers["warning_present"])
        fields.append(FieldResult("warning_present", "Warning present", verdict_for(p), p))

    # Warning wording: one verdict per clause, so the agent sees WHICH sentence is wrong
    for i, clause in enumerate(WARNING_CLAUSES, 1):
        qid = f"warning_clause_{i}"
        if qid in label_answers:
            p = prob(label_answers[qid])
            v = verdict_for(p, CLAUSE_THRESHOLDS)
            note = "" if v == Verdict.MATCH else f'Expected: "{clause}"'
            fields.append(FieldResult(qid, f"Warning sentence ({i})", v, p, note))

    # Header case and weight from the zoomed crop: two reads of case averaged
    if header_answers:
        p_title = prob(header_answers["header_title_case"]) if "header_title_case" in header_answers else 0.5
        p_caps = ((1 - p_title) + choice_probs(header_answers.get("header_style")).get("caps", 0.5)) / 2
        v = verdict_for(p_caps, HEADER_THRESHOLDS)
        note = "" if v == Verdict.MATCH else "Possible 'Government Warning' in title case. Check by eye."
        if not paragraph_isolated and v == Verdict.MISMATCH:
            v, note = Verdict.NEEDS_REVIEW, "Read from the whole label, not a zoomed crop. Check by eye."
        fields.append(FieldResult("header_caps", "Warning header ALL CAPS", v, p_caps, note))
        p_bold = prob(header_answers["header_bold"]) if "header_bold" in header_answers else 0.5
        v = verdict_for(p_bold, HEADER_THRESHOLDS)
        note = "" if v == Verdict.MATCH else "Bold weight is a visual judgment. Check by eye."
        if not paragraph_isolated and v == Verdict.MISMATCH:
            v, note = Verdict.NEEDS_REVIEW, "Read from the whole label, not a zoomed crop. Check by eye."
        fields.append(FieldResult("header_bold", "Warning header bold", v, p_bold, note))
    else:
        for qid, label in (("header_caps", "Warning header ALL CAPS"), ("header_bold", "Warning header bold")):
            fields.append(FieldResult(qid, label, Verdict.NEEDS_REVIEW, 0.5,
                                      "Could not isolate the warning paragraph in the image."))

    # Predefined-choice details (the HOW)
    details: list[ChoiceResult] = []
    merged = {**label_answers, **(header_answers or {})}
    for qid in ("abv_format", "header_style"):
        ans = merged.get(qid)
        probs = choice_probs(ans)
        if not probs:
            continue
        choice = (ans.get("choice") if isinstance(ans, dict) else None) or max(probs, key=probs.get)
        conf = float(ans.get("confidence", probs.get(choice, 0.0))) if isinstance(ans, dict) else probs[choice]
        details.append(ChoiceResult(qid, choice, choice.replace("_", " "), conf, probs))

    # Cross-checks between independent answers
    fmt = next((d for d in details if d.field == "abv_format"), None)
    if fmt and fmt.choice == "not_found" and fmt.probabilities.get("not_found", 0) > 0.6:
        for f in fields:
            if f.field == "abv" and f.verdict == Verdict.MATCH:
                f.verdict, f.note = Verdict.NEEDS_REVIEW, "Model also reports no alcohol content visible."
    wp = next((f for f in fields if f.field == "warning_present"), None)
    if wp and wp.verdict == Verdict.MISMATCH:
        for f in fields:
            if f.field.startswith("warning_clause_") and f.verdict == Verdict.MATCH:
                f.verdict, f.note = Verdict.NEEDS_REVIEW, "Conflicts with 'warning present' answer."

    leg = label_answers.get("legibility")
    if isinstance(leg, dict) and "score" in leg:
        idx = min(len(_LEGIBILITY) - 1, max(0, round(float(leg["score"]))))
        legibility = _LEGIBILITY[idx]
    else:
        legibility = "unknown"

    if any(f.verdict == Verdict.MISMATCH for f in fields):
        overall = Verdict.MISMATCH
    elif any(f.verdict == Verdict.NEEDS_REVIEW for f in fields) or legibility == "unreadable":
        overall = Verdict.NEEDS_REVIEW
    else:
        overall = Verdict.MATCH
    return VerificationResult(overall=overall, legibility=legibility, fields=fields, details=details)


def error_result(msg: str) -> VerificationResult:
    return VerificationResult(overall=Verdict.NEEDS_REVIEW, legibility="unknown", error=msg)
