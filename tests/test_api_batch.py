"""End-to-end API tests for /api/batch and /api/verify with Clef stubbed out."""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import clef_client, main

def noul(p):
    return {"type": "noul", "noul": p}


def pick(expected=0.9, d1=0.05):
    probs = {"expected": expected, "d1": d1, "d2": 0.03, "none": 0.02}
    return {"type": "choice", "choice": max(probs, key=probs.get), "probabilities": probs}


GOOD = {q: pick() for q in ("brand", "class_type", "abv", "net_contents")}
GOOD.update({q: noul(0.98) for q in ("warning_present", "warning_clause_1", "warning_clause_2")})
GOOD["legibility"] = {"type": "score", "score": 2.0}
GOOD["abv_format"] = {"type": "choice", "choice": "percent_and_proof",
                      "probabilities": {"percent_and_proof": 0.9, "not_found": 0.1}}
HEADER_OK = {"header_title_case": noul(0.1), "header_bold": noul(0.95),
             "header_style": {"type": "choice", "choice": "caps",
                              "probabilities": {"caps": 0.95, "title": 0.05}}}
HEADER_TITLE = {"header_title_case": noul(0.95), "header_bold": noul(0.95),
                "header_style": {"type": "choice", "choice": "title",
                                 "probabilities": {"caps": 0.05, "title": 0.95}}}

UNSURE = {**GOOD, "brand": pick(expected=0.5, d1=0.4)}

CANNED = {"ok.png": (GOOD, HEADER_OK), "titlecase.png": (GOOD, HEADER_TITLE), "unsure.png": (UNSURE, HEADER_OK)}


def png(color):
    """Small label-like image with a 3-line paragraph so the Python crop finds something."""
    from PIL import ImageDraw, ImageFont
    img = Image.new("RGB", (300, 200), color)
    d = ImageDraw.Draw(img)
    f = ImageFont.load_default(14)
    for i in range(3):
        d.text((10, 100 + i * 20), "warning text line here", fill="black", font=f)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    """Stub Clef: pick canned answers by the brand name in the state (ties each file to a row)."""
    calls = []

    brand_of_last_label_call = {}

    async def fake_decide(self, state, questions, images=None, instructions=None):
        calls.append({"state": state, "questions": questions, "n_images": len(images or [])})
        if "header_bold" in questions:  # pass 2 (zoomed crop)
            return brand_of_last_label_call["h"]
        brand = questions["brand"]["criteria"]["expected"]
        label, header = CANNED[brand]
        brand_of_last_label_call["h"] = header
        return label

    monkeypatch.setattr(clef_client.ClefClient, "decide", fake_decide)
    monkeypatch.setattr(clef_client.settings, "cloudflare_account_id", "acct")
    monkeypatch.setattr(clef_client.settings, "cloudflare_api_token", "tok")
    c = TestClient(main.app)
    c.calls = calls
    return c


def manifest(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["filename", "brand_name", "class_type", "alcohol_content", "net_contents",
                "bottler_name_address", "country_of_origin"])
    w.writerows(rows)
    return buf.getvalue().encode()


def batch_files(names, rows):
    files = [("images", (n, png("white"), "image/png")) for n in names]
    files.append(("manifest", ("apps.csv", manifest(rows), "text/csv")))
    return files


def test_sample_cases_and_images_are_available():
    with TestClient(main.app) as client:
        response = client.get("/api/samples")

        assert response.status_code == 200
        samples = response.json()
        assert len(samples) == 13

        for sample in samples:
            image_response = client.get(sample["url"])
            assert image_response.status_code == 200
            assert image_response.headers["content-type"] == "image/png"

        manifest_response = client.get("/samples/manifest.csv")
        assert manifest_response.status_code == 200


ROWS = [
    ["ok.png", "ok.png", "Bourbon", "45% Alc./Vol. (90 Proof)", "750 mL", "", ""],
    ["titlecase.png", "titlecase.png", "Bourbon", "45%", "750 mL", "", ""],
    ["unsure.png", "unsure.png", "Bourbon", "45%", "750 mL", "", ""],
    ["orphan.png", "orphan.png", "Bourbon", "45%", "750 mL", "", ""],
]


