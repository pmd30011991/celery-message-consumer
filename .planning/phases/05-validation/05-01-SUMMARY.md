---
phase: 05-validation
plan: 01
subsystem: testing
tags: [pytest, celery, amqp, callbacks, error-handling, version-compat]

# Dependency graph
requires:
  - phase: 01-root-cause-fix
    provides: "_on_pool_success and _on_pool_error implementations in handlers.py"
  - phase: 03-reconnect-hardening
    provides: "bare try/except Exception in pool callbacks pattern"
provides:
  - "14-test suite validating all _on_pool_success and _on_pool_error callback branches"
  - "Celery 3.x (single-object) and 4.x/5.x (tuple) exc_info format validation"
  - "Bug fix: _on_pool_error now catches routing exceptions to prevent propagation"
affects: [future-phases, test-suite]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Direct method call testing: handler._on_pool_success(body, msg) without pool dispatch"
    - "patch.object(handler, 'retry') / patch.object(handler, 'archive') for routing isolation"
    - "caplog.at_level(logging.WARNING) for warning log verification"

key-files:
  created:
    - tests/test_callbacks.py
  modified:
    - event_consumer/handlers.py

key-decisions:
  - "Rule 1 auto-fix: _on_pool_error routing block wrapped in try/except Exception to prevent retry()/archive() errors from propagating out of the error callback"
  - "Tests use fresh venv /tmp/celery-test-venv as the original /tmp/celery-consumer-venv has a corrupted pytest install (empty pytest/__init__.py)"

patterns-established:
  - "Callback methods tested via direct invocation (not through pool dispatch) for deterministic unit tests"
  - "Both Celery exc_info formats (tuple and bare exception) always tested in parallel for version compat coverage"

requirements-completed: [TEST-03, TEST-04]

# Metrics
duration: 6min
completed: 2026-03-16
---

# Phase 5 Plan 01: Callback Unit Tests Summary

**14-test callback validation suite covering _on_pool_success/_on_pool_error all branches and Celery 3.x/4.x/5.x exc_info format compatibility, plus a bug fix for routing exception propagation**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-16T15:06:34Z
- **Completed:** 2026-03-16T15:12:20Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Created `tests/test_callbacks.py` with 14 tests across 3 test classes
- TestOnPoolSuccess: 4 tests validating ack, cleanup, and closed-channel resilience
- TestOnPoolError: 6 tests validating PermanentFailure archive, transient retry, exhausted-retries archive, requeue safety net, requeue-failure-no-crash, and cleanup-always-called
- TestCeleryVersionCompat: 4 tests validating Celery 3.x single-object and 4.x/5.x tuple exc_info formats for both transient and permanent failure cases
- Auto-fixed bug: `_on_pool_error` routing block did not catch exceptions from `retry()`/`archive()`, causing them to propagate out of the error callback
- Full suite: 47 passed, 2 skipped (integration tests)

## Task Commits

1. **Task 1: Create callback unit tests and version compat tests** - `faff39f` (feat)

## Files Created/Modified

- `/Users/duyphungminh/Documents/Cynopsis/celery-message-consumer/tests/test_callbacks.py` - 14 unit tests for _on_pool_success and _on_pool_error callback paths
- `/Users/duyphungminh/Documents/Cynopsis/celery-message-consumer/event_consumer/handlers.py` - Added try/except Exception in _on_pool_error routing block

## Decisions Made

- Used `/tmp/celery-test-venv` (fresh venv) instead of `/tmp/celery-consumer-venv` (broken pytest install) for test execution. The original venv has an empty `pytest/` directory with no `.py` files.
- Tests call `_on_pool_success` and `_on_pool_error` directly (no pool dispatch) — cleaner unit tests with deterministic control of exc_info values.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _on_pool_error routing block propagates exceptions from retry()/archive()**
- **Found during:** Task 1 (creating tests - tests test_requeue_safety_net and test_requeue_failure_no_crash failed)
- **Issue:** The `try/finally` in `_on_pool_error` uses a bare `finally` but no `except`. When `self.retry()` raises `RuntimeError`, the exception propagates out of `_on_pool_error` even though the `finally` block runs first. The `finally` block successfully calls `message.requeue()`, but the RuntimeError still escapes — causing the error callback itself to crash the pool greenlet.
- **Fix:** Added `except Exception: _logger.warning(...)` between the routing block and the `finally` clause, so exceptions from `retry()`/`archive()` are caught and logged rather than propagated.
- **Files modified:** `event_consumer/handlers.py`
- **Verification:** All 14 tests pass; full suite 47 passed.
- **Committed in:** `faff39f` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Fix is necessary for correctness — a crashing error callback defeats the purpose of the safety net. No scope creep.

## Issues Encountered

- `/tmp/celery-consumer-venv` has a corrupted pytest installation (empty `pytest/` and `_pytest/` directories — no source files, only empty subdirectories). Created fresh venv at `/tmp/celery-test-venv` with `pytest`, `six`, `django`, `celery`, `kombu` and installed the package in editable mode. Tests run cleanly from the new venv.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- TEST-03 and TEST-04 requirements are now validated with passing tests
- The _on_pool_error bug fix (routing exceptions swallowed instead of propagated) is live in production code
- No blockers for remaining validation plans in phase 05

## Self-Check: PASSED

- tests/test_callbacks.py: FOUND
- 05-01-SUMMARY.md: FOUND
- commit faff39f: FOUND

---
*Phase: 05-validation*
*Completed: 2026-03-16*
