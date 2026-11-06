from pathlib import Path

import pytest

from app.publish import PublishError, Publisher


def make_publisher(tmp_path: Path) -> Publisher:
    (tmp_path / "ipv4.txt").write_text("192.0.2.1\n192.0.2.2\n", encoding="ascii")
    (tmp_path / "ipv6.txt").write_text("2001:db8::1\n", encoding="ascii")
    return Publisher(tmp_path)


def test_result_validation_rejects_invalid_ip(tmp_path: Path):
    publisher = make_publisher(tmp_path)
    (tmp_path / "ipv4.txt").write_text("not-an-ip\n", encoding="ascii")
    with pytest.raises(PublishError, match="无效 IP"):
        publisher._read_result("ipv4")


def test_gist_publish_uses_expected_endpoint_and_payload(tmp_path: Path, monkeypatch):
    publisher = make_publisher(tmp_path)
    monkeypatch.setenv("CFST_GIST_ID", "a" * 32)
    monkeypatch.setenv("CFST_GITHUB_TOKEN", "test-token")
    calls = []

    def fake_request(url, method, headers, body=None):
        calls.append((url, method, headers, body))
        return 200, b"{}"

    monkeypatch.setattr(publisher, "_request", fake_request)
    result = publisher.publish("gist", "ipv4")
    assert result["status"] == "success"
    assert calls[0][0] == "https://api.github.com/gists/" + "a" * 32
    assert calls[0][1] == "PATCH"
    assert b"ipv4.txt" in calls[0][3]
    assert b"192.0.2.1" in calls[0][3]


def test_cloudflare_publish_requires_https_and_token(tmp_path: Path, monkeypatch):
    publisher = make_publisher(tmp_path)
    monkeypatch.setenv("CFST_CF_WORKER_URL", "http://worker.example")
    monkeypatch.setenv("CFST_CF_WORKER_TOKEN", "secret")
    with pytest.raises(PublishError, match="HTTPS"):
        publisher.publish("cloudflare", "ipv4")


def test_publish_all_runs_destinations_independently(tmp_path: Path, monkeypatch):
    publisher = make_publisher(tmp_path)
    monkeypatch.setenv("CFST_GIST_ID", "b" * 32)
    monkeypatch.setenv("CFST_GITHUB_TOKEN", "gist-token")
    monkeypatch.setenv("CFST_CF_WORKER_URL", "https://worker.example")
    monkeypatch.setenv("CFST_CF_WORKER_TOKEN", "cf-token")

    def fake_gist(family, content):
        return {"status": "success"}

    def fail_cf(family, content):
        raise PublishError("simulated CF failure")

    monkeypatch.setattr(publisher, "publish_gist", fake_gist)
    monkeypatch.setattr(publisher, "publish_cloudflare", fail_cf)
    result = publisher.publish_all("ipv4")
    assert result["gist"]["status"] == "success"
    assert result["cloudflare"]["status"] == "failed"

def test_result_validation_rejects_wrong_address_family(tmp_path: Path):
    publisher = make_publisher(tmp_path)
    (tmp_path / "ipv4.txt").write_text("2001:db8::1\n", encoding="ascii")
    with pytest.raises(PublishError, match="错误协议版本"):
        publisher._read_result("ipv4")


def test_cloudflare_publish_uses_put_and_returns_public_url(tmp_path: Path, monkeypatch):
    publisher = make_publisher(tmp_path)
    monkeypatch.setenv("CFST_CF_WORKER_URL", "https://worker.example")
    monkeypatch.setenv("CFST_CF_WORKER_TOKEN", "cf-token")
    calls = []

    def fake_request(url, method, headers, body=None):
        calls.append((url, method, headers, body))
        return 200, b"OK"

    monkeypatch.setattr(publisher, "_request", fake_request)
    result = publisher.publish("cloudflare", "ipv6")
    assert result["status"] == "success"
    assert calls[0][0] == "https://worker.example/ipv6.txt"
    assert calls[0][1] == "PUT"
    assert calls[0][2]["Authorization"] == "Bearer cf-token"
    assert result["url"] == "https://worker.example/ipv6.txt"



def test_publish_config_is_saved_private_and_never_returned(tmp_path: Path):
    publisher = make_publisher(tmp_path)
    result = publisher.save_config({
        "gist_id": "c" * 32,
        "github_token": "very-secret-github-token",
        "worker_url": "https://worker.example",
        "worker_token": "very-secret-worker-token",
    })
    assert result["targets"]["gist"]["configured"] is True
    assert result["targets"]["cloudflare"]["configured"] is True
    assert "very-secret-github-token" not in str(result)
    assert "very-secret-worker-token" not in str(result)
    assert publisher.config_file.stat().st_mode & 0o777 == 0o600
    assert publisher._config()["github_token"] == "very-secret-github-token"
    assert publisher._config()["worker_token"] == "very-secret-worker-token"


def test_publish_config_rejects_non_https_worker_url(tmp_path: Path):
    publisher = make_publisher(tmp_path)
    with pytest.raises(PublishError, match="HTTPS"):
        publisher.save_config({"worker_url": "http://worker.example"})
