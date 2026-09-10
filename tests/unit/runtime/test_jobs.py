from __future__ import annotations

from pathlib import Path

from runtime.jobs import JobEngine, JobState


def test_enqueue_is_idempotent(tmp_path: Path) -> None:
    engine = JobEngine(tmp_path / "jobs.sqlite3")
    first = engine.enqueue(
        type="shell",
        payload={"argv": ["echo", "ok"]},
        idempotency_key="once",
        session_id="s1",
    )
    second = engine.enqueue(
        type="shell",
        payload={"argv": ["echo", "again"]},
        idempotency_key="once",
        session_id="s1",
    )
    assert first.job_id == second.job_id
    assert second.payload["argv"] == ["echo", "ok"]
    engine.close()


def test_claim_complete_and_no_double_complete(tmp_path: Path) -> None:
    engine = JobEngine(tmp_path / "jobs.sqlite3")
    engine.enqueue(type="demo", payload={"n": 1}, idempotency_key="k1")
    claimed = engine.claim()
    assert claimed is not None
    assert claimed.state == JobState.RUNNING
    assert claimed.attempt == 1
    assert engine.claim() is None
    done = engine.complete(claimed.job_id, result_ref="out:1")
    again = engine.complete(claimed.job_id, result_ref="out:2")
    assert done.state == JobState.COMPLETED
    assert again.result_ref == "out:1"
    engine.close()


def test_crash_recovery_retries_then_fails(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    engine = JobEngine(path)
    job = engine.enqueue(type="demo", payload={}, idempotency_key="crash", max_attempts=2)
    claimed = engine.claim()
    assert claimed is not None
    engine.close()

    restarted = JobEngine(path)
    recovered = restarted.recover_running()
    assert len(recovered) == 1
    assert recovered[0].state == JobState.RETRYING
    assert recovered[0].job_id == job.job_id
    claimed_again = restarted.claim()
    assert claimed_again is not None
    assert claimed_again.attempt == 2
    restarted.close()

    third = JobEngine(path)
    third.recover_running()
    leftover = third.get(job.job_id)
    assert leftover is not None
    assert leftover.state == JobState.FAILED
    assert leftover.error == "recovered_after_crash"
    third.close()


def test_cancel_and_pause(tmp_path: Path) -> None:
    engine = JobEngine(tmp_path / "jobs.sqlite3")
    job = engine.enqueue(type="demo", payload={}, idempotency_key="c1")
    paused = engine.pause(job.job_id)
    assert paused.state == JobState.PAUSED
    assert engine.claim() is None
    engine.resume(job.job_id)
    claimed = engine.claim()
    assert claimed is not None
    cancelled = engine.cancel(claimed.job_id, reason="user")
    assert cancelled.state == JobState.CANCELLED
    assert cancelled.cancellation == "user"
    engine.close()


def test_completed_job_is_not_reexecuted_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    engine = JobEngine(path)
    job = engine.enqueue(type="agent_task", payload={"goal": "once"}, idempotency_key="agent_task:once")
    claimed = engine.claim(job_type="agent_task")
    assert claimed is not None
    engine.complete(claimed.job_id, result_ref="done")
    engine.close()

    restarted = JobEngine(path)
    restarted.recover_running()
    leftover = restarted.get(job.job_id)
    assert leftover is not None
    assert leftover.state == JobState.COMPLETED
    assert restarted.claim(job_type="agent_task") is None
    again = restarted.enqueue(
        type="agent_task",
        payload={"goal": "again"},
        idempotency_key="agent_task:once",
    )
    assert again.job_id == job.job_id
    assert again.state == JobState.COMPLETED
    restarted.close()


def test_claim_filters_by_job_type(tmp_path: Path) -> None:
    engine = JobEngine(tmp_path / "jobs.sqlite3")
    engine.enqueue(type="automation_fire", payload={}, idempotency_key="auto")
    engine.enqueue(type="agent_task", payload={}, idempotency_key="agent")
    claimed = engine.claim(job_type="agent_task")
    assert claimed is not None
    assert claimed.type == "agent_task"
    assert engine.claim(job_type="agent_task") is None
    other = engine.claim(job_type="automation_fire")
    assert other is not None
    assert other.type == "automation_fire"
    engine.close()


def test_running_recovered_once_then_not_duplicated(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    engine = JobEngine(path)
    job = engine.enqueue(type="agent_task", payload={}, idempotency_key="crash-once", max_attempts=3)
    claimed = engine.claim(job_type="agent_task")
    assert claimed is not None
    engine.close()

    restarted = JobEngine(path)
    recovered = restarted.recover_running()
    assert len(recovered) == 1
    assert recovered[0].job_id == job.job_id
    assert recovered[0].state == JobState.RETRYING
    second = restarted.recover_running()
    assert second == []
    restarted.close()
