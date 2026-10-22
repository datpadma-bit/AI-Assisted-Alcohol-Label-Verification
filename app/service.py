"""Orchestration: single-label verify (two Clef passes in parallel) and concurrent batch verify."""
from __future__ import annotations

import asyncio
import csv
import io
import time

from pydantic import ValidationError

from .clef_client import ClefClient, ClefError, image_to_data_url
from .config import settings
from .verifier import (ApplicationData, build_header_questions, build_label_questions,
                       error_result, interpret)
from .image_prep import find_warning_paragraph, preprocess, whole_image_zoom


async def verify_label(client: ClefClient, image_bytes: bytes, app: ApplicationData) -> dict:
    t0 = time.perf_counter()
    prep_info: dict = {}
    try:
        prepared = preprocess(image_bytes)  # contrast + deskew, pure Python
        if prepared is None:
            raise ClefError("Unreadable image file. Please upload a valid PNG, JPEG or WebP.")
        img = prepared.png
        prep_info = {"skew_corrected_deg": round(prepared.skew_deg, 2), "inverted": prepared.inverted}

        state1, q1 = build_label_questions(app)
        tasks = [client.decide(state1, q1, images=[image_to_data_url(img)])]

        para = find_warning_paragraph(img)
        crop = para.png if para is not None else whole_image_zoom(img)
        prep_info["warning_paragraph_found"] = para is not None
        state2, q2 = build_header_questions(isolated=para is not None)
        tasks.append(client.decide(state2, q2, images=[image_to_data_url(crop, max_side=2000)]))

        answers = await asyncio.gather(*tasks)
        result = interpret(answers[0], answers[1], app, paragraph_isolated=para is not None)
    except (ClefError, ValueError) as exc:
        result = error_result(str(exc))
    out = result.to_dict()
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
    out["preprocessing"] = prep_info
    return out


REQUIRED_COLUMNS = ("filename", "brand_name", "class_type", "alcohol_content", "net_contents")


def parse_batch_csv(raw: bytes) -> tuple[dict[str, ApplicationData], dict[str, str]]:
    """CSV columns: filename, brand_name, class_type, alcohol_content, net_contents,
    [bottler_name_address], [country_of_origin].

    Returns (filename -> application, filename -> row error). A bad row does not reject the
    whole batch; its file is reported as Needs review with the error text.
    """
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 text") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV is empty")
    missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames)
    if missing:
        raise ValueError(f"CSV is missing columns: {sorted(missing)}")
    apps: dict[str, ApplicationData] = {}
    errors: dict[str, str] = {}
    for n, row in enumerate(reader, start=2):  # line 1 is the header
        fname = (row.get("filename") or "").strip()
        if not fname:
            continue
        clean = {k: v for k, v in row.items() if k and k != "filename"}
        try:
            apps[fname] = ApplicationData(**clean)
        except ValidationError as exc:
            problems = "; ".join(e["msg"].replace("Value error, ", "") for e in exc.errors())
            errors[fname] = f"CSV line {n}: {problems}"
    if not apps and not errors:
        raise ValueError("CSV has no data rows")
    return apps, errors


async def verify_batch(files: list[tuple[str, bytes]], apps: dict[str, ApplicationData],
                       row_errors: dict[str, str] | None = None) -> list[dict]:
    row_errors = row_errors or {}
    # Filenames match case-insensitively and ignoring any folder prefix ("labels/A.PNG" == "a.png")
    key = lambda n: n.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()  # noqa: E731
    apps_by_key = {key(n): a for n, a in apps.items()}
    errors_by_key = {key(n): e for n, e in row_errors.items()}
    sem = asyncio.Semaphore(settings.batch_concurrency)
    async with ClefClient() as client:

        async def one(name: str, data: bytes) -> dict:
            app = apps_by_key.get(key(name))
            if app is None:
                msg = errors_by_key.get(key(name), "No matching row in CSV (check the filename column)")
                return {"filename": name, "elapsed_ms": 0, **error_result(msg).to_dict()}
            async with sem:
                res = await verify_label(client, data, app)
            return {"filename": name, **res}

        rows = list(await asyncio.gather(*(one(n, d) for n, d in files)))
        uploaded = {key(n) for n, _ in files}
        for name in list(apps) + list(row_errors):
            if key(name) not in uploaded:
                rows.append({"filename": name, "elapsed_ms": 0,
                             **error_result("Listed in CSV but no image was uploaded").to_dict()})
        return rows


def batch_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["filename", "overall", "legibility", "field", "verdict", "confidence", "note", "error"])
    for r in rows:
        err = r.get("error") or ""
        if not r.get("fields"):
            w.writerow([r["filename"], r["overall"], r["legibility"], "", "", "", "", err])
        for f in r.get("fields", []):
            w.writerow([r["filename"], r["overall"], r["legibility"], f["label"], f["verdict"],
                        f["confidence"], f["note"], err])
    return buf.getvalue()
