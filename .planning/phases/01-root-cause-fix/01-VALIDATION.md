---
phase: 1
slug: root-cause-fix
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-11
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | none — Wave 0 installs |
| **Quick run command** | `pytest tests/test_handlers.py -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_handlers.py -x -q`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | POOL-01 | unit | `pytest tests/test_handlers.py::test_apply_async_dispatches_callable -x` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 0 | POOL-02 | unit | `pytest tests/test_handlers.py::test_handler_receives_pool -x` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 0 | POOL-03 | unit | `pytest tests/test_handlers.py::test_listener_returns_immediately -x` | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 0 | POOL-05 | unit | `pytest tests/test_handlers.py::test_decorator_api_unchanged -x` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 0 | ACK-01 | unit | `pytest tests/test_handlers.py::test_ack_in_success_callback -x` | ❌ W0 | ⬜ pending |
| 1-01-06 | 01 | 0 | ACK-02 | unit | `pytest tests/test_handlers.py::test_permanent_failure_archives -x` | ❌ W0 | ⬜ pending |
| 1-01-07 | 01 | 0 | ACK-02 | unit | `pytest tests/test_handlers.py::test_transient_exception_retries -x` | ❌ W0 | ⬜ pending |
| 1-01-08 | 01 | 0 | ACK-02 | unit | `pytest tests/test_handlers.py::test_exhausted_retries_archives -x` | ❌ W0 | ⬜ pending |
| 1-01-09 | 01 | 0 | ACK-03 | unit | `pytest tests/test_handlers.py::test_unacked_requeued_on_error -x` | ❌ W0 | ⬜ pending |
| 1-01-10 | 01 | 0 | ACK-04 | unit | `pytest tests/test_handlers.py::test_lambda_capture_correct_message -x` | ❌ W0 | ⬜ pending |
| 1-01-11 | 01 | 0 | ACK-05 | unit | `pytest tests/test_handlers.py::test_retry_count_captured_before_dispatch -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/__init__.py` — package marker
- [ ] `tests/test_handlers.py` — unit test stubs for all POOL-* and ACK-* requirements
- [ ] `tests/conftest.py` — shared fixtures: mock pool, mock message, mock channel

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
