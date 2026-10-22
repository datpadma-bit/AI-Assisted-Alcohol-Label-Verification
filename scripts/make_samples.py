"""Generate synthetic test labels + manifest.csv into samples/. Run: uv run python scripts/make_samples.py

Twelve labels: the README example, deliberate failures for each check, an import label with
bottler and country of origin, Dave's "STONE'S THROW vs Stone's Throw" case, a dark label design,
and three photo-style degradations (tilt + blur + noise, glare, low light).
"""
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `app` importable

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.verifier import GOVERNMENT_WARNING

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)
WARN_BODY = GOVERNMENT_WARNING.split(": ", 1)[1]
random.seed(7)


def font(size: int, bold: bool = False):
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def wrap(draw, text, f, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def render(brand, cls, abv, net, *, bottler=None, origin=None, header="GOVERNMENT WARNING:",
           header_bold=True, body=WARN_BODY, warning=True, bg="#f7f1e1", ink="#2b1a0a",
           warn_ink="black", border="#5a3a1a", warn_size=26):
    W, H = 900, 1200
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, W - 20, H - 20], outline=border, width=6)
    y = 80
    rows = [(brand, 64, True), (cls, 36, False), (abv, 34, False), (net, 34, False)]
    if bottler:
        rows.append((bottler, 24, False))
    if origin:
        rows.append((origin, 28, True))
    for text, size, bold in rows:
        f = font(size, bold)
        d.text(((W - d.textlength(text, font=f)) / 2, y), text, fill=ink, font=f)
        y += size + 30
    if warning:
        y += 60
        hf, bf = font(warn_size, header_bold), font(warn_size)
        x = 60
        lh = int(warn_size * 1.4)
        d.text((x, y), header, fill=warn_ink, font=hf)
        hw = d.textlength(header + " ", font=hf)
        first = wrap(d, body, bf, W - 2 * x - hw)
        d.text((x + hw, y), first[0], fill=warn_ink, font=bf)
        y += lh
        for line in wrap(d, " ".join(first[1:]), bf, W - 2 * x):
            d.text((x, y), line, fill=warn_ink, font=bf)
            y += lh
    return img


# --- photo-style degradations ---------------------------------------------------------------

