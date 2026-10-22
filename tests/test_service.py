import pytest

from app.service import batch_to_csv, parse_batch_csv

HEADER = b"filename,brand_name,class_type,alcohol_content,net_contents,bottler_name_address,country_of_origin\n"


def test_parse_batch_csv():
    raw = (HEADER
           + b"a.png,OLD TOM DISTILLERY,Bourbon,45%,750 mL,,\n"
           + b"b.png,Glen Foo,Scotch Whisky,40%,700 mL,Glen Foo Ltd,Scotland\n")
    apps, errors = parse_batch_csv(raw)
    assert errors == {}
    assert apps["a.png"].country_of_origin is None
    assert apps["b.png"].country_of_origin == "Scotland"


def test_parse_batch_csv_missing_column():
    with pytest.raises(ValueError, match="missing columns"):
        parse_batch_csv(b"filename,brand_name\na.png,x\n")


def test_bad_row_is_reported_not_fatal():
    raw = (b"filename,brand_name,class_type,alcohol_content,net_contents\n"
           b"a.png,OLD TOM,Bourbon,45%,\n"
           b"b.png,  ,Bourbon,45%,750 mL\n"
           b"c.png,Good,Bourbon,45%,750 mL\n")
    apps, errors = parse_batch_csv(raw)
    assert list(apps) == ["c.png"]
    assert "net_contents" in errors["a.png"] and "line 2" in errors["a.png"]
    assert "brand_name" in errors["b.png"] and "line 3" in errors["b.png"]


def test_empty_and_header_only_csv():
    with pytest.raises(ValueError, match="empty"):
        parse_batch_csv(b"")
    with pytest.raises(ValueError, match="no data rows"):
        parse_batch_csv(HEADER)


def test_batch_to_csv_includes_error_rows():
    rows = [{"filename": "x.png", "overall": "needs_review", "legibility": "unknown",
             "fields": [], "error": "No matching row in CSV"}]
    out = batch_to_csv(rows)
    assert "No matching row in CSV" in out
