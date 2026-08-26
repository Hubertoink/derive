from datetime import UTC, datetime

from app.main import discovery_next_due
from app.models import AppSettings


def test_first_scheduled_run_is_due_after_worker_starts_late(monkeypatch):
    monkeypatch.setattr("app.main.discovery_timezone", lambda _settings: UTC)
    settings = AppSettings(
        ai_provider="openai",
        discovery_frequency="interval",
        discovery_interval_days=1,
        discovery_time="09:00",
        discovery_timezone="test",
    )
    started_at = datetime(2026, 8, 26, 9, 17, tzinfo=UTC)

    assert discovery_next_due(settings, started_at) == datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
