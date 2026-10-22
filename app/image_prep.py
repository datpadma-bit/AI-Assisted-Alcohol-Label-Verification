"""Pure-Pillow image preparation. NO model here: Clef-omni is the only model in this project.

- `preprocess`: normalise contrast and straighten a tilted photo (projection-profile deskew).
- `find_warning_paragraph`: find the paragraph of smallest text (the warning) with a row-ink
  profile, handling both dark-on-light and light-on-dark labels, and return a zoomed crop.

Clef-omni reads letter case and font weight far better from the zoomed crop than from the whole
label, and reads everything better from a straightened, contrast-normalised image.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps


@dataclass
class Paragraph:
    box: tuple[int, int, int, int]
    lines: int
    png: bytes


@dataclass
class Prepared:
    png: bytes
    skew_deg: float
    inverted: bool  # light text on dark background


def _load(raw: bytes) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        return img.convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def _to_png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG", compress_level=1)  # optimize=True takes ~8 s on noisy photos
    return out.getvalue()


def _ink_gray(img: Image.Image) -> tuple[Image.Image, bool]:
    """Grayscale where ink is dark. Inverts light-on-dark labels. Returns (gray, inverted)."""
    gray = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)
    hist = gray.histogram()
    dark = sum(hist[:128])
    inverted = dark > sum(hist[128:])  # mostly dark pixels -> dark background
    if inverted:
        gray = ImageOps.invert(gray)
    return gray, inverted


# --- deskew ------------------------------------------------------------------------------------

def _row_means(gray: Image.Image) -> list[int]:
    """Mean value of every row, computed in C by a box-filter resize to a 1-pixel-wide column."""
    return list(gray.resize((1, gray.height), Image.BOX).getdata())


def _row_profile_score(gray: Image.Image) -> float:
    """Variance of the row-ink profile: straight text lines give a spiky profile, tilted a flat one."""
    rows = _row_means(gray)
    mean = sum(rows) / len(rows)
    return sum((r - mean) ** 2 for r in rows) / len(rows)


def estimate_skew(gray: Image.Image, max_deg: float = 12.0) -> float:
    """Angle (degrees) that straightens the text; 0.0 if already straight."""
    small = gray.copy()
    small.thumbnail((300, 400))
    small = small.crop((int(small.width * 0.1), int(small.height * 0.1),
                        int(small.width * 0.9), int(small.height * 0.9)))

    def score(a: float) -> float:
        return _row_profile_score(small.rotate(a, resample=Image.BILINEAR, fillcolor=255))

    base = score(0.0)
    coarse = {a: score(a) for a in range(-int(max_deg), int(max_deg) + 1, 2)}
    best = max(coarse, key=coarse.get)
    fine = {a / 4: score(a / 4) for a in range(int(best * 4) - 6, int(best * 4) + 7)}
    best_f = max(fine, key=fine.get)
    if fine[best_f] < base * 1.15:  # not meaningfully better than untouched -> leave it
        return 0.0
    return best_f


def preprocess(raw: bytes) -> Prepared | None:
    img = _load(raw)
    if img is None:
        return None
    gray, inverted = _ink_gray(img)
    angle = estimate_skew(gray)
    out = ImageOps.autocontrast(img, cutoff=1)
    if abs(angle) >= 0.5:
        fill = (20, 20, 20) if inverted else (235, 235, 235)
        out = out.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=fill)
    return Prepared(png=_to_png(out), skew_deg=angle, inverted=inverted)


# --- paragraph finder --------------------------------------------------------------------------

def _text_lines(gray: Image.Image, thr: int = 128, min_h: int = 5) -> list[tuple[int, int]]:
    h = gray.height
    # Binarise (ink -> 255), then the row mean is the fraction of ink pixels in that row.
    binary = gray.point(lambda v: 255 if v < thr else 0)
    ink = [m > 255 * 0.01 for m in _row_means(binary)]
    lines, y = [], 0
    while y < h:
        if ink[y]:
            s = y
            while y < h and ink[y]:
                y += 1
            if y - s >= min_h:
                lines.append((s, y))
        else:
            y += 1
    return lines


def _blocks(lines: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    if not lines:
        return []
    blocks, cur = [], [lines[0]]
    for ln in lines[1:]:
        gap = ln[0] - cur[-1][1]
        lh = cur[-1][1] - cur[-1][0]
        if gap <= lh * 1.2:
            cur.append(ln)
        else:
            blocks.append(cur)
            cur = [ln]
    blocks.append(cur)
    return blocks


def find_warning_paragraph(raw: bytes, zoom_width: int = 1800) -> Paragraph | None:
    """Return a zoomed crop of the most paragraph-like text block, or None if nothing found."""
    img = _load(raw)
    if img is None:
        return None
    w, h = img.size
    # Ignore a thin outer margin so a printed border does not read as one giant text line.
    mx, my = int(w * 0.05), int(h * 0.03)
    gray, inverted = _ink_gray(img.crop((mx, my, w - mx, h - my)))
    blocks = [b for b in _blocks(_text_lines(gray)) if len(b) >= 2]
    if not blocks:
        return None

    def median_height(b: list[tuple[int, int]]) -> int:
        heights = sorted(y1 - y0 for y0, y1 in b)
        return heights[len(heights) // 2]

    # The warning is the paragraph of smallest text; more lines breaks ties.
    best = min(blocks, key=lambda b: (median_height(b), -len(b)))
    top, bot = best[0][0] + my, best[-1][1] + my
    pad = int((bot - top) * 0.15) + 10
    box = (0, max(0, top - pad), w, min(h, bot + pad))
    crop = img.crop(box)
    if inverted:  # light-on-dark: hand Clef ordinary dark-on-light text
        crop = ImageOps.invert(crop)
    s = zoom_width / crop.width
    crop = crop.resize((zoom_width, max(1, int(crop.height * s))), Image.LANCZOS)
    return Paragraph(box=box, lines=len(best), png=_to_png(crop))


def whole_image_zoom(raw: bytes, zoom_width: int = 1800) -> bytes | None:
    """Fallback for the header pass when no paragraph could be isolated."""
    img = _load(raw)
    if img is None:
        return None
    s = zoom_width / img.width
    return _to_png(img.resize((zoom_width, max(1, int(img.height * s))), Image.LANCZOS))
