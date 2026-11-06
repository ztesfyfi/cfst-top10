import pytest
from app.sources import merge_ip_sources, parse_ip_list

def test_normalize_and_dedupe():
    r = parse_ip_list("192.0.2.1\n192.0.2.1\n2001:db8::1\n")
    assert r.entries == ("192.0.2.1", "2001:db8::1")
    assert r.duplicates == 1

def test_invalid_lines_counted():
    r = parse_ip_list("192.0.2.1\nnot-an-ip\n")
    assert r.invalid == 1

def test_cross_source_dedupe():
    r = merge_ip_sources(["192.0.2.1\n", "192.0.2.1\n2001:db8::1\n"])
    assert len(r.entries) == 2
    assert r.duplicates == 1

def test_oversized_rejected():
    with pytest.raises(ValueError):
        parse_ip_list("1" * (8 * 1024 * 1024 + 1))
