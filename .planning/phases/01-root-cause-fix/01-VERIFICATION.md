---
phase: 01-root-cause-fix
verified: 2026-03-11T10:00:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 1: Root Cause Fix — Verification Report

**Phase Goal:** Message handlers execute in the Celery pool greenlet, not on the listener thread, and all post-execution side effects (ack, retry, archive, Django cleanup) run in pool callbacks.
**Verified:** 2026-03-11T10:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A message sent to RabbitMQ is processed by a pool greenlet — listener thread returns to `drain_events()` without waiting for handler completion | VERIFIED | `__call__` calls `self.pool.apply_async(target=self.func, ...)` and returns immediately; `handler.func.called == False` after `__call__` returns; test `test_listener_returns_immediately` passes |
| 2 | `message.ack()` is called only after the handler function completes successfully inside the pool greenlet | VERIFIED | `message.ack()` is in `_on_pool_success` only; `__call__` contains no inline ack; test `test_ack_in_success_callback` confirms ack not called until callback fires |
| 3 | A handler that raises `PermanentFailure` causes the message to be archived via `_on_pool_error` callback, not inline code | VERIFIED | `_on_pool_error` checks `isinstance(exc_value, PermanentFailure)` and routes to `self.archive()`; test `test_permanent_failure_archives` passes |
| 4 | A handler that raises a transient exception causes retry (or archive when retries exhausted) via error callback — same semantics as current inline path | VERIFIED | `_on_pool_error` routes to `self.retry()` when `retry_count < MAX_RETRIES`, to `self.archive()` when exhausted; tests `test_transient_exception_retries` and `test_exhausted_retries_archives` pass |
| 5 | Existing `@message_handler` decorator and `AMQPRetryConsumerStep` registration interface work without any changes to user code | VERIFIED | `message_handler` decorator signature and `REGISTRY` logic unchanged; `test_decorator_api_unchanged` passes |

**Score:** 5/5 success criteria verified

---

### Required Artifacts (from 01-02-PLAN.md must_haves)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `event_consumer/handlers.py` | Fixed pool dispatch with `_on_pool_success` | VERIFIED | Method exists at line 330; substantive implementation (try/except/finally, calls `message.ack()`, calls `_django_cleanup()`) |
| `event_consumer/handlers.py` | Error callback with retry/archive/requeue logic via `_on_pool_error` | VERIFIED | Method exists at line 344; substantive implementation (exc_info unpack, PermanentFailure branch, retry exhaustion branch, safety-net requeue in finally) |
| `event_consumer/handlers.py` | Django cleanup helper via `_django_cleanup` | VERIFIED | Method exists at line 325; guards on `settings.USE_DJANGO` before sending signal |
| `event_consumer/handlers.py` | Inline fallback via `_inline_dispatch` | VERIFIED | Method exists at line 404; substantive try/except/else/finally covering all error paths |
| `tests/__init__.py` | Package marker for test discovery | VERIFIED | File exists |
| `tests/conftest.py` | Shared fixtures: mock_pool, mock_message, mock_channel, handler, settings_patch | VERIFIED | 159 lines; all 5 fixtures present; mock_pool._last_call and _all_calls capture; ack side-effect flips acknowledged; autouse settings_patch |
| `tests/test_handlers.py` | Unit tests for all POOL-* and ACK-* requirements | VERIFIED | 418 lines; 11 test functions; all 11 pass against the fixed implementation |

---

