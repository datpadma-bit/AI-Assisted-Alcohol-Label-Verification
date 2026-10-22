from app.decoys import abv_decoys, brand_decoys, class_decoys, net_decoys, origin_decoys


def test_brand_decoys_differ_from_brand():
    d = brand_decoys("OLD TOM DISTILLERY")
    assert len(d) == 2 and "OLD TOM DISTILLERY" not in d
    assert "DISTILLERY TOM OLD" in d


def test_abv_decoys_keep_format_change_number():
    d = abv_decoys("45% Alc./Vol. (90 Proof)")
    assert d == ["40% Alc./Vol. (80 Proof)", "50% Alc./Vol. (100 Proof)"]
    assert abv_decoys("40% ABV") == ["35% ABV", "45% ABV"]
    assert len(abv_decoys("strong")) == 2


def test_net_decoys():
    assert net_decoys("750 mL") == ["700 mL", "1 L"]
    assert "1 L" not in net_decoys("1 L")


def test_class_and_origin_decoys_exclude_expected():
    assert "Kentucky Straight Bourbon Whiskey" not in class_decoys("kentucky straight bourbon whiskey")
    assert "Scotland" not in origin_decoys("Scotland")
