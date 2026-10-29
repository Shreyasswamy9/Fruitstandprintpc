from conftest import CANON_ATTRS

from printhub.printers.capabilities import (
    check_preset, count_selected_pages, normalize_ipp, normalize_page_ranges, to_ipp_options, validate_settings,
)
from printhub.printers.cups import interpret_status, parse_markers, probe_device
from printhub.printers.ipp import TAG_KEYWORD, TAG_PRINTER, decode_response, encode_request, _encode_attr

CAPS = normalize_ipp(CANON_ATTRS)


def test_real_canon_capabilities():
    assert CAPS["copies"] == {"min": 1, "max": 999}
    assert {c["key"] for c in CAPS["color_modes"]} == {"color", "monochrome"}
    assert {s["key"] for s in CAPS["sides"]} == {"one-sided", "two-sided-long-edge", "two-sided-short-edge"}
    assert CAPS["finishings"] == []  # the Canon reports only "none"
    assert "na_letter_8.5x11in" in {m["key"] for m in CAPS["media"]}
    assert not any("fullbleed" in m["key"] or m["key"].startswith("custom_") for m in CAPS["media"])
    assert CAPS["collate"] is True and CAPS["page_ranges"] is True
    assert CAPS["defaults"]["sides"] == "two-sided-long-edge"


def test_unsupported_settings_are_errors_not_substitutions():
    clean, errors = validate_settings({"finishings": ["4"], "color_mode": "color", "media": "na_ledger_11x17in"}, CAPS)
    assert "finishings" in errors and "media" in errors
    assert clean == {"color_mode": "color"}
    _, errors = validate_settings({"copies": 0}, CAPS)
    assert "copies" in errors
    _, errors = validate_settings({"copies": 1000}, CAPS)
    assert "copies" in errors
    _, errors = validate_settings({"bogus": 1}, CAPS)
    assert "bogus" in errors


def test_settings_map_to_ipp_options():
    clean, errors = validate_settings({
        "copies": 3, "color_mode": "monochrome", "sides": "two-sided-short-edge", "media": "iso_a4_210x297mm",
        "orientation": "landscape", "scaling": "fit", "media_source": "tray-1", "media_type": "stationery",
        "quality": "draft", "collate": True,
    }, CAPS)
    assert not errors
    opts, copies = to_ipp_options(clean, "1-2,5")
    assert copies == 3
    assert opts == {
        "print-color-mode": "monochrome", "sides": "two-sided-short-edge", "media": "iso_a4_210x297mm",
        "orientation-requested": "4", "print-scaling": "fit", "media-source": "tray-1", "media-type": "stationery",
        "print-quality": "3", "multiple-document-handling": "separate-documents-collated-copies", "page-ranges": "1-2,5",
    }


def test_page_ranges():
    assert normalize_page_ranges("5, 1-3", 10) == ("1-3,5", None)
    assert normalize_page_ranges("", 10) == (None, None)
    assert normalize_page_ranges("4-2", 10)[1]
    assert "past the end" in normalize_page_ranges("1-12", 10)[1]
    assert normalize_page_ranges("1;2", 10)[1]
    assert count_selected_pages("1-3,5", 10) == 4


def test_preset_check_splits_supported_and_unsupported():
    result = check_preset({"color_mode": "color", "finishings": ["4"]}, CAPS)
    assert result["applicable"] == {"color_mode": "color"}
    assert "finishings" in result["unsupported"]


def test_status_and_markers_from_real_attributes():
    st = interpret_status(CANON_ATTRS)
    assert st.state == "ready" and st.accepting is True
    markers = parse_markers(CANON_ATTRS)
    assert [m["level"] for m in markers] == [52, 87, 87, 84]
    offline = interpret_status({**CANON_ATTRS, "printer-state-reasons": ["offline-report"]})
    assert offline.state == "offline"
    jam = interpret_status({**CANON_ATTRS, "printer-state-reasons": ["media-jam-error"]})
    assert jam.state == "attention"
    stopped = interpret_status({**CANON_ATTRS, "printer-state": [5]})
    assert stopped.state == "stopped"
    assert parse_markers({"marker-names": ["x"], "marker-levels": [-1]})[0]["level"] is None


def test_probe_does_not_claim_reachability_it_cannot_check():
    assert probe_device("dnssd://Canon._ipps._tcp.local./")["reachable"] is None
    assert probe_device("usb://Canon/MF")["reachable"] is None
    res = probe_device("socket://127.0.0.1:1", timeout=0.3)
    assert res["checked"] and res["reachable"] is False


def test_ipp_round_trip():
    req = encode_request(0x000B, 7, [(TAG_KEYWORD, "requested-attributes", ["a", "b"])])
    assert req[:2] == b"\x01\x01" and req[-1] == 3
    # Build a response by hand: status 0, one printer group with a multi-valued keyword
    body = bytes([1, 1, 0, 0, 0, 0, 0, 7, TAG_PRINTER]) + _encode_attr(TAG_KEYWORD, "sides-supported", ["one-sided", "two-sided-long-edge"]) + b"\x03"
    resp = decode_response(body)
    assert resp.ok and resp.first(TAG_PRINTER)["sides-supported"] == ["one-sided", "two-sided-long-edge"]
