"""Call Clef-omni for real on every label in samples/manifest.csv and compare with expected.csv.

Run: uv run python scripts/live_check.py            (all labels)
     uv run python scripts/live_check.py ok.png     (one label, full detail)
"""
import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `app` importable

from app.clef_client import ClefClient
from app.service import parse_batch_csv, verify_label

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def load_expected() -> dict[str, tuple[str, str]]:
    p = SAMPLES / "expected.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as fh:
        return {r["filename"]: (r["expected"], r["note"]) for r in csv.DictReader(fh)}


async def main(only: str | None):
    apps, errors = parse_batch_csv((SAMPLES / "manifest.csv").read_bytes())
    if errors:
        print("manifest errors:", errors)
    expected = load_expected()
    names = [only] if only else list(apps)
    hits = 0
    async with ClefClient() as client:
        for name in names:
            res = await verify_label(client, (SAMPLES / name).read_bytes(), apps[name])
            exp, note = expected.get(name, ("?", ""))
            ok = res["overall"] == exp
            hits += ok
            mark = "OK " if ok else "XX "
            bad = [f"{f['label']} {f['confidence']:.2f}" for f in res["fields"] if f["verdict"] != "match"]
            print(f"{mark}{name:26} got={res['overall']:13} want={exp:13} {res['elapsed_ms']:5} ms  "
                  f"{res['legibility']:18} flagged: {', '.join(bad) or '-'}")
            if res["error"]:
                print("     ERROR:", res["error"])
            if only:
                for f in res["fields"]:
                    print(f"     {f['verdict']:13} {f['confidence']:.2f}  {f['label']}"
                          + (f"  [{f['seen']}]" if f['seen'] else "") + (f"  {f['note']}" if f['note'] else ""))
                for d in res["details"]:
                    print(f"     choice  {d['confidence']:.2f}  {d['field']} -> {d['choice']}")
    if not only:
        print(f"\n{hits}/{len(names)} labels got the expected overall verdict")


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
