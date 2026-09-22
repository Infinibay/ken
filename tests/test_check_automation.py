"""Real check execution behind edit hooks; delivery is bounded and deduplicated."""

import threading

import pytest

from ken.checks.automation import Scheduler, edited_paths, resume
from ken.checks.service import check
from ken.daemon.server import DaemonState, _record_tool_post
from tests.test_checks import contract as contract, enable, BAD


def test_edits_coalesce_and_success_is_not_repeated(contract):
    root, _ = contract
    enable(root, automatic=True)
    done = threading.Event()
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        result = check(*args, **kwargs)
        done.set()
        return result

    scheduler = Scheduler(root, delay=0.1, runner=run)
    try:
        scheduler.enqueue("a", ["src/store.py"])
        scheduler.enqueue("a", ["src/store.py", "src/another.py"])
        assert done.wait(5)
        # The runner signals before publication; joining the timer only waits
        # for this bounded background job to publish its result.
        wait_idle(scheduler)
        assert len(calls) == 1
        assert calls[0]["touched"] == ["src/another.py", "src/store.py"]
        assert "storage.return-id: pass" in scheduler.drain("a")
        assert scheduler.drain("a") == ""
        done.clear()
        scheduler.enqueue("a", ["src/store.py"])
        assert done.wait(5)
        wait_idle(scheduler)
        assert scheduler.drain("a") == ""
        (root / "src/store.py").write_text(BAD)
        done.clear()
        scheduler.enqueue("a", ["src/store.py"])
        assert done.wait(5)
        wait_idle(scheduler)
        notice = scheduler.drain("a")
        assert "fail" in notice and "regression" in notice
    finally:
        scheduler.close()


def wait_idle(scheduler):
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with scheduler.lock:
            if not scheduler.running and not scheduler.pending:
                return
        time.sleep(0.01)
    pytest.fail("check worker did not finish")


def test_drafts_and_non_automatic_rules_never_run_on_edits(contract):
    root, _ = contract
    scheduler = Scheduler(root, runner=lambda *a, **k: pytest.fail("must not run"))
    try:
        scheduler.enqueue("a", ["src/store.py"])
        assert not scheduler.pending
        enable(root)
        scheduler.enqueue("a", ["src/store.py"])
        assert not scheduler.pending
    finally:
        scheduler.close()


def test_actual_daemon_post_event_schedules_and_failed_edit_does_not(contract):
    root, _ = contract
    enable(root, automatic=True)
    state = DaemonState(root, "fixture-token")
    state.session_start("fixture")
    done = threading.Event()

    def run(*args, **kwargs):
        result = check(*args, **kwargs)
        done.set()
        return result

    state.contract_checks = Scheduler(root, delay=0.01, runner=run)
    try:
        payload = {
            "session_id": "fixture",
            "tool": "Edit",
            "input": {"file_path": "src/store.py"},
        }
        _record_tool_post(state, payload | {"success": False})
        assert not state.contract_checks.pending
        (root / "src/store.py").write_text(BAD)
        _record_tool_post(state, payload | {"success": True})
        assert done.wait(5)
        wait_idle(state.contract_checks)
        assert "fail" in state.contract_checks.drain("fixture")
        assert "input validity: unchanged" in resume(root)
        (root / "src/new.py").write_text("x = 1")
        assert "input validity: stale" in resume(root)
    finally:
        state.contract_checks.close()
        state.conn.close()


def test_patch_collects_all_paths_and_ignores_outside_workspace(contract):
    root, _ = contract
    patch = (
        "*** Update File: src/a.py\n*** Add File: src/b.py\n*** Delete File: src/c.py\n"
    )
    assert edited_paths(root, patch, "src/a.py") == ["src/a.py", "src/b.py", "src/c.py"]
    assert edited_paths(root, {"patch": patch}, "/outside/file.py") == [
        "src/a.py",
        "src/b.py",
        "src/c.py",
    ]


def test_shutdown_cancels_pending_work(contract):
    root, _ = contract
    enable(root, automatic=True)
    scheduler = Scheduler(
        root, delay=1, runner=lambda *a, **kw: pytest.fail("closed worker ran")
    )
    scheduler.enqueue("a", ["src/store.py"])
    scheduler.close()
    assert scheduler.pending == {}
    scheduler.enqueue("a", ["src/store.py"])
    assert scheduler.pending == {}
