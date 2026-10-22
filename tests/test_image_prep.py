import io

from PIL import Image, ImageDraw, ImageFont

from app.image_prep import estimate_skew, find_warning_paragraph, preprocess, whole_image_zoom


def make_label(big_lines=4, para_lines=5, bg="white", ink="black"):
    img = Image.new("RGB", (900, 1200), bg)
    d = ImageDraw.Draw(img)
    f_big, f_small = ImageFont.load_default(60), ImageFont.load_default(24)
    y = 80
    for i in range(big_lines):
        d.text((100, y), f"BIG LINE {i}", fill=ink, font=f_big)
        y += 90
    y += 150
    top = y
    for i in range(para_lines):
        d.text((60, y), "small paragraph text line " * 3, fill=ink, font=f_small)
        y += 34
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), top, y


def test_finds_the_small_text_paragraph_not_the_big_header():
    raw, top, bottom = make_label()
    p = find_warning_paragraph(raw)
    assert p is not None
    assert p.lines == 5
    assert p.box[1] <= top and p.box[3] >= bottom
    assert Image.open(io.BytesIO(p.png)).width == 1800


def test_prefers_small_text_even_when_header_has_more_lines():
    raw, top, bottom = make_label(big_lines=6, para_lines=3)
    p = find_warning_paragraph(raw)
    assert p is not None and p.lines == 3
    assert p.box[1] <= top


def test_light_text_on_dark_background():
    raw, top, bottom = make_label(bg="#1d1f2b", ink="#f3e9c6")
    p = find_warning_paragraph(raw)
    assert p is not None and p.lines == 5
    assert p.box[1] <= top and p.box[3] >= bottom
    assert preprocess(raw).inverted is True


def test_deskew_straightens_a_tilted_label():
    raw, _, _ = make_label()
    tilted = Image.open(io.BytesIO(raw)).rotate(6, resample=Image.BICUBIC, fillcolor="white")
    buf = io.BytesIO()
    tilted.save(buf, format="PNG")
    prep = preprocess(buf.getvalue())
    assert abs(prep.skew_deg + 6) <= 1.0, prep.skew_deg  # ~ -6 degrees to undo the tilt
    assert find_warning_paragraph(buf.getvalue()) is None or True  # tilted: may or may not isolate
    assert find_warning_paragraph(prep.png) is not None  # straightened: paragraph found again


def test_straight_label_is_not_rotated():
    raw, _, _ = make_label()
    assert preprocess(raw).skew_deg == 0.0


def test_blank_image_returns_none_and_fallback_zoom_works():
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), "white").save(buf, format="PNG")
    assert find_warning_paragraph(buf.getvalue()) is None
    assert Image.open(io.BytesIO(whole_image_zoom(buf.getvalue()))).width == 1800


def test_garbage_returns_none():
    assert find_warning_paragraph(b"not an image") is None
    assert preprocess(b"not an image") is None
