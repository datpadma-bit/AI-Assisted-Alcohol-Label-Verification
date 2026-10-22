"""FastAPI entrypoint. Images are processed in memory and never written to disk."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .clef_client import ClefClient
from .service import batch_to_csv, parse_batch_csv, verify_batch, verify_label
from .verifier import GOVERNMENT_WARNING, ApplicationData

app = FastAPI(title="TTB Label Verifier (Clef-omni prototype)")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
SAMPLES = Path(__file__).resolve().parent.parent / "samples"
if SAMPLES.is_dir():  # demo labels, handy for trying the UI
    app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")

ALLOWED = {"image/png", "image/jpeg", "image/webp"}
MAX_BYTES = 10 * 1024 * 1024


def _check_image(f: UploadFile, data: bytes) -> None:
    if f.content_type not in ALLOWED:
        raise HTTPException(
            400, f"{f.filename}: unsupported type {f.content_type}. Use PNG, JPEG or WebP.")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, f"{f.filename}: larger than 10 MB.")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/warning")
async def api_warning() -> dict:
    """The statutory warning text every label is checked against (27 CFR 16.21)."""
    return {"text": GOVERNMENT_WARNING}


@app.get("/api/samples")
async def api_samples() -> list[dict]:
    """Demo labels for the 'Try a sample' buttons: file, form values, expected verdict, note."""
    manifest = SAMPLES / "manifest.csv"
    if not manifest.exists():
        return []
    apps, _errors = parse_batch_csv(manifest.read_bytes())
    expected: dict[str, dict] = {}
    exp_path = SAMPLES / "expected.csv"
    if exp_path.exists():
        import csv
        import io
        for row in csv.DictReader(io.StringIO(exp_path.read_text(encoding="utf-8"))):
            expected[row["filename"]] = row
    return [
        {
            "filename": name,
            "url": f"/samples/{name}",
            "fields": application.model_dump(exclude_none=True),
            "expected": expected.get(name, {}).get("expected", ""),
            "note": expected.get(name, {}).get("note", ""),
        }
        for name, application in apps.items()
        if (SAMPLES / name).exists()
    ]


@app.post("/api/verify")
async def api_verify(
    image: UploadFile = File(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    alcohol_content: str = Form(...),
    net_contents: str = Form(...),
    bottler_name_address: str = Form(""),
    country_of_origin: str = Form(""),
) -> dict:
    data = await image.read()
    _check_image(image, data)
    try:
        application = ApplicationData(
            brand_name=brand_name,
            class_type=class_type,
            alcohol_content=alcohol_content,
            net_contents=net_contents,
            bottler_name_address=bottler_name_address or None,
            country_of_origin=country_of_origin or None,
        )
    except ValidationError as exc:
        msgs = [e["msg"].replace("Value error, ", "") for e in exc.errors()]
        raise HTTPException(422, "; ".join(msgs)) from exc
    async with ClefClient() as client:
        return await verify_label(client, data, application)


@app.post("/api/batch")
async def api_batch(
    images: list[UploadFile] = File(...),
    manifest: UploadFile = File(...),
    as_csv: bool = Form(False),
):
    try:
        apps, row_errors = parse_batch_csv(await manifest.read())
    except ValueError as exc:
        raise HTTPException(400, f"Bad manifest CSV: {exc}") from exc
    files: list[tuple[str, bytes]] = []
    for f in images:
        data = await f.read()
        _check_image(f, data)
        files.append((f.filename or "", data))
    rows = await verify_batch(files, apps, row_errors)
    if as_csv:
        return PlainTextResponse(
            batch_to_csv(rows), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=results.csv"})
    summary = {k: sum(1 for r in rows if r["overall"] == k)
               for k in ("match", "needs_review", "mismatch")}
    return {"summary": summary, "results": rows}
