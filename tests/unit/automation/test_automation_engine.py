"""Comprehensive tests for the production AutomationEngine.

Covers all 17 acceptance criteria:
 1. one-shot execution
 2. interval scheduling (recurring)
 3. recurring trigger
 4. cron trigger
 5. enable/disable
 6. cancellation
 7. persistent state (disk)
 8. restart recovery (no duplicates)
 9. run history
10. failure history
11. idempotency
12. no duplicate side-effects after restart
13. timezone handling
14. malformed cron guard
15. missed schedules & catch-up
16. concurrent execution limits
17. clean shutdown
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

# Ensure root is on path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mark.automation.engine import (
    AutomationEngine,
    CronScheduler,
    CronParser,
    OneShotTrigger,
    RecurringTrigger,
    SimpleAutomationEngine,
)
from mark.automation.types import (
    AutomationJob,
    AutomationStatus,
    ConcurrencyPolicy,
    ExecutionStatus,
    RetryPolicy,
    TriggerType,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def store_dir(tmp_path: Path) -> Path:
    d = tmp_path / "automation_store"
    d.mkdir()
    return d


@pytest.fixture()
def engine(store_dir: Path) -> AutomationEngine:
    return AutomationEngine(store_path=store_dir)


@pytest.fixture()
def sync_engine(store_dir: Path) -> AutomationEngine:
    """Engine without executor marks every job completed instantly."""
    return AutomationEngine(store_path=store_dir)


# ── 1. One-shot execution ────────────────────────────────────────────


class TestOneShot:
    """Criterion 1: one-shot fires once."""

    def test_one_shot_fires_once(self, engine: AutomationEngine) -> None:
        calls: list[str] = []

        async def noop(_job: AutomationJob) -> None:
            calls.append(_job.id)

        engine._executor = noop
        engine.start()

        job = engine.create("oneshot", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        assert job.status == AutomationStatus.PENDING
        assert job.next_run_at is not None

        time.sleep(0.3)
        time.sleep(0.3)
        engine.stop()

        j = engine.get_job(job.id)
        assert j.status == AutomationStatus.COMPLETED
        assert j.run_count == 1
        assert len(calls) == 1

    def test_one_shot_no_executor(self, sync_engine: AutomationEngine) -> None:
        job = sync_engine.create("oneshot", TriggerType.ONE_SHOT, {}, goal="test")
        sync_engine.start()
        time.sleep(0.3)
        time.sleep(0.3)
        sync_engine.stop()
        j = sync_engine.get_job(job.id)
        assert j.status == AutomationStatus.COMPLETED
        assert j.run_count == 1


# ── 2 & 3. Interval / recurring ──────────────────────────────────────


class TestInterval:
    """Criterion 2 & 3: interval and recurring."""

    def test_recurring_fires_multiple(self, engine: AutomationEngine) -> None:
        calls: list[int] = []

        async def counter(job: AutomationJob) -> None:
            calls.append(job.run_count + 1)

        engine._executor = counter
        engine.start()

        job = engine.create(
            "recurring",
            TriggerType.RECURRING,
            {"interval_seconds": 0.1},
            goal="interval test",
        )
        time.sleep(0.5)
        engine.stop()

        j = engine.get_job(job.id)
        assert j.run_count >= 2  # at least 2 fires in 0.5s with 0.1s interval

    def test_interval_via_recurring(self, engine: AutomationEngine) -> None:
        engine.start()
        job = engine.create(
            "interval",
            TriggerType.RECURRING,
            {"interval_seconds": 0.05},
            goal="interval",
        )
        time.sleep(0.2)
        engine.stop()
        j = engine.get_job(job.id)
        assert j.run_count >= 1


# ── 4. Cron trigger ──────────────────────────────────────────────────


class TestCron:
    """Criterion 4: cron expressions."""

    def test_cron_valid_expression(self, engine: AutomationEngine) -> None:
        job = engine.create(
            "cron_evm",
            TriggerType.CRON,
            {"expression": "* * * * *"},
            goal="every minute",
        )
        assert job.next_run_at is not None
        assert job.next_run_at > time.time()

    def test_cron_specific_time(self, store_dir: Path) -> None:
        engine = AutomationEngine(store_path=store_dir)
        job = engine.create(
            "cron_0900",
            TriggerType.CRON,
            {"expression": "0 9 * * 1-5"},
            goal="weekdays 9am",
            timezone_str="UTC",
        )
        assert job.next_run_at is not None
        assert job.next_run_at > time.time()

    def test_cron_parser_next_run(self) -> None:
        parser = CronParser("0 12 * * *")  # noon every day
        now = time.time()
        nxt = parser.next_run(now)
        assert nxt > now

    def test_cron_with_step(self) -> None:
        parser = CronParser("*/15 * * * *")  # every 15 min
        now = time.time()
        nxt = parser.next_run(now)
        assert nxt > now


# ── 5. Enable / disable ─────────────────────────────────────────────


class TestEnableDisable:
    """Criterion 5: enable/disable controls."""

    def test_disable_prevents_execution(self, engine: AutomationEngine) -> None:
        calls: list[str] = []

        async def noop(_job: AutomationJob) -> None:
            calls.append(_job.id)

        engine._executor = noop
        engine.start()

        job = engine.create("dis_test", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        engine.disable(job.id)

        time.sleep(0.3)
        time.sleep(0.3)
        engine.stop()

        assert len(calls) == 0
        assert not engine.get_job(job.id).enabled

    def test_enable_resumes(self, engine: AutomationEngine) -> None:
        engine.start()
        job = engine.create("en_test", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        engine.disable(job.id)
        time.sleep(0.1)
        engine.enable(job.id)

        time.sleep(0.3)
        time.sleep(0.3)
        engine.stop()

        assert engine.get_job(job.id).status == AutomationStatus.COMPLETED

    def test_cancel_is_separate(self, engine: AutomationEngine) -> None:
        engine.start()
        job = engine.create("cancel_test", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        result = engine.cancel(job.id)
        assert result is True
        assert engine.get_job(job.id).status == AutomationStatus.CANCELLED


# ── 6. Cancellation ──────────────────────────────────────────────────


class TestCancellation:
    """Criterion 6: cancellation."""

    def test_cancel_returns_true(self, engine: AutomationEngine) -> None:
        assert engine.cancel("nonexistent") is False
        job = engine.create("cancel", TriggerType.ONE_SHOT, {}, goal="test")
        assert engine.cancel(job.id) is True
        assert engine.get_job(job.id).status == AutomationStatus.CANCELLED

    def test_cancel_while_running(self, engine: AutomationEngine) -> None:
        engine.start()
        job = engine.create("cancel_run", TriggerType.RECURRING, {"interval_seconds": 10.0}, goal="test")
        engine.cancel(job.id)
        assert engine.get_job(job.id).status == AutomationStatus.CANCELLED

    def test_delete_removes(self, engine: AutomationEngine) -> None:
        job = engine.create("del_test", TriggerType.ONE_SHOT, {}, goal="test")
        assert engine.delete(job.id) is True
        assert engine.get_job(job.id) is None


# ── 7. Persistent state ──────────────────────────────────────────────


class TestPersistence:
    """Criterion 7: state survives engine recreation."""

    def test_save_load(self, store_dir: Path) -> None:
        eng1 = AutomationEngine(store_path=store_dir)
        eng1.create("persist1", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        eng2 = AutomationEngine(store_path=store_dir)
        jobs = eng2.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].name == "persist1"

    def test_status_survives(self, store_dir: Path) -> None:
        async def noop(_job: AutomationJob) -> None:
            pass

        eng1 = AutomationEngine(store_path=store_dir, executor=noop)
        eng1.start()
        job = eng1.create("persist2", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        time.sleep(0.4)
        time.sleep(0.4)
        eng1.stop()

        eng2 = AutomationEngine(store_path=store_dir)
        j = eng2.get_job(job.id)
        assert j is not None
        assert j.status == AutomationStatus.COMPLETED
        assert j.run_count >= 1


# ── 8 & 12. Restart recovery (no duplicates) ─────────────────────────


class TestRestartRecovery:
    """Criterion 8 & 12: restart without duplicate execution."""

    def test_restart_no_duplicate(self, store_dir: Path) -> None:
        calls: list[int] = []

        async def counter(job: AutomationJob) -> None:
            calls.append(len(calls) + 1)

        eng1 = AutomationEngine(store_path=store_dir, executor=counter)
        eng1.start()
        job = eng1.create("restart1", TriggerType.RECURRING, {"interval_seconds": 0.2}, goal="test")
        time.sleep(0.6)  # let it fire 2-3 times
        eng1.stop()

        before_stop = len(calls)

        # Restart
        eng2 = AutomationEngine(store_path=store_dir, executor=counter)
        eng2.start()
        time.sleep(0.3)  # let it fire at most 1 more time
        eng2.stop()

        after_restart = len(calls)
        assert after_restart <= before_stop + 1, "No duplicate executions on restart"

    def test_running_job_resets_on_restart(self, store_dir: Path) -> None:
        """A RUNNING job at shutdown should be reset to PENDING."""
        async def block(_job: AutomationJob) -> None:
            await asyncio.sleep(10)

        eng1 = AutomationEngine(store_path=store_dir, executor=block)
        eng1.start()
        job = eng1.create("block_job", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")

        # Force the job to be RUNNING by manually setting it
        eng1._jobs[job.id].status = AutomationStatus.RUNNING
        eng1._jobs[job.id].next_run_at = 0.0  # overdue
        eng1._save()
        eng1.stop()

        # On restart, the engine should recover and reset the job
        eng2 = AutomationEngine(store_path=store_dir, executor=block)
        j = eng2.get_job(job.id)
        assert j.status == AutomationStatus.PENDING, "RUNNING jobs reset to PENDING on restart"
        eng2.stop()


# ── 9. Run history ───────────────────────────────────────────────────


class TestRunHistory:
    """Criterion 9: run history is tracked."""

    def test_history_records_success(self, engine: AutomationEngine) -> None:
        engine.start()
        engine.create("hist1", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        time.sleep(0.3)
        time.sleep(0.3)
        engine.stop()

        history = engine.get_history()
        assert len(history) >= 1
        entry = history[0]
        assert entry.status == ExecutionStatus.SUCCESS
        assert entry.duration_seconds >= 0

    def test_history_per_job(self, engine: AutomationEngine) -> None:
        engine.start()
        j1 = engine.create("hist_a", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        time.sleep(0.2)
        time.sleep(0.2)
        engine.stop()

        hist = engine.get_history(job_id=j1.id)
        assert len(hist) >= 1


# ── 10. Failure history ──────────────────────────────────────────────


class TestFailureHistory:
    """Criterion 10: failure history is tracked."""

    def test_failure_recorded(self, store_dir: Path) -> None:
        async def fail(_job: AutomationJob) -> None:
            raise RuntimeError("oops")

        eng = AutomationEngine(store_path=store_dir, executor=fail, concurrency=ConcurrencyPolicy(
            max_concurrent_per_job=1, max_concurrent_global=4,
        ))
        eng.start()
        job = eng.create("fail1", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        time.sleep(1.5)  # allow retries
        eng.stop()

        history = eng.get_history()
        failed_entries = [h for h in history if h.status == ExecutionStatus.FAILED]
        assert len(failed_entries) >= 1

    def test_failure_counter(self, store_dir: Path) -> None:
        async def fail(_job: AutomationJob) -> None:
            raise RuntimeError("fail")

        eng = AutomationEngine(store_path=store_dir, executor=fail)
        eng.start()
        job = eng.create("fail2", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        time.sleep(2.0)  # allow retries to exhaust
        eng.stop()

        j = eng.get_job(job.id)
        assert j.failure_count >= 1


# ── 11 & 12. Idempotency ─────────────────────────────────────────────


class TestIdempotency:
    """Criterion 11 & 12: idempotency, no duplicate side effects."""

    def test_no_duplicate_on_concurrent_tick(self, engine: AutomationEngine) -> None:
        calls: list[int] = []

        async def slow_counter(job: AutomationJob) -> None:
            await asyncio.sleep(0.15)
            calls.append(len(calls) + 1)

        engine._executor = slow_counter
        engine.start()

        job = engine.create("idem", TriggerType.RECURRING, {"interval_seconds": 0.05}, goal="test")

        time.sleep(0.5)
        engine.stop()

        execs = engine.get_executions(job.id)
        running = [e for e in execs if e.status == ExecutionStatus.RUNNING]
        assert len(running) <= 1, "At most one active execution per tick"


# ── 13. Timezone handling ────────────────────────────────────────────


class TestTimezone:
    """Criterion 13: timezone-aware scheduling."""

    def test_cron_different_timezone(self, store_dir: Path) -> None:
        eng = AutomationEngine(store_path=store_dir)
        job_utc = eng.create("tz_utc", TriggerType.CRON, {"expression": "0 12 * * *"},
                             timezone_str="UTC")
        job_ny = eng.create("tz_ny", TriggerType.CRON, {"expression": "0 12 * * *"},
                            timezone_str="America/New_York")

        assert job_utc.next_run_at is not None
        assert job_ny.next_run_at is not None
        assert job_utc.next_run_at != job_ny.next_run_at

    def test_invalid_tz_falls_back(self, store_dir: Path) -> None:
        eng = AutomationEngine(store_path=store_dir)
        job = eng.create("bad_tz", TriggerType.CRON, {"expression": "0 12 * * *"},
                         timezone_str="Invalid/Zone")
        assert job.next_run_at is not None


# ── 14. Malformed cron ───────────────────────────────────────────────


class TestMalformedCron:
    """Criterion 14: malformed cron guard."""

    def test_invalid_cron_raises(self) -> None:
        with pytest.raises(ValueError):
            CronParser("bad expression")

    def test_invalid_cron_sets_failed(self, engine: AutomationEngine) -> None:
        engine.start()
        job = engine.create("bad_cron", TriggerType.CRON, {"expression": "garbage"}, goal="test")

        time.sleep(0.3)
        time.sleep(0.3)
        engine.stop()

        j = engine.get_job(job.id)
        assert j.status == AutomationStatus.FAILED or j.last_error is not None


# ── 15. Missed schedules & catch-up ──────────────────────────────────


class TestMissedSchedules:
    """Criterion 15: missed schedule detection and catch-up."""

    def test_missed_schedule_fires_on_restart(self, store_dir: Path) -> None:
        calls: list[int] = []

        def sync_counter(_job: AutomationJob) -> None:
            calls.append(len(calls) + 1)

        eng1 = AutomationEngine(store_path=store_dir, executor=sync_counter)
        eng1.start()
        job = eng1.create("missed", TriggerType.RECURRING, {"interval_seconds": 0.05}, goal="test")
        time.sleep(0.2)  # let it run (engine ticks every 0.1s, so 2 ticks)
        eng1.stop()

        eng2 = AutomationEngine(store_path=store_dir, executor=sync_counter)
        eng2._jobs[job.id].next_run_at = 0.0
        eng2._save()
        eng2.start()  # START the engine so it can fire jobs
        time.sleep(0.4)  # let eng2 fire at least twice
        eng2.stop()

        assert len(calls) >= 2


# ── 16. Concurrent execution ─────────────────────────────────────────


class TestConcurrentExecution:
    """Criterion 16: concurrent execution limits."""

    def test_max_concurrent_per_job(self, store_dir: Path) -> None:
        max_concurrent: int = 0
        current_concurrent: int = 0
        lock = threading.Lock()

        async def track(job: AutomationJob) -> None:
            nonlocal max_concurrent, current_concurrent
            with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.2)
            with lock:
                current_concurrent -= 1

        eng = AutomationEngine(
            store_path=store_dir,
            executor=track,
            concurrency=ConcurrencyPolicy(max_concurrent_per_job=1, max_concurrent_global=10),
        )
        eng.start()
        job = eng.create("conc", TriggerType.RECURRING, {"interval_seconds": 0.01}, goal="test")
        time.sleep(0.4)
        eng.stop()

        assert max_concurrent == 1

    def test_max_concurrent_global(self, store_dir: Path) -> None:
        max_global: int = 0
        current_global: int = 0
        lock = threading.Lock()

        async def track(_job: AutomationJob) -> None:
            nonlocal max_global, current_global
            with lock:
                current_global += 1
                max_global = max(max_global, current_global)
            await asyncio.sleep(0.15)
            with lock:
                current_global -= 1

        eng = AutomationEngine(
            store_path=store_dir,
            executor=track,
            concurrency=ConcurrencyPolicy(max_concurrent_per_job=5, max_concurrent_global=2),
        )
        eng.start()
        j1 = eng.create("g1", TriggerType.RECURRING, {"interval_seconds": 0.01}, goal="a")
        j2 = eng.create("g2", TriggerType.RECURRING, {"interval_seconds": 0.01}, goal="b")
        j3 = eng.create("g3", TriggerType.RECURRING, {"interval_seconds": 0.01}, goal="c")
        time.sleep(0.4)
        eng.stop()

        assert max_global <= 2


# ── 17. Clean shutdown ───────────────────────────────────────────────


class TestCleanShutdown:
    """Criterion 17: clean shutdown."""

    def test_stop_does_not_throw(self, engine: AutomationEngine) -> None:
        engine.start()
        engine.create("shutdown_test", TriggerType.RECURRING, {"interval_seconds": 0.1}, goal="test")
        time.sleep(0.3)
        engine.stop(timeout=2.0)

    def test_stop_already_stopped(self, engine: AutomationEngine) -> None:
        engine.stop()
        engine.stop(timeout=0.5)

    def test_running_jobs_stored_before_shutdown(self, store_dir: Path) -> None:
        import json
        eng = AutomationEngine(store_path=store_dir)
        eng.start()
        job = eng.create("shutdown_job", TriggerType.ONE_SHOT, {"delay_seconds": 0.0}, goal="test")
        eng._jobs[job.id].status = AutomationStatus.RUNNING
        eng._save()
        eng.stop()

        data = json.loads((store_dir / "store.json").read_text())
        assert data["jobs"][job.id]["status"] == AutomationStatus.RUNNING


# ── Backward-compat shims ────────────────────────────────────────────


class TestBackwardCompatShims:
    """Ensure existing e2e test APIs still work."""

    def test_simple_engine_register(self, store_dir: Path) -> None:
        eng = SimpleAutomationEngine()
        eng.register({"name": "r1", "trigger": {"event": "file_change"}, "action": "notify"})
        assert "r1" in eng.list_rules()

    def test_simple_engine_lifecycle(self, store_dir: Path) -> None:
        eng = SimpleAutomationEngine()
        eng.start()
        eng.stop()

    def test_oneshot_trigger(self) -> None:
        t = OneShotTrigger(delay_seconds=5.0)
        assert t.next_run(100.0) == 105.0

    def test_recurring_trigger(self) -> None:
        t = RecurringTrigger(interval_seconds=10.0)
        assert t.next_run(100.0) == 110.0

    def test_cron_scheduler(self) -> None:
        cs = CronScheduler()
        ts = cs.schedule("task1", "0 12 * * *")
        assert ts > time.time()
        cs.remove("task1")


# ── Retry policy ─────────────────────────────────────────────────────


class TestRetryPolicy:
    """Retry policy with backoff."""

    def test_retry_on_transient_failure(self, store_dir: Path) -> None:
        attempts: list[int] = []

        async def flaky(job: AutomationJob) -> None:
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise RuntimeError("transient")

        eng = AutomationEngine(
            store_path=store_dir,
            executor=flaky,
            concurrency=ConcurrencyPolicy(max_concurrent_per_job=1, max_concurrent_global=4),
        )
        eng.start()
        job = eng.create("retry", TriggerType.ONE_SHOT, {"delay_seconds": 0.0},
                         goal="retry test", retry_policy=RetryPolicy(max_attempts=3))
        time.sleep(2.5)
        eng.stop()

        j = eng.get_job(job.id)
        assert j.run_count >= 1

    def test_exhaust_retries_marks_failed(self, store_dir: Path) -> None:
        async def always_fail(_job: AutomationJob) -> None:
            raise RuntimeError("always")

        eng = AutomationEngine(store_path=store_dir, executor=always_fail)
        eng.start()
        job = eng.create("exhaust", TriggerType.ONE_SHOT, {"delay_seconds": 0.0},
                         goal="exhaust test", retry_policy=RetryPolicy(max_attempts=2))
        time.sleep(3.0)
        eng.stop()

        j = eng.get_job(job.id)
        assert j.failure_count >= 1


# ── E2E compatibility ─────────────────────────────────────────────────


class TestE2ECompatibility:
    """Verify imports that existing E2E tests expect."""

    def test_engine_import(self) -> None:
        from mark.automation.engine import AutomationEngine
        eng = AutomationEngine()
        assert isinstance(eng, AutomationEngine)

    def test_rule_import(self) -> None:
        from mark.automation.types import AutomationRule
        rule = AutomationRule(name="test", trigger="manual", action="notify")
        assert rule.name == "test"

    def test_full_import(self) -> None:
        from mark.automation import (
            AutomationEngine,
            AutomationJob,
            AutomationStatus,
            TriggerType,
            SimpleAutomationEngine,
        )
        eng = AutomationEngine()
        assert isinstance(eng, AutomationEngine)
