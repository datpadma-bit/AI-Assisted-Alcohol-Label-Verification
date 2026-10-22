from app.verifier import (
    WARNING_CLAUSES, ApplicationData, Verdict, build_header_questions, build_label_questions,
    interpret, normalize_name, parse_abv, parse_volume_ml, verdict_for,
)

APP = ApplicationData(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
)


def noul(p):
    return {"type": "noul", "noul": p}


def pick(expected=0.9, d1=0.05, d2=0.03, none=0.02):
    probs = {"expected": expected, "d1": d1, "d2": d2, "none": none}
    return {"type": "choice", "choice": max(probs, key=probs.get), "probabilities": probs}


def label_answers(**overrides):
    base = {q: pick() for q in ("brand", "class_type", "abv", "net_contents")}
    base["warning_present"] = noul(0.97)
    for i in range(1, len(WARNING_CLAUSES) + 1):
        base[f"warning_clause_{i}"] = noul(0.8)
    base["abv_format"] = {"type": "choice", "choice": "percent_and_proof", "confidence": 0.8,
                          "probabilities": {"percent_and_proof": 0.9, "percent_only": 0.05,
                                            "proof_only": 0.03, "not_found": 0.02}}
    base["legibility"] = {"type": "score", "score": 1.6}
    base.update(overrides)
    return base


def header_answers(**overrides):
    base = {"header_title_case": noul(0.2),
            "header_style": {"type": "choice", "choice": "caps", "confidence": 0.9,
                             "probabilities": {"caps": 0.95, "title": 0.03, "other": 0.02}},
            "header_bold": noul(0.92)}
    base.update(overrides)
    return base


def test_identity_questions_offer_expected_value_plus_decoys():
    _, q = build_label_questions(APP)
    c = q["brand"]["criteria"]
    assert c["expected"] == "OLD TOM DISTILLERY"
    assert len([k for k in c if k.startswith("d")]) == 2
    assert "none" in c
    assert all(v != c["expected"] for k, v in c.items() if k != "expected")
    assert q["abv"]["criteria"]["d1"] != "45% Alc./Vol. (90 Proof)"
    assert "%" in q["abv"]["criteria"]["d1"]  # keeps the user's format, changes the number
    assert "bottler" not in q and "origin" not in q
    assert len([k for k in q if k.startswith("warning_clause_")]) == len(WARNING_CLAUSES) == 2


def test_optional_questions_added_when_data_present():
    imp = APP.model_copy(update={"country_of_origin": "Scotland", "bottler_name_address": "X Ltd, Glasgow"})
    _, q = build_label_questions(imp)
    assert q["origin"]["criteria"]["expected"] == "Scotland"
    assert "Scotland" not in [q["origin"]["criteria"]["d1"], q["origin"]["criteria"]["d2"]]
    assert "bottler" in q


def test_header_questions():
    _, q = build_header_questions()
    assert {"header_title_case", "header_style", "header_bold"} <= set(q)


def test_thresholds():
    assert verdict_for(0.95) == Verdict.MATCH
    assert verdict_for(0.5) == Verdict.NEEDS_REVIEW
    assert verdict_for(0.02) == Verdict.MISMATCH
    assert verdict_for(0.6, (0.5, 0.2)) == Verdict.MATCH


def test_all_good_is_match():
    r = interpret(label_answers(), header_answers(), APP)
    assert r.overall == Verdict.MATCH, [(f.field, f.verdict) for f in r.fields]
    assert r.legibility == "fully readable"
    assert {f.field for f in r.fields} >= {"brand", "warning_clause_1", "header_caps", "header_bold"}


def test_wrong_abv_is_mismatch_and_reports_what_was_seen():
    r = interpret(label_answers(abv=pick(expected=0.04, d1=0.9)), header_answers(), APP)
    assert r.overall == Verdict.MISMATCH
    abv = next(f for f in r.fields if f.field == "abv")
    assert abv.verdict == Verdict.MISMATCH
    assert abv.seen.startswith("40%") and "Label appears to show" in abv.note


def test_expected_wins_but_not_top_is_review():
    r = interpret(label_answers(brand=pick(expected=0.76, d1=0.78, d2=0.0, none=0.0)),
                  header_answers(), APP)
    b = next(f for f in r.fields if f.field == "brand")
    assert b.verdict == Verdict.NEEDS_REVIEW


def test_reworded_warning_flags_the_specific_clause():
    r = interpret(label_answers(warning_clause_2=noul(0.03)), header_answers(), APP)
    assert r.overall == Verdict.MISMATCH
    c2 = next(f for f in r.fields if f.field == "warning_clause_2")
    assert c2.verdict == Verdict.MISMATCH and c2.note.startswith("Expected:")
    assert next(f for f in r.fields if f.field == "warning_clause_1").verdict == Verdict.MATCH


def test_title_case_header_is_flagged():
    h = header_answers(header_title_case=noul(0.72),
                       header_style={"type": "choice", "choice": "caps",
                                     "probabilities": {"caps": 0.61, "title": 0.35, "other": 0.04}})
    r = interpret(label_answers(), h, APP)
    caps = next(f for f in r.fields if f.field == "header_caps")
    assert caps.verdict in (Verdict.NEEDS_REVIEW, Verdict.MISMATCH)
    assert "title case" in caps.note
    assert r.overall != Verdict.MATCH


def test_no_paragraph_crop_forces_review():
    r = interpret(label_answers(), None, APP)
    assert r.overall == Verdict.NEEDS_REVIEW
    assert all(f.verdict == Verdict.NEEDS_REVIEW for f in r.fields if f.field.startswith("header_"))


def test_crosscheck_abv_not_found_downgrades_match():
    la = label_answers(abv_format={"type": "choice", "choice": "not_found",
                                   "probabilities": {"not_found": 0.9, "percent_only": 0.1}})
    r = interpret(la, header_answers(), APP)
    assert next(f for f in r.fields if f.field == "abv").verdict == Verdict.NEEDS_REVIEW


def test_crosscheck_no_warning_but_clauses_match_downgrades():
    r = interpret(label_answers(warning_present=noul(0.02)), header_answers(), APP)
    assert all(f.verdict == Verdict.NEEDS_REVIEW for f in r.fields if f.field.startswith("warning_clause_"))


def test_details_are_reported():
    d = interpret(label_answers(), header_answers(), APP).to_dict()["details"]
    assert {x["field"] for x in d} == {"abv_format", "header_style"}


def test_parsers():
    assert parse_abv("45% Alc./Vol. (90 Proof)") == 45.0
    assert parse_abv("90 Proof") == 45.0
    assert parse_abv("n/a") is None
    assert parse_volume_ml("750 mL") == 750
    assert parse_volume_ml("1 L") == 1000
    assert normalize_name("STONE'S THROW") == normalize_name("Stone's Throw")


def test_whole_image_fallback_softens_header_mismatch_to_review():
    h = header_answers(header_title_case=noul(0.95),
                       header_style={"type": "choice", "choice": "title",
                                     "probabilities": {"caps": 0.03, "title": 0.95, "other": 0.02}})
    r = interpret(label_answers(), h, APP, paragraph_isolated=False)
    caps = next(f for f in r.fields if f.field == "header_caps")
    assert caps.verdict == Verdict.NEEDS_REVIEW and "whole label" in caps.note
    r2 = interpret(label_answers(), h, APP, paragraph_isolated=True)
    assert next(f for f in r2.fields if f.field == "header_caps").verdict == Verdict.MISMATCH
