from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from api.services import qmt_sync_scheduler_service


def test_should_run_accepts_naive_last_synced_at():
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(last_synced_at=(now - timedelta(seconds=40)).replace(tzinfo=None), sync_interval_seconds=30)
    assert qmt_sync_scheduler_service._should_run(row, now) is True


def test_should_run_respects_interval_for_aware_last_synced_at():
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(last_synced_at=now - timedelta(seconds=5), sync_interval_seconds=30)
    assert qmt_sync_scheduler_service._should_run(row, now) is False
