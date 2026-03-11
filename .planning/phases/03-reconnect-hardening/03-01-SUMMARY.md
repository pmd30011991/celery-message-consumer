---
phase: 03-reconnect-hardening
plan: "01"
subsystem: event_consumer
tags: [reconnect, lifecycle, backpressure, pool, tdd]

dependency_graph:
  requires:
    - 01-01 (pool dispatch via apply_async)
    - 02-01 (pool-derived prefetch_count)
  provides:
    - Stale-free handler list after reconnect (_close resets self.handlers)
    - Closed-channel guard in pool callbacks
    - Prefork pool detection with inline fallback
  affects:
    - event_consumer/handlers.py (AMQPRetryConsumerStep._close, start; AMQPRetryHandler._on_pool_error, _on_pool_success)

tech_stack:
  added: []
  patterns:
    - "try/except Exception in pool callbacks — bare catch, not kombu.ignore_errors (no conn ref available in callback scope)"
    - "isinstance(pool, AsynPool) with ImportError guard — reliable prefork detection across Celery versions"
    - "self.handlers = [] as last statement in _close() — defensive cleanup ensures clean restart state"

key_files:
  created:
    - tests/test_reconnect.py
  modified:
    - event_consumer/handlers.py

decisions:
  - "self.handlers = [] placed as final statement in _close(), not at start of start() — ensures no stale state window between stop() and start()"
  - "pool_limit reset to None alongside self.pool = None in POOL-04 guard — prevents prefork pool limit leaking into prefetch_count resolution"
  - "bare try/except Exception in pool callbacks (not kombu.ignore_errors) — ignore_errors requires a live conn ref unavailable in pool callback scope"
  - "_logger.critical for successful requeue moved to else clause — only logs when requeue actually succeeds, preventing false positives on closed-channel failures"

metrics:
  duration_seconds: 119
  completed_date: "2026-03-11"
  tasks_completed: 2
  files_modified: 2
  tests_added: 11
  tests_total: 27
---

# Phase 03 Plan 01: Reconnect Hardening Summary

**One-liner:** Three surgical fixes to AMQP reconnect lifecycle: handler list cleared on close (CONN-01), requeue guarded against closed-channel exceptions in pool error callback (CONN-02), and AsynPool prefork detection with inline fallback (POOL-04).

## What Was Built

### CONN-01: Handler List Reset in `_close()` (event_consumer/handlers.py line 216)

Added `self.handlers = []` as the final statement in `AMQPRetryConsumerStep._close()`. Without this, a partial-cleanup scenario (where `stop()` raises mid-iteration) could leave stale handler objects referencing closed channels between `stop()` and the next `start()` after reconnect. The fix is defensive — `start()` already reassigns `self.handlers`, but the one-line reset ensures zero stale state window.

### CONN-02: Closed-Channel Guard in `_on_pool_error` Finally Block (line 424-432)

Wrapped `message.requeue()` in the `finally` block of `_on_pool_error` with `try/except Exception`. When a pool greenlet completes after a connection drop, the callback fires against the now-closed channel. Previously, `message.requeue()` would raise an `amqp.exceptions.AMQPConnectionError` (or similar) as an unhandled exception. Now the failure is caught and logged as a warning. The `_logger.critical` for successful requeue moved to the `else` clause.

Also updated `_on_pool_success` warning message to include "(channel likely closed by reconnect)" for consistency.

### POOL-04: Prefork Pool Guard in `start()` (lines 173-183)

Added an `isinstance(self.pool, AsynPool)` check after `self.pool = c.pool`. If the pool is AsynPool (prefork), logs a warning and sets `self.pool = None` (and `pool_limit = None`) to trigger the existing `_inline_dispatch` fallback. The check is wrapped in `try/except ImportError` for builds where asynpool is not present.

## Tests Added (`tests/test_reconnect.py` — 11 tests)

| Test | Requirement |
|------|-------------|
| `TestCloseResetsHandlers::test_close_resets_handlers` | CONN-01 |
| `TestCloseResetsHandlers::test_close_resets_handlers_after_cancel` | CONN-01 |
| `TestRestartNoStaleHandlers::test_restart_no_stale_handlers` | CONN-01/CONN-03 |
| `TestOnPoolSuccessClosedChannel::test_on_pool_success_closed_channel` | CONN-02 |
| `TestOnPoolSuccessClosedChannel::test_on_pool_success_closed_channel_calls_django_cleanup` | CONN-02 |
| `TestOnPoolErrorClosedChannelRequeue::test_on_pool_error_closed_channel_requeue` | CONN-02 |
| `TestOnPoolErrorClosedChannelRequeue::test_on_pool_error_requeue_failure_logs_warning` | CONN-02 |
| `TestPreforkGuardSetsPoolNone::test_prefork_guard_sets_pool_none` | POOL-04 |
| `TestPreforkGuardSetsPoolNone::test_prefork_guard_logs_warning` | POOL-04 |
| `TestPreforkGuardInlineFallback::test_prefork_guard_inline_fallback` | POOL-04 |
| `TestBlueprintRestartCleanState::test_blueprint_restart_clean_state` | CONN-03 |

## Deviations from Plan

None — plan executed exactly as written. The test count is 11 (plan specified minimum 7); the extras are additional coverage tests within the same requirement groups (CONN-01 cancel variant, CONN-02 cleanup assertion, POOL-04 warning log assertion).

## Verification Results

```
/tmp/celery-consumer-venv/bin/pytest tests/test_reconnect.py -v   → 11/11 PASSED
/tmp/celery-consumer-venv/bin/pytest tests/ -x -q                 → 27/27 PASSED
grep self.handlers = []  handlers.py                              → line 216 (CONN-01)
grep AsynPool            handlers.py                              → lines 173, 176, 177 (POOL-04)
grep Could not requeue   handlers.py                              → line 431 (CONN-02)
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `363a2e3` | `test` | RED — 11 failing reconnect hardening tests |
| `17d35ec` | `feat` | GREEN — CONN-01, CONN-02, POOL-04 production fixes |

## Self-Check: PASSED

- [x] `tests/test_reconnect.py` exists — FOUND
- [x] `event_consumer/handlers.py` modified — FOUND
- [x] Commit `363a2e3` exists — FOUND
- [x] Commit `17d35ec` exists — FOUND
- [x] `self.handlers = []` in `_close()` — FOUND (line 216)
- [x] `AsynPool` isinstance guard in `start()` — FOUND (line 177)
- [x] `Could not requeue` guard in `_on_pool_error` — FOUND (line 431)
- [x] 27 tests pass, 0 failures — CONFIRMED
