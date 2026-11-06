from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GIST_ID_RE = re.compile(r"^[0-9a-fA-F]{20,64}$")
FILENAME_RE = {"ipv4": "ipv4.txt", "ipv6": "ipv6.txt"}
MAX_RESULT_BYTES = 2 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PublishError(RuntimeError):
    pass


class Publisher:
    """Independent Gist and Cloudflare Worker publishers for result TXT files."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.state_file = data_dir / "publish-state.json"
        self.config_file = data_dir / "publish-config.json"

    def _state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except (OSError, ValueError):
            pass
        return {"gist": {}, "cloudflare": {}}

    def _config(self) -> dict[str, str]:
        try:
            stored = json.loads(self.config_file.read_text(encoding="utf-8"))
            if not isinstance(stored, dict):
                stored = {}
        except (OSError, ValueError):
            stored = {}
        return {
            "gist_id": str(stored.get("gist_id") or os.getenv("CFST_GIST_ID", "")).strip(),
            "github_token": str(stored.get("github_token") or os.getenv("CFST_GITHUB_TOKEN", "")).strip(),
            "worker_url": str(stored.get("worker_url") or os.getenv("CFST_CF_WORKER_URL", "")).strip(),
            "worker_token": str(stored.get("worker_token") or os.getenv("CFST_CF_WORKER_TOKEN", "")).strip(),
        }

    def save_config(self, values: dict[str, Any]) -> dict[str, Any]:
        updated = self._config()
        for key in ("gist_id", "github_token", "worker_url", "worker_token"):
            value = values.get(key)
            if value is not None and str(value).strip():
                value = str(value).strip()
                if len(value) > 4096 or any(ord(ch) < 32 for ch in value):
                    raise PublishError("配置值长度或字符不合法")
                updated[key] = value
        if updated["gist_id"] and not GIST_ID_RE.fullmatch(updated["gist_id"]):
            raise PublishError("Gist ID 格式不正确")
        if updated["worker_url"]:
            parsed = urlsplit(updated["worker_url"])
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise PublishError("Worker 地址必须是有效 HTTPS 根地址")
            updated["worker_url"] = updated["worker_url"].rstrip("/")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.config_file.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(updated, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, self.config_file)
        return self.status()

    def status(self) -> dict[str, Any]:
        state = self._state()
        values = self._config()
        config = {
            "gist": bool(values["gist_id"] and values["github_token"]),
            "cloudflare": bool(values["worker_url"] and values["worker_token"]),
        }
        return {
            "gist_id": values["gist_id"],
            "worker_url": values["worker_url"],
            "targets": {
                name: {
                    "configured": config[name],
                    "files": state.get(name, {}),
                }
                for name in ("gist", "cloudflare")
            }
        }

    def _save(self, target: str, family: str, value: dict[str, Any]) -> None:
        state = self._state()
        state.setdefault(target, {})[family] = value
        temp = self.state_file.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, self.state_file)

    def _read_result(self, family: str) -> str:
        if family not in FILENAME_RE:
            raise PublishError("未知结果类型")
        path = self.data_dir / FILENAME_RE[family]
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise PublishError("本地结果文件不存在") from exc
        if not raw or len(raw) > MAX_RESULT_BYTES:
            raise PublishError("结果文件为空或超过 2 MiB")
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PublishError("结果文件不是有效 ASCII TXT") from exc
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or any(any(ch.isspace() for ch in line) for line in lines):
            raise PublishError("结果文件格式无效")
        import ipaddress
        try:
            for line in lines:
                parsed = ipaddress.ip_address(line)
                expected_version = 4 if family == "ipv4" else 6
                if parsed.version != expected_version:
                    raise PublishError(f"{family} 文件包含错误协议版本的地址")
        except ValueError as exc:
            raise PublishError("结果文件包含无效 IP") from exc
        return "\n".join(lines) + "\n"

    @staticmethod
    def _request(url: str, method: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read(3 * 1024 * 1024 + 1)
                if len(data) > 3 * 1024 * 1024:
                    raise PublishError("发布端响应超过 1 MiB")
                return response.status, data
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", "replace")
            raise PublishError(f"远端 HTTP {exc.code}: {detail[:500]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise PublishError(f"远端连接失败: {exc}") from exc

    def publish_gist(self, family: str, content: str) -> dict[str, Any]:
        config = self._config()
        gist_id = config["gist_id"]
        token = config["github_token"]
        if not GIST_ID_RE.fullmatch(gist_id) or not token:
            raise PublishError("Gist 未配置：检查 CFST_GIST_ID 和 CFST_GITHUB_TOKEN")
        payload = json.dumps({
            "files": {FILENAME_RE[family]: {"content": content}}
        }).encode("utf-8")
        self._request(
            f"https://api.github.com/gists/{gist_id}",
            "PATCH",
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "CFST-TOP10",
            },
            payload,
        )
        return {"ok": True, "updated_at": utc_now(), "gist_url": f"https://gist.github.com/{gist_id}"}

    def publish_cloudflare(self, family: str, content: str) -> dict[str, Any]:
        config = self._config()
        base = config["worker_url"].rstrip("/")
        token = config["worker_token"]
        if not base.startswith("https://") or not token:
            raise PublishError("Cloudflare 未配置：检查 HTTPS 的 CFST_CF_WORKER_URL 和 CFST_CF_WORKER_TOKEN")
        self._request(
            f"{base}/{FILENAME_RE[family]}",
            "PUT",
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/plain; charset=utf-8",
                "User-Agent": "CFST-TOP10",
            },
            content.encode("ascii"),
        )
        return {"ok": True, "updated_at": utc_now(), "url": f"{base}/{FILENAME_RE[family]}"}

    def publish(self, target: str, family: str) -> dict[str, Any]:
        if target not in {"gist", "cloudflare"}:
            raise PublishError("未知发布目标")
        if family not in FILENAME_RE:
            raise PublishError("未知结果类型")
        content = self._read_result(family)
        try:
            result = self.publish_gist(family, content) if target == "gist" else self.publish_cloudflare(family, content)
            state = {"status": "success", **result, "error": None}
        except Exception as exc:
            state = {"status": "failed", "updated_at": None, "error": str(exc)[:500]}
            self._save(target, family, state)
            raise PublishError(str(exc)) from exc
        self._save(target, family, state)
        return state

    def publish_all(self, family: str) -> dict[str, Any]:
        outcomes = {}
        for target in ("gist", "cloudflare"):
            config = self._config()
            configured = (
                bool(config["gist_id"] and config["github_token"])
                if target == "gist"
                else bool(config["worker_url"] and config["worker_token"])
            )
            if not configured:
                outcomes[target] = {"status": "not_configured"}
                continue
            try:
                outcomes[target] = self.publish(target, family)
            except PublishError as exc:
                outcomes[target] = {"status": "failed", "error": str(exc)}
        return outcomes