### Key Link Verification (from 01-02-PLAN.md must_haves.key_links)

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `AMQPRetryHandler.__call__` | `self.pool.apply_async` | `target=self.func, args=(body,), callback=, error_callback=` | WIRED | Line 494: `self.pool.apply_async(` with `target=self.func` on line 495, `args=(body,)` on line 496 |
| `AMQPRetryHandler.__call__` | `_on_pool_success` | `callback=lambda` with default-arg capture | WIRED | Line 497: `callback=lambda result, b=body, m=message: (self._on_pool_success(b, m))` |
| `AMQPRetryHandler.__call__` | `_on_pool_error` | `error_callback=lambda` with default-arg capture | WIRED | Line 500: `error_callback=lambda exc_info, b=body, m=message, rc=retry_count: (self._on_pool_error(b, m, exc_info, rc))` |
| `AMQPRetryConsumerStep.get_handlers` | `AMQPRetryHandler.__init__` | `pool=self.pool` parameter | WIRED | Line 204: `pool=self.pool,  # NEW: wire pool for async dispatch` |
| `tests/conftest.py` | `event_consumer/handlers.py` | imports `AMQPRetryHandler` | WIRED | Line 139 in conftest: `from event_consumer.handlers import AMQPRetryHandler` |
| `tests/test_handlers.py` | `tests/conftest.py` | pytest fixtures | WIRED | Test functions accept `handler`, `mock_pool`, `mock_message` fixture parameters; all resolved by conftest |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| POOL-01 | 01-01, 01-02 | `apply_async(target, args)` correct signature | SATISFIED | `target=self.func, args=(body,)` at handler.py:494-496; `test_apply_async_dispatches_callable` passes |
| POOL-02 | 01-01, 01-02 | `AMQPRetryHandler` receives pool from `AMQPRetryConsumerStep` | SATISFIED | `pool=self.pool` at handler.py:204; `__init__` accepts `pool=None` at line 228; `self.pool = pool` at line 237; `test_handler_receives_pool_from_get_handlers` passes |
| POOL-03 | 01-01, 01-02 | Listener thread returns immediately after dispatch | SATISFIED | `__call__` returns after `apply_async` with no blocking; comment "POOL-03: Listener thread returns here immediately" at line 504; `test_listener_returns_immediately` passes |
| POOL-05 | 01-01, 01-02 | `@message_handler` decorator API unchanged | SATISFIED | `message_handler` function body and signature unchanged; `test_decorator_api_unchanged` passes |
| ACK-01 | 01-01, 01-02 | Messages acked only after successful handler completion in pool | SATISFIED | `message.ack()` exists only in `_on_pool_success` (line 333) and `retry()`/`archive()` methods; removed from `__call__`; `test_ack_in_success_callback` passes |
| ACK-02 | 01-01, 01-02 | Failed messages trigger retry or archive via pool callbacks | SATISFIED | `_on_pool_error` routes PermanentFailure to archive, transient to retry/archive-on-exhaustion; tests `test_permanent_failure_archives`, `test_transient_exception_retries`, `test_exhausted_retries_archives` all pass |
| ACK-03 | 01-01, 01-02 | Unacknowledged messages requeued on handler crash | SATISFIED | `_on_pool_error` finally block at lines 395-402 checks `not message.acknowledged` and calls `message.requeue()`; `test_unacked_requeued_on_error` passes |
| ACK-04 | 01-01, 01-02 | Lambda captures use default-argument binding | SATISFIED | `b=body, m=message` in callback lambda (line 497); `b=body, m=message, rc=retry_count` in error_callback lambda (line 500); `test_lambda_capture_correct_message` passes |
| ACK-05 | 01-01, 01-02 | `retry_count` captured from headers before pool dispatch | SATISFIED | `retry_count = self.retry_count(message)` at line 480 with comment "ACK-05: capture BEFORE dispatch"; `test_retry_count_captured_before_dispatch` passes |

**Orphaned requirements check:** REQUIREMENTS.md traceability table maps POOL-01/02/03/05 and ACK-01/02/03/04/05 to Phase 1. All 9 IDs are claimed by both plan files. No orphaned requirements.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | No anti-patterns found |

Scanned `event_consumer/handlers.py` and `tests/test_handlers.py` for TODO/FIXME/placeholder comments, empty implementations (`return null`, `return {}`, `=> {}`), and stub patterns. None found.

---

### Commit Verification

All task commits documented in SUMMARY files are present in git history:

| Commit | Description |
|--------|-------------|
| `8e1507b` | test(01-01): create test infrastructure with shared fixtures |
| `917f14b` | test(01-01): write failing unit tests for all Phase 1 requirements |
| `04d0062` | feat(01-02): add pool parameter wiring and helper methods |
| `26a063b` | feat(01-02): fix __call__ to use async pool dispatch with callbacks |

---

### Human Verification Required

None. All behavioral contracts are verifiable via the unit test suite. The tests exercise the full dispatch path including callback invocation, lambda capture, retry/archive routing, and safety-net requeue — without requiring a live broker.

One item is out of scope for Phase 1 and deferred per REQUIREMENTS.md:

- **POOL-04** (prefork pool detection and inline fallback with warning log) is mapped to Phase 3. An `_inline_dispatch` fallback exists for the `pool=None` case but does not yet detect or warn on prefork pools specifically. This is not a gap for Phase 1.

---

### Summary

Phase 1 goal is fully achieved. The root-cause bug (`apply_async(self.func(body))` — calling the handler synchronously on the listener thread) is replaced with the correct async dispatch pattern. All 9 requirements (POOL-01/02/03/05, ACK-01/02/03/04/05) are implemented and covered by passing tests. The listener thread is now free to return to `drain_events()` immediately after dispatching, and all post-execution side effects (ack, retry, archive, Django cleanup, safety-net requeue) run exclusively in pool callbacks.

---

_Verified: 2026-03-11T10:00:00Z_
_Verifier: Claude (gsd-verifier)_
