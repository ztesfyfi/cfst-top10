from __future__ import annotations

import csv
import ipaddress
import json
import os
import signal
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .db import Database
from .sources import merge_ip_sources, read_text_file


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_cfst_csv(path: Path, top_n: int) -> list[str]:
    rows: list[tuple[float, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"IP 地址", "丢包率", "下载速度(MB/s)"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("CFST CSV 缺少必要列，无法安全解析")
        for row in reader:
            try:
                address = str(row["IP 地址"]).strip()
                ipaddress.ip_address(address)
                loss = float(str(row["丢包率"]).strip().rstrip("%"))
                speed = float(str(row["下载速度(MB/s)"]).strip())
                if loss == 0 and speed >= 0:
                    rows.append((speed, address))
            except (ValueError, TypeError, AttributeError):
                continue
    rows.sort(key=lambda item: (-item[0], item[1]))
    unique: list[str] = []
    seen: set[str] = set()
    for _, address in rows:
        if address not in seen:
            seen.add(address)
            unique.append(address)
        if len(unique) >= top_n:
            break
    return unique


class EngineManager:
    def __init__(self, data_dir: Path, engine_dir: Path, db: Database):
        self.data_dir = data_dir
        self.engine_dir = engine_dir
        self.db = db
        self.log_dir = data_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "engine.log"
        self.state_path = data_dir / "engine-state.json"
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None
        self._stop_requested = False
        self._state = self._read_state()

    def _read_state(self) -> dict:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state.get("status") == "running":
                state["status"] = "interrupted"
                state["message"] = "容器在任务运行期间停止；旧结果未被覆盖"
            return state
        except (OSError, ValueError):
            return {"status": "idle", "message": "尚未执行测速", "started_at": None,
                    "finished_at": None, "results": {}}

    def _save_state(self) -> None:
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.state_path)

    def _log(self, message: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{utc_now()}] {message}\n")

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def logs(self, limit: int = 250) -> list[str]:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        except OSError:
            return []

    def start(self, top_n: int = 10) -> dict:
        if not 1 <= top_n <= 1000:
            raise ValueError("TOP N 范围必须为 1～1000")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("已有测速任务正在运行")
            self._stop_requested = False
            self._state = {"status": "running", "message": "测速任务已启动",
                           "started_at": utc_now(), "finished_at": None,
                           "top_n": top_n, "results": {}}
            self._save_state()
            self._thread = threading.Thread(target=self._run, args=(top_n,), daemon=True)
            self._thread.start()
            return dict(self._state)

    def stop(self) -> dict:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                return dict(self._state)
            self._stop_requested = True
            process = self._process
            self._state["status"] = "stopping"
            self._state["message"] = "正在停止测速子进程"
            self._save_state()
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return self.status()

    def _enabled_contents(self) -> list[str]:
        contents = []
        for source in self.db.list_sources():
            if not source["enabled"]:
                continue
            path = Path(source["path"]) if source["path"] else None
            if path is None or not path.is_file():
                self._log(f"跳过不可用来源：{source['name']}")
                continue
            contents.append(read_text_file(path))
        return contents

    def _run(self, top_n: int) -> None:
        results: dict[str, dict] = {}
        try:
            merged = merge_ip_sources(self._enabled_contents())
            families = {
                "ipv4": [value for value in merged.entries
                         if ipaddress.ip_network(value, strict=False).version == 4],
                "ipv6": [value for value in merged.entries
                         if ipaddress.ip_network(value, strict=False).version == 6],
            }
            self._log(
                f"来源合并完成：合并前去重统计后 {len(merged.entries)} 条，"
                f"无效 {merged.invalid} 条，重复 {merged.duplicates} 条"
            )
            if not merged.entries:
                raise RuntimeError("没有可测速的有效 IP/CIDR")
            binary = self.engine_dir / "cfst"
            if not binary.is_file() or not os.access(binary, os.X_OK):
                raise RuntimeError("CFST 可执行文件不存在或不可执行")

            with tempfile.TemporaryDirectory(prefix="cfst-", dir="/tmp") as temp_dir:
                work = Path(temp_dir)
                for family, addresses in families.items():
                    with self._lock:
                        if self._stop_requested:
                            raise InterruptedError("用户已停止任务")
                    if not addresses:
                        results[family] = {"status": "skipped", "count": 0}
                        continue
                    input_file = work / f"{family}.txt"
                    csv_file = work / f"{family}.csv"
                    input_file.write_text("\n".join(addresses) + "\n", encoding="ascii")
                    command = [
                        str(binary), "-f", str(input_file), "-dn", str(top_n),
                        "-tlr", "0", "-o", str(csv_file), "-p", "0",
                    ]
                    self._log(f"{family} 开始测速，候选 {len(addresses)} 条")
                    process = subprocess.Popen(
                        command, cwd=str(self.engine_dir), stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        start_new_session=True, bufsize=1,
                    )
                    with self._lock:
                        self._process = process
                    assert process.stdout is not None
                    for line in process.stdout:
                        text = line.rstrip()
                        if text:
                            self._log(text)
                        with self._lock:
                            if self._stop_requested and process.poll() is None:
                                try:
                                    os.killpg(process.pid, signal.SIGTERM)
                                except ProcessLookupError:
                                    pass
                    return_code = process.wait()
                    with self._lock:
                        self._process = None
                        if self._stop_requested:
                            raise InterruptedError("用户已停止任务")
                    if return_code != 0:
                        raise RuntimeError(f"{family} CFST 退出码：{return_code}")
                    if not csv_file.is_file() or csv_file.stat().st_size == 0:
                        raise RuntimeError(f"{family} 未生成有效 CSV；保留旧结果")
                    selected = parse_cfst_csv(csv_file, top_n)
                    if not selected:
                        raise RuntimeError(f"{family} 没有符合零丢包条件的结果；保留旧结果")
                    target = self.data_dir / f"{family}.txt"
                    temp_target = target.with_suffix(".txt.tmp")
                    temp_target.write_text("\n".join(selected) + "\n", encoding="ascii")
                    os.replace(temp_target, target)
                    results[family] = {"status": "success", "count": len(selected),
                                       "file": target.name}
                    self._log(f"{family} 结果已原子保存：{len(selected)} 个 IP")

            with self._lock:
                self._state.update({"status": "completed", "message": "测速完成",
                                    "finished_at": utc_now(), "results": results,
                                    "input_count": len(merged.entries),
                                    "invalid": merged.invalid, "duplicates": merged.duplicates})
                self._save_state()
        except InterruptedError as exc:
            with self._lock:
                self._state.update({"status": "stopped", "message": str(exc),
                                    "finished_at": utc_now(), "results": results})
                self._save_state()
            self._log("测速任务已停止")
        except Exception as exc:
            self._log(f"任务失败：{exc}")
            with self._lock:
                self._state.update({"status": "failed", "message": str(exc),
                                    "finished_at": utc_now(), "results": results})
                self._save_state()
        finally:
            with self._lock:
                self._process = None
