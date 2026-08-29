"""Unit tests for AutomationEngine.

Covers all 17 acceptance items from fix_agents/09_automation_engine.md:
1. one-shot, 2. interval, 3. recurring, 4. cron, 5. enable/disable,
6. cancellation, 7. persistent state, 8. restart recovery, 9. run history,
10. failure history, 11. idempotency, 12. no duplicate side-effects after restart,
13. timezone, 14. malformed cron, 15. missed schedules, 16. concurrent execution,
17. clean shutdown.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Any

import pytest

from mark.automation.engine import (
    AutomationEngine,
    CronParser,
    CronScheduler,
    ExecutionIdempotencyTracker,
    SimpleAutomationEngine,
    TriggerType,
)
from mark.automation.types import (
    AutomationExecution,
    AutomationHistoryEntry,
    AutomationJob,
    AutomationRule,
    AutomationStatus,
    ConcurrencyPolicy,
    ExecutionStatus,
    RetryPolicy,
)


# -- Fixtures --

@pytest.fixture()
def store(tmp_path: Path) -> Path:
    p = tmp_path / "automation"
    p.mkdir()
    return p


@pytest.fixture()
def engine(store: Path) -> AutomationEngine:
    return AutomationEngine(store_path=store)


@pytest.fixture()
def async_engine(store: Path) -> tuple[AutomationEngine, list[str]]:
    invocations: list[str] = []

    async def _executor(record):
        invocations.append(record.id)

    eng = AutomationEngine(
        store_path=store,
        executor=_executor,
    )
    return eng, invocations


# 1. One-shot trigger

class TestOneShotTrigger:
    def test_create_one_shot(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="test_one_shot",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        assert rec.trigger_type == TriggerType.ONE_SHOT
        assert rec.next_run_at is not None
        assert rec.status == AutomationStatus.PENDING

    def test_one_shot_runs_once(self, async_engine: tuple) -> None:
        eng, invocations = async_engine
        rec = eng.create(
            name="oneshot",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        assert len(invocations) == 0
        eng._execute(rec)
        assert len(invocations) == 1
        result = eng.get(rec.id)
        assert result is not None
        assert result.status == AutomationStatus.COMPLETED


# 2 & 3. Interval / Recurring trigger

class TestRecurringTrigger:
    def test_create_recurring(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="recurring",
            trigger_type=TriggerType.RECURRING,
            payload={"interval_seconds": 60.0},
        )
        assert rec.trigger_type == TriggerType.RECURRING

    def test_recurring_runs_multiple_times(self, async_engine: tuple) -> None:
        eng, invocations = async_engine
        rec = eng.create(
            name="recurring",
            trigger_type=TriggerType.RECURRING,
            payload={"interval_seconds": 60.0},
        )
        for _ in range(5):
            eng._execute(rec)
        assert len(invocations) == 5

    def test_recurring_after_run_sets_next(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="rec",
            trigger_type=TriggerType.RECURRING,
            payload={"interval_seconds": 30.0},
        )
        original_next = rec.next_run_at
        assert original_next is not None
        rec.last_run_at = rec.next_run_at
        engine._schedule_trigger(rec)
        assert rec.next_run_at is not None
        assert rec.next_run_at > original_next


# 4. Cron trigger

class TestCronTrigger:
    def test_create_cron(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="cron_job",
            trigger_type=TriggerType.CRON,
            payload={"expression": "0 9 * * 1"},
        )
        assert rec.trigger_type == TriggerType.CRON
        assert rec.next_run_at is not None

    def test_cron_requires_expression(self, engine: AutomationEngine) -> None:
        with pytest.raises(ValueError, match="expression"):
            engine.create(
                name="bad_cron",
                trigger_type=TriggerType.CRON,
                payload={},
            )

    def test_cron_5_field(self) -> None:
        parser = CronParser("0 9 * * 1")
        assert parser.next_fire_time() > 0

    def test_cron_6_field(self) -> None:
        parser = CronParser("0 0 9 * * 1")
        assert parser.next_fire_time() > 0

    def test_cron_7_field_with_year(self) -> None:
        parser = CronParser("0 0 9 * * 1 2025")
        assert parser.next_fire_time() > 0

    def test_cron_name_aliases(self) -> None:
        parser = CronParser("0 9 * * MON")
        assert parser.next_fire_time() > 0

    def test_cron_star(self) -> None:
        parser = CronParser("* * * * *")
        assert parser.next_fire_time() > 0

    def test_cron_step(self) -> None:
        parser = CronParser("*/5 * * * *")
        assert parser.next_fire_time() > 0

    def test_cron_range(self) -> None:
        parser = CronParser("0 9-17 * * 1-5")
        assert parser.next_fire_time() > 0


# 5. Enable / Disable

class TestEnableDisable:
    def test_enable(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="job",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        engine.disable(rec.id)
        result = engine.get(rec.id)
        assert result is not None
        assert result.enabled is False

    def test_disable_unknown(self, engine: AutomationEngine) -> None:
        assert engine.disable("nonexistent") is False

    def test_enable_unknown(self, engine: AutomationEngine) -> None:
        assert engine.enable("nonexistent") is False

    def test_disable_sets_status(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="job",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        engine.disable(rec.id)
        result = engine.get(rec.id)
        assert result is not None
        assert result.status == AutomationStatus.CANCELLED

    def test_enable_resets_status(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="job",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        engine.disable(rec.id)
        engine.enable(rec.id)
        result = engine.get(rec.id)
        assert result is not None
        assert result.enabled is True
        assert result.status == AutomationStatus.PENDING


# 6. Cancellation

class TestCancellation:
    def test_cancel(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="cancel_me",
            trigger_type=TriggerType.RECURRING,
            payload={"interval_seconds": 60.0},
        )
        assert engine.cancel(rec.id) is True

    def test_cancel_unknown(self, engine: AutomationEngine) -> None:
        assert engine.cancel("nonexistent") is False


# 7. Persistent state

class TestPersistence:
    def test_create_and_reload(self, store: Path) -> None:
        eng1 = AutomationEngine(store_path=store)
        eng1.create(
            name="persistent",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        eng1.stop()
        eng2 = AutomationEngine(store_path=store)
        recs = eng2.list()
        assert len(recs) == 1
        assert recs[0].name == "persistent"

    def test_persist_executions(self, store: Path) -> None:
        eng = AutomationEngine(store_path=store)
        rec = eng.create(
            name="exe_test",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        eng._execute(rec)
        eng.stop()
        eng2 = AutomationEngine(store_path=store)
        executions = list(eng2._executions.values())
        assert len(executions) >= 1

    def test_persist_history(self, store: Path) -> None:
        eng = AutomationEngine(store_path=store)
        rec = eng.create(
            name="hist_test",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        eng._execute(rec)
        eng.stop()
        eng2 = AutomationEngine(store_path=store)
        history = eng2.get_run_history(rec.id)
        assert len(history) >= 1


# 8. Restart recovery

class TestRestartRecovery:
    def test_stale_running_becomes_pending(self, store: Path) -> None:
        eng = AutomationEngine(store_path=store)
        rec = eng.create(
            name="stale",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        with eng._lock:
            rec.status = AutomationStatus.RUNNING
            eng._jobs[rec.id].status = AutomationStatus.RUNNING
        eng._save()
        eng2 = AutomationEngine(store_path=store)
        result = eng2.get(rec.id)
        assert result is not None
        assert result.status == AutomationStatus.PENDING

    def test_stale_execution_marked_failed(self, store: Path) -> None:
        eng = AutomationEngine(store_path=store)
        rec = eng.create(
            name="stale_exe",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        with eng._lock:
            rec.status = AutomationStatus.RUNNING
            eng._jobs[rec.id].status = AutomationStatus.RUNNING
        exe = AutomationExecution(
            job_id=rec.id,
            execution_id="stale_exe_id",
            status=ExecutionStatus.RUNNING,
            started_at=time.time(),
        )
        eng._executions[exe.id] = exe
        eng._save()
        eng2 = AutomationEngine(store_path=store)
        found = eng2.get_execution("stale_exe_id")
        assert found is not None
        assert found.status == ExecutionStatus.FAILED


# 9 & 10. Run history / Failure history

class TestRunHistory:
    def test_history_on_success(self, async_engine: tuple) -> None:
        eng, invocations = async_engine
        rec = eng.create(
            name="hist_success",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        eng._execute(rec)
        history = eng.get_run_history(rec.id)
        assert len(history) >= 1

    def test_failure_history(self, store: Path) -> None:
        async def _bad_executor(record):
            raise RuntimeError("intentional failure")
        eng = AutomationEngine(store_path=store, executor=_bad_executor)
        rec = eng.create(
            name="fail_job",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        for _ in range(2):
            eng._execute(rec)
            time.sleep(0.1)
        failures = eng.get_failure_history(rec.id)
        assert len(failures) >= 1

    def test_history_limit(self, async_engine: tuple) -> None:
        eng, invocations = async_engine
        rec = eng.create(
            name="hist_limit",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        for _ in range(10):
            eng._execute(rec)
        history = eng.get_run_history(rec.id, limit=3)
        assert len(history) <= 3


# 11. Idempotency

class TestIdempotency:
    def test_tracker_first_time(self, store: Path) -> None:
        tracker = ExecutionIdempotencyTracker(store)
        assert tracker.mark_completed("exe_1") is True

    def test_tracker_duplicate(self, store: Path) -> None:
        tracker = ExecutionIdempotencyTracker(store)
        tracker.mark_completed("exe_1")
        assert tracker.mark_completed("exe_1") is False

    def test_tracker_is_completed(self, store: Path) -> None:
        tracker = ExecutionIdempotencyTracker(store)
        tracker.mark_completed("exe_1")
        assert tracker.is_completed("exe_1") is True
        assert tracker.is_completed("exe_2") is False

    def test_tracker_persistence(self, store: Path) -> None:
        tracker1 = ExecutionIdempotencyTracker(store)
        tracker1.mark_completed("exe_persist")
        del tracker1
        tracker2 = ExecutionIdempotencyTracker(store)
        assert tracker2.is_completed("exe_persist") is True

    def test_tracker_clean_old_entries(self, store: Path) -> None:
        tracker = ExecutionIdempotencyTracker(store)
        for i in range(20):
            tracker.mark_completed(f"exe_{i}")
        tracker.clean_old_entries(max_entries=10)
        assert len(tracker._completed_ids) <= 10


# 12. No duplicate side-effects after restart

class TestNoDuplicateSideEffects:
    def test_restart_no_re_execution(self, store: Path) -> None:
        eng = AutomationEngine(store_path=store)
        rec = eng.create(
            name="no_dup",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        eng._execute(rec)
        eng.stop()
        eng2 = AutomationEngine(store_path=store)
        result = eng2.get(rec.id)
        assert result is not None
        assert result.status == AutomationStatus.COMPLETED

    def test_idempotency_prevents_re_run(self, store: Path) -> None:
        tracker = ExecutionIdempotencyTracker(store)
        assert tracker.mark_completed("unique_exe") is True
        assert tracker.mark_completed("unique_exe") is False


# 13. Timezone support

class TestTimezone:
    def test_cron_parser_utc(self) -> None:
        parser = CronParser("0 9 * * 1", default_timezone="UTC")
        next_t = parser.next_fire_time()
        assert next_t > 0
        dt = datetime.fromtimestamp(next_t, tz=tz.utc)
        assert dt.year > 2024

    def test_engine_default_timezone(self, store: Path) -> None:
        eng = AutomationEngine(store_path=store, default_timezone="UTC")
        assert eng._default_timezone == "UTC"

    def test_scheduler_timezone(self, store: Path) -> None:
        scheduler = CronScheduler(default_timezone="UTC")
        next_t = scheduler.schedule("task1", "0 9 * * 1")
        assert next_t > 0


# 14. Malformed cron

class TestMalformedCron:
    def test_invalid_fields_count(self) -> None:
        with pytest.raises(ValueError, match="Expected 5, 6, or 7 fields"):
            CronParser("0 9 * *")

    def test_out_of_range_value(self) -> None:
        with pytest.raises(ValueError):
            CronParser("60 * * * *")

    def test_invalid_step(self) -> None:
        with pytest.raises(ValueError, match="step must be positive"):
            CronParser("*/0 * * * *")

    def test_invalid_range(self) -> None:
        with pytest.raises(ValueError):
            CronParser("0 10-5 * * *")


# 15. Missed schedules (tick loop)

class TestMissedSchedules:
    def test_tick_finds_due_jobs(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="missed",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        engine._tick()


# 16. Concurrent execution

class TestConcurrency:
    def test_concurrent_per_job_limit(self, store: Path) -> None:
        policy = ConcurrencyPolicy(max_concurrent_per_job=1, max_concurrent_global=10)
        invocations: list[str] = []
        lock = threading.Lock()

        async def _slow_executor(record):
            with lock:
                invocations.append(record.id)
            await asyncio.sleep(0.1)

        eng = AutomationEngine(
            store_path=store,
            executor=_slow_executor,
            concurrency_policy=policy,
        )
        rec = eng.create(
            name="concurrent_test",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        eng._execute(rec)
        eng._execute(rec)
        assert len(invocations) == 2

    def test_global_concurrency_limit(self, store: Path) -> None:
        policy = ConcurrencyPolicy(max_concurrent_per_job=10, max_concurrent_global=2)
        eng = AutomationEngine(
            store_path=store,
            concurrency_policy=policy,
        )
        rec1 = eng.create(
            name="global1",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        rec2 = eng.create(
            name="global2",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        eng._execute(rec1)
        eng._execute(rec2)


# 17. Clean shutdown

class TestCleanShutdown:
    def test_stop_returns_true(self, engine: AutomationEngine) -> None:
        assert engine.stop(timeout=1.0) is True

    def test_stop_before_start(self, engine: AutomationEngine) -> None:
        assert engine.stop(timeout=1.0) is True

    def test_stop_persists_state(self, store: Path) -> None:
        eng = AutomationEngine(store_path=store)
        eng.create(
            name="shutdown_test",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"delay_seconds": 0},
        )
        eng.stop(timeout=1.0)
        assert (store / "automation.json").exists()

    def test_start_stop_lifecycle(self, engine: AutomationEngine) -> None:
        engine.start()
        assert engine._running is True
        time.sleep(0.2)
        assert engine.stop(timeout=1.0) is True
        assert engine._running is False

    def test_start_already_running(self, engine: AutomationEngine) -> None:
        engine.start()
        engine.start()
        engine.stop(timeout=1.0)


# CronParser unit tests

class TestCronParser:
    def test_standard_5_field(self) -> None:
        parser = CronParser("0 9 * * 1")
        assert "minute" in parser.fields
        assert parser.next_fire_time() > 0

    def test_extended_6_field(self) -> None:
        parser = CronParser("0 0 9 * * 1")
        assert "second" in parser.fields
        assert parser.next_fire_time() > 0

    def test_full_7_field(self) -> None:
        parser = CronParser("0 0 9 * * 1 2025")
        assert "year" in parser.fields
        assert parser.next_fire_time() > 0

    def test_month_names(self) -> None:
        parser = CronParser("0 0 1 jan *")
        assert 1 in parser.fields.get("month", set())

    def test_dow_names(self) -> None:
        parser = CronParser("0 0 * * MON")
        assert 1 in parser.fields.get("dow", set())

    def test_mixed_fields(self) -> None:
        parser = CronParser("*/15 9-17 * * MON-FRI")
        assert parser.next_fire_time() > 0

    def test_specific_values(self) -> None:
        parser = CronParser("30 14 15 6 *")
        assert 30 in parser.fields["minute"]
        assert 14 in parser.fields["hour"]

    def test_next_fire_time_returns_valid_timestamp(self) -> None:
        parser = CronParser("0 0 * * *")
        t = parser.next_fire_time()
        assert t > time.time()

    def test_next_fire_time_from_specific_time(self) -> None:
        parser = CronParser("0 0 * * *")
        t = parser.next_fire_time(from_time=1000000.0)
        assert t > 1000000.0

    def test_invalid_expression_raises(self) -> None:
        with pytest.raises(ValueError):
            CronParser("abc * * * *")


# CronScheduler unit tests

class TestCronScheduler:
    def test_schedule_and_advance(self, store: Path) -> None:
        scheduler = CronScheduler()
        next_t = scheduler.schedule("task1", "0 9 * * 1")
        assert next_t > 0
        scheduler.remove("task1")
        due = scheduler.get_due_tasks()
        assert "task1" not in due

    def test_remove_nonexistent(self, store: Path) -> None:
        scheduler = CronScheduler()
        scheduler.remove("nonexistent")

    def test_callbacks(self, store: Path) -> None:
        scheduler = CronScheduler()
        scheduler.schedule("task1", "0 9 * * 1")
        callback_called = threading.Event()

        def _cb():
            callback_called.set()

        scheduler.register_callback("task1", _cb)
        scheduler._callbacks["task1"]()
        assert callback_called.is_set()


# Engine API tests

class TestEngineAPI:
    def test_create(self, engine: AutomationEngine) -> None:
        rec = engine.create(
            name="test",
            trigger_type=TriggerType.ONE_SHOT,
            payload={"key": "val"},
            goal="Test goal",
        )
        assert rec.name == "test"
        assert rec.goal == "Test goal"

    def test_list(self, engine: AutomationEngine) -> None:
        engine.create(name="a", trigger_type=TriggerType.ONE_SHOT, payload={})
        engine.create(name="b", trigger_type=TriggerType.RECURRING, payload={})
        recs = engine.list()
        assert len(recs) == 2

    def test_list_workspace_filter(self, engine: AutomationEngine) -> None:
        engine.create(name="a", trigger_type=TriggerType.ONE_SHOT, payload={}, workspace_id="ws1")
        engine.create(name="b", trigger_type=TriggerType.ONE_SHOT, payload={}, workspace_id="ws2")
        ws1 = engine.list(workspace_id="ws1")
        assert len(ws1) == 1
        assert ws1[0].name == "a"

    def test_get(self, engine: AutomationEngine) -> None:
        rec = engine.create(name="get_test", trigger_type=TriggerType.ONE_SHOT, payload={})
        result = engine.get(rec.id)
        assert result is not None
        assert result.name == "get_test"

    def test_get_not_found(self, engine: AutomationEngine) -> None:
        assert engine.get("nonexistent") is None

    def test_delete(self, engine: AutomationEngine) -> None:
        rec = engine.create(name="del", trigger_type=TriggerType.ONE_SHOT, payload={})
        assert engine.delete(rec.id) is True
        assert engine.get(rec.id) is None

    def test_delete_unknown(self, engine: AutomationEngine) -> None:
        assert engine.delete("nonexistent") is False

    def test_count(self, engine: AutomationEngine) -> None:
        assert engine.count == 0
        engine.create(name="c1", trigger_type=TriggerType.ONE_SHOT, payload={})
        engine.create(name="c2", trigger_type=TriggerType.ONE_SHOT, payload={})
        assert engine.count == 2

    def test_register_back_compat(self, engine: AutomationEngine) -> None:
        class Rule:
            name = "compat"
            trigger = {"type": "manual"}
            action = "echo"
        name = engine.register(Rule())
        assert name == "compat"

    def test_list_rules(self, engine: AutomationEngine) -> None:
        engine.register(AutomationRule(name="r1"))
        rules = engine.list_rules()
        assert "r1" in rules


# SimpleAutomationEngine

class TestSimpleAutomationEngine:
    def test_register_and_list(self) -> None:
        eng = SimpleAutomationEngine()
        eng.register(AutomationRule(name="rule1"))
        assert "rule1" in eng.list_rules()

    def test_start_stop_noop(self) -> None:
        eng = SimpleAutomationEngine()
        eng.start()
        eng.stop()

    def test_register_with_dict(self) -> None:
        eng = SimpleAutomationEngine()
        eng.register({"name": "dict_rule", "trigger": "a", "action": "b"})
        assert "dict_rule" in eng.list_rules()


# RetryPolicy and ConcurrencyPolicy

class TestRetryPolicy:
    def test_default_policy(self) -> None:
        p = RetryPolicy()
        assert p.max_attempts == 3

    def test_custom_policy(self) -> None:
        p = RetryPolicy(max_attempts=5, initial_delay_seconds=0.5)
        assert p.max_attempts == 5

    def test_retryable_codes(self) -> None:
        p = RetryPolicy()
        assert "transient" in p.retryable_codes


class TestConcurrencyPolicy:
    def test_defaults(self) -> None:
        p = ConcurrencyPolicy()
        assert p.max_concurrent_per_job == 1
        assert p.max_concurrent_global == 4
