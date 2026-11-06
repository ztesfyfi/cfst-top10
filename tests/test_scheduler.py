from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.scheduler import Scheduler


class DummyEngine:
    def status(self):
        return {"status": "idle"}


def test_schedule_config_persists_and_validates(tmp_path: Path):
    scheduler = Scheduler(tmp_path, DummyEngine())
    saved = scheduler.update({
        "enabled": True, "mode": "interval", "interval_hours": 6,
        "timezone": "Asia/Shanghai", "top_n": 20,
    })
    assert saved["enabled"] is True
    assert saved["interval_hours"] == 6
    restored = Scheduler(tmp_path, DummyEngine())
    assert restored.status()["enabled"] is True
    assert restored.status()["top_n"] == 20
    assert restored.status()["next_run_at"] is not None


def test_schedule_rejects_invalid_values(tmp_path: Path):
    scheduler = Scheduler(tmp_path, DummyEngine())
    with pytest.raises(ValueError):
        scheduler.update({"interval_hours": 0})
    with pytest.raises(ValueError):
        scheduler.update({"timezone": "Not/AZone"})


def test_daily_schedule_calculates_next_run(tmp_path: Path):
    scheduler = Scheduler(tmp_path, DummyEngine())
    status = scheduler.update({
        "enabled": True, "mode": "daily", "daily_time": "03:30",
        "timezone": "Asia/Shanghai",
    })
    next_run = datetime.fromisoformat(status["next_run_at"])
    assert next_run.tzinfo is not None
    assert next_run > datetime.now(timezone.utc)
