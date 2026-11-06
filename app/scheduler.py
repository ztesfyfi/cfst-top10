from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


class Scheduler:
    """Single-process persistent scheduler; all work is delegated to EngineManager."""

    def __init__(self, data_dir: Path, engine):
        self.path = data_dir / "schedule.json"
        self.engine = engine
        self.lock = threading.RLock()
        self.wakeup = threading.Event()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.config = self._load()
        self.last_run_at = self.config.pop("last_run_at", None)
        self.last_result = self.config.pop("last_result", None)
        self.enabled_since = self.config.pop("enabled_since", iso(now_utc()))
        self.active_task_started = None

    @staticmethod
    def defaults() -> dict:
        return {"enabled": False, "mode": "interval", "interval_hours": 12,
                "daily_time": "03:30", "timezone": "Asia/Shanghai", "top_n": 10}

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            cfg = {**self.defaults(), **raw}
            self._validate(cfg)
            return cfg
        except (OSError, ValueError, TypeError, ZoneInfoNotFoundError):
            return self.defaults()

    def _validate(self, cfg: dict) -> None:
        if cfg["mode"] not in {"interval", "daily"}:
            raise ValueError("定时模式仅支持 interval 或 daily")
        if not 1 <= int(cfg["top_n"]) <= 1000:
            raise ValueError("TOP N 范围必须为 1～1000")
        if cfg["mode"] == "interval" and not 1 <= int(cfg["interval_hours"]) <= 720:
            raise ValueError("间隔小时数范围必须为 1～720")
        if cfg["mode"] == "daily":
            value = str(cfg["daily_time"])
            if len(value) != 5 or value[2] != ":":
                raise ValueError("每日执行时间格式应为 HH:MM")
            hour, minute = map(int, value.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("每日执行时间无效")
        try:
            ZoneInfo(str(cfg["timezone"]))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("时区名称无效，请使用 IANA 时区名称") from exc

    def _save(self) -> None:
        payload = {**self.config, "last_run_at": self.last_run_at,
                   "last_result": self.last_result, "enabled_since": self.enabled_since}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def update(self, values: dict) -> dict:
        with self.lock:
            candidate = {**self.config, **values}
            self._validate(candidate)
            was_enabled = bool(self.config["enabled"])
            self.config = candidate
            if candidate["enabled"] and not was_enabled:
                self.enabled_since = iso(now_utc())
            if not candidate["enabled"]:
                self.enabled_since = iso(now_utc())
            self._save()
            self.wakeup.set()
            return self.status()

    def _next_run(self) -> datetime | None:
        if not self.config["enabled"]:
            return None
        zone = ZoneInfo(self.config["timezone"])
        now = now_utc()
        if self.config["mode"] == "interval":
            base = datetime.fromisoformat(self.last_run_at) if self.last_run_at else datetime.fromisoformat(self.enabled_since)
            return base.astimezone(timezone.utc) + timedelta(hours=int(self.config["interval_hours"]))
        local_now = now.astimezone(zone)
        hour, minute = map(int, self.config["daily_time"].split(":"))
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if self.last_run_at:
            last_local = datetime.fromisoformat(self.last_run_at).astimezone(zone)
            if last_local.date() == local_now.date():
                candidate += timedelta(days=1)
            elif candidate <= local_now:
                candidate += timedelta(days=1)
        elif candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    def status(self) -> dict:
        with self.lock:
            next_run = self._next_run()
            return {**self.config, "last_run_at": self.last_run_at,
                    "last_result": self.last_result, "next_run_at": iso(next_run),
                    "scheduler_running": bool(self.thread and self.thread.is_alive())}

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, name="cfst-scheduler", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wakeup.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    due = self._next_run()
                    enabled = bool(self.config["enabled"])
                    if enabled and due and now_utc() >= due:
                        # Persist the trigger time before dispatch, preventing duplicate dispatch on restart.
                        self.last_run_at = iso(now_utc())
                        self.last_result = {"status": "dispatching", "triggered_at": self.last_run_at}
                        self._save()
                        top_n = int(self.config["top_n"])
                    else:
                        top_n = 0
                if top_n:
                    try:
                        result = self.engine.start(top_n, trigger="scheduled")
                        with self.lock:
                            self.active_task_started = result.get("started_at")
                            self.last_result = {"status": "started", "task": result}
                            self._save()
                    except Exception as exc:
                        with self.lock:
                            self.last_result = {"status": "skipped" if "正在运行" in str(exc) else "failed",
                                                "message": str(exc), "finished_at": iso(now_utc())}
                            self._save()
                with self.lock:
                    if self.active_task_started:
                        task = self.engine.status()
                        if task.get("started_at") == self.active_task_started and task.get("status") not in {"running", "stopping"}:
                            self.last_result = {"status": task.get("status"), "message": task.get("message"),
                                                "started_at": task.get("started_at"), "finished_at": task.get("finished_at"),
                                                "results": task.get("results", {})}
                            self.active_task_started = None
                            self._save()
                self.wakeup.wait(5)
                self.wakeup.clear()
            except Exception:
                self.wakeup.wait(5)
                self.wakeup.clear()
