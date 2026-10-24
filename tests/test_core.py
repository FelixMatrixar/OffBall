from offball.core import clock_label, parse_event_ref, parse_frame_ref


def test_frame_refs() -> None:
    assert parse_frame_ref("m07-f2-27000") == ("m07", 2, 27000)
    assert parse_frame_ref("a-b-f1-5") == ("a-b", 1, 5)
    assert parse_frame_ref("m07-f22-1") is None
    assert parse_frame_ref("m07-e0912") is None


def test_event_refs() -> None:
    assert parse_event_ref("m07-e0912") == ("m07", 912)
    assert parse_event_ref("m07-e12") is None
    assert parse_event_ref("m07-f2-1") is None


def test_clock_label() -> None:
    assert clock_label(2, 1_239_560) == "65:39"
    assert clock_label(1, 45 * 60_000 + 130_000) == "45+2:10"