def tilt_blur_noise(img: Image.Image) -> Image.Image:
    out = img.rotate(7, resample=Image.BICUBIC, expand=True, fillcolor="#777")
    out = out.filter(ImageFilter.GaussianBlur(1.2))
    px = out.load()
    for _ in range(out.width * out.height // 12):
        x, y = random.randrange(out.width), random.randrange(out.height)
        r, g, b = px[x, y]
        n = random.randint(-28, 28)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return out


def glare(img: Image.Image) -> Image.Image:
    out = img.copy()
    overlay = Image.new("L", out.size, 0)
    od = ImageDraw.Draw(overlay)
    od.ellipse([120, 300, 620, 1050], fill=170)  # bright blob over the warning area
    overlay = overlay.filter(ImageFilter.GaussianBlur(70))
    white = Image.new("RGB", out.size, "white")
    return Image.composite(white, out, overlay)


def low_light(img: Image.Image) -> Image.Image:
    out = ImageEnhance.Brightness(img).enhance(0.45)
    out = ImageEnhance.Contrast(out).enhance(0.75)
    return out.filter(ImageFilter.GaussianBlur(0.6))


# --- the set ----------------------------------------------------------------------------------

OLD_TOM = dict(brand="OLD TOM DISTILLERY", cls="Kentucky Straight Bourbon Whiskey",
               abv="45% Alc./Vol. (90 Proof)", net="750 mL")
GLEN = dict(brand="GLEN FOO", cls="Single Malt Scotch Whisky", abv="40% Alc./Vol. (80 Proof)", net="700 mL",
            bottler="Distilled and bottled by Glen Foo Distillers Ltd., Dufftown, Scotland",
            origin="PRODUCT OF SCOTLAND")

# filename -> (render kwargs, post-process, application row, expected overall, note)
SET = {
    "ok.png": (OLD_TOM, None, OLD_TOM, "match", "README example label, everything correct"),
    "wrong_abv.png": ({**OLD_TOM, "abv": "40% Alc./Vol. (80 Proof)"}, None, OLD_TOM, "mismatch",
                      "label says 40%, application says 45%"),
    "wrong_net_contents.png": ({**OLD_TOM, "net": "700 mL"}, None, OLD_TOM, "mismatch",
                               "label says 700 mL, application says 750 mL"),
    "wrong_brand.png": ({**OLD_TOM, "brand": "OLD TOM DISTILLING CO."}, None, OLD_TOM, "mismatch",
                        "label brand differs from application"),
    "reworded_warning.png": ({**OLD_TOM, "body": "(1) Pregnant women should not drink alcohol. "
                              "(2) Alcohol impairs driving and may cause health problems."}, None, OLD_TOM,
                             "mismatch", "warning sentences reworded"),
    "missing_warning.png": ({**OLD_TOM, "warning": False}, None, OLD_TOM, "mismatch", "no warning at all"),
    "titlecase_warning.png": ({**OLD_TOM, "header": "Government Warning:"}, None, OLD_TOM, "needs_review",
                              "header in Title Case (Jenny's rejection)"),
    "import_scotch.png": (GLEN, None, GLEN, "match", "import label with bottler + country of origin"),
    "case_variant_brand.png": ({**OLD_TOM, "brand": "Stone's Throw"}, None, {**OLD_TOM, "brand": "STONE'S THROW"},
                               "match", "Dave's case: label Stone's Throw, application STONE'S THROW"),
    "dark_label.png": ({**OLD_TOM, "bg": "#1d1f2b", "ink": "#f3e9c6", "warn_ink": "#f3e9c6",
                        "border": "#c9a84c"}, None, OLD_TOM, "match", "dark design, light text"),
    "photo_tilted.png": (OLD_TOM, tilt_blur_noise, OLD_TOM, "needs_review",
                         "tilted 7°, blurred, noisy: deskewed in Python, one warning sentence reads ~0.35 -> human look"),
    "photo_glare.png": (OLD_TOM, glare, OLD_TOM, "match", "glare blob over the warning"),
    "photo_low_light.png": (OLD_TOM, low_light, OLD_TOM, "match", "dark, low contrast"),
}


def main():
    rows = []
    for name, (kw, post, app, expected, note) in SET.items():
        render_kw = {k: v for k, v in kw.items() if k in {
            "brand", "cls", "abv", "net", "bottler", "origin", "header", "header_bold", "body",
            "warning", "bg", "ink", "warn_ink", "border", "warn_size"}}
        img = render(render_kw.pop("brand"), render_kw.pop("cls"), render_kw.pop("abv"),
                     render_kw.pop("net"), **render_kw)
        if post:
            img = post(img)
        img.save(OUT / name)
        rows.append({
            "filename": name,
            "brand_name": app["brand"], "class_type": app["cls"],
            "alcohol_content": app["abv"], "net_contents": app["net"],
            "bottler_name_address": app.get("bottler", ""),
            "country_of_origin": "Scotland" if app.get("origin") else "",
            "expected": expected, "note": note,
        })
        print("wrote", name)
    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["filename", "brand_name", "class_type", "alcohol_content",
                                           "net_contents", "bottler_name_address", "country_of_origin"])
        w.writeheader()
        w.writerows({k: r[k] for k in w.fieldnames} for r in rows)
    with open(OUT / "expected.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["filename", "expected", "note"])
        w.writeheader()
        w.writerows({k: r[k] for k in w.fieldnames} for r in rows)
    print("wrote manifest.csv and expected.csv")


if __name__ == "__main__":
    main()