def test_batch_json_shape_and_summary(client):
    names = ["ok.png", "titlecase.png", "unsure.png", "nocsv.png"]
    r = client.post("/api/batch", files=batch_files(names, ROWS))
    assert r.status_code == 200, r.text
    body = r.json()

    # orphan.png is in the CSV but was not uploaded -> reported as its own Needs review row
    assert body["summary"] == {"match": 1, "needs_review": 3, "mismatch": 1}
    by_name = {row["filename"]: row for row in body["results"]}
    assert set(by_name) == set(names) | {"orphan.png"}
    assert by_name["orphan.png"]["error"] == "Listed in CSV but no image was uploaded"

    assert by_name["ok.png"]["overall"] == "match"
    assert by_name["titlecase.png"]["overall"] == "mismatch"
    assert by_name["unsure.png"]["overall"] == "needs_review"

    # file with no CSV row -> error row, no Clef call, still reported
    orphan = by_name["nocsv.png"]
    assert orphan["overall"] == "needs_review"
    assert orphan["error"].startswith("No matching row in CSV")
    assert orphan["fields"] == []

    # two Clef calls per matched file (full label + zoomed warning crop), one image each
    assert len(client.calls) == 6
    assert all(c["n_images"] == 1 for c in client.calls)

    # per-field detail present and shaped correctly
    f = by_name["titlecase.png"]["fields"]
    caps = next(x for x in f if x["field"] == "header_caps")
    assert caps["verdict"] == "mismatch" and caps["confidence"] == 0.05
    d = next(x for x in by_name["titlecase.png"]["details"] if x["field"] == "header_style")
    assert d["choice"] == "title"
    assert "elapsed_ms" in by_name["ok.png"]


def test_batch_csv_download(client):
    names = ["ok.png", "titlecase.png"]
    r = client.post("/api/batch", files=batch_files(names, ROWS), data={"as_csv": "true"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert set(rows[0]) == {"filename", "overall", "legibility", "field", "verdict",
                            "confidence", "note", "error"}
    # 5 simple fields + 2 warning clauses + caps + bold = 9 rows per label (no bottler/origin)
    assert sum(1 for x in rows if x["filename"] == "ok.png") == 9
    tc = [x for x in rows if x["filename"] == "titlecase.png" and x["field"] == "Warning header ALL CAPS"]
    assert tc[0]["verdict"] == "mismatch" and tc[0]["overall"] == "mismatch"


def test_batch_rejects_bad_manifest(client):
    files = [("images", ("ok.png", png("white"), "image/png")),
             ("manifest", ("apps.csv", b"filename,brand_name\nok.png,x\n", "text/csv"))]
    r = client.post("/api/batch", files=files)
    assert r.status_code == 400
    assert "missing columns" in r.json()["detail"]


def test_batch_rejects_non_image(client):
    files = [("images", ("notes.txt", b"hello", "text/plain")),
             ("manifest", ("apps.csv", manifest(ROWS), "text/csv"))]
    r = client.post("/api/batch", files=files)
    assert r.status_code == 400
    assert "unsupported type" in r.json()["detail"]


def test_single_verify_matches_batch_result(client):
    r = client.post("/api/verify",
                    files={"image": ("ok.png", png("white"), "image/png")},
                    data={"brand_name": "ok.png", "class_type": "Bourbon",
                          "alcohol_content": "45% Alc./Vol. (90 Proof)", "net_contents": "750 mL"})
    assert r.status_code == 200
    body = r.json()
    assert body["overall"] == "match" and body["legibility"] == "fully readable"
    assert len(body["fields"]) == 9
    q = client.calls[-2]["questions"]  # pass 1
    assert {"brand", "warning_clause_1", "abv_format", "legibility"} <= set(q)
    assert "bottler" not in q
    assert "header_bold" in client.calls[-1]["questions"]  # pass 2


def test_verify_without_credentials_returns_clear_error(monkeypatch):
    monkeypatch.setattr(clef_client.settings, "cloudflare_account_id", "")
    monkeypatch.setattr(clef_client.settings, "cloudflare_api_token", "")
    monkeypatch.setattr(clef_client.settings, "clef_base_url", "")
    c = TestClient(main.app)
    r = c.post("/api/verify",
               files={"image": ("ok.png", png("white"), "image/png")},
               data={"brand_name": "x", "class_type": "y", "alcohol_content": "45%", "net_contents": "750 mL"})
    assert r.status_code == 200
    assert r.json()["overall"] == "needs_review"
    assert "CLOUDFLARE_ACCOUNT_ID" in r.json()["error"]
