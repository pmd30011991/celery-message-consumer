---
phase: 04-heartbeat-safety-net
plan: 01
subsystem: infra
tags: [eventlet, gevent, greenlet, amqp, heartbeat, concurrency]

# Dependency graph
requires:
  - phase: 03-reconnect-hardening
    provides: "_close() cleanup pattern (self.handlers = []), stale-ref prevention"
provides:
  - "_heartbeat_loop module-level function: sleeps interval/2 then calls connection.heartbeat_tick()"
  - "_spawn/_sleep module-level refs with eventlet->gevent->None fallback"
  - "AMQPRetryConsumerStep.__init__ initializes self._heartbeat_greenlet = None"
  - "AMQPRetryConsumerStep.start() spawns heartbeat greenlet when connection.heartbeat is truthy"
  - "AMQPRetryConsumerStep._close() kills and clears heartbeat greenlet before channel teardown"
  - "tests/test_heartbeat.py with 6 tests covering BEAT-01 and BEAT-02"
affects: [05-integration-tests]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_spawn/_sleep module-level indirection for testable concurrency primitives"
    - "try/except ImportError chain: eventlet -> gevent -> None (null-spawn fallback)"
    - "_heartbeat_loop as module-level function (not a method) — no self reference, pure inputs"
    - "greenlet lifecycle: spawn in start(), kill in _close() before channel teardown"

key-files:
  created:
    - tests/test_heartbeat.py
  modified:
    - event_consumer/handlers.py

key-decisions:
  - "_spawn/_sleep module-level: testable without monkeypatching entire libraries"
  - "eventlet->gevent->None fallback order matches existing Celery pool preference"
  - "Spawn guard: `if c.connection.heartbeat and _spawn is not None` — skip when neither heartbeat configured nor concurrency library available"
  - "_StopLoop BaseException sentinel in tests: stop heartbeat loop after one iteration without greenlet library dependency"
  - "6 test functions (plan required 5 minimum): added test_no_heartbeat_greenlet_when_heartbeat_none for full coverage"

patterns-established:
  - "Heartbeat greenlet: module-level function with connection + interval args, no self reference"
  - "Greenlet teardown: kill before channel close in _close(), use getattr guard for AttributeError safety"

requirements-completed: [BEAT-01, BEAT-02]

# Metrics
duration: 4min
completed: 2026-03-12
---

# Phase 04 Plan 01: Heartbeat Safety-Net Greenlet Summary

**Dedicated heartbeat greenlet using _spawn/_sleep module-level indirection (eventlet->gevent->None fallback) that calls connection.heartbeat_tick() at interval/2 cadence, independent of the listener loop**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-12T09:10:52Z
- **Completed:** 2026-03-12T09:14:49Z
- **Tasks:** 2 (RED + GREEN/REFACTOR)
- **Files modified:** 2

## Accomplishments
- Implemented `_heartbeat_loop` as a module-level function (pure inputs: connection + interval)
- Added `_spawn`/`_sleep` module-level references with eventlet->gevent->None fallback for testability
- Wired greenlet spawn into `start()` guarded by `c.connection.heartbeat and _spawn is not None`
- Wired greenlet kill into `_close()` before channel teardown, preventing leaked greenlets on reconnect
- Created 6 TDD tests (BEAT-01 + BEAT-02), all passing; no regressions in existing 27 tests

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — Write failing tests for heartbeat greenlet** - `ea50989` (test)
2. **Task 2: GREEN + REFACTOR — Implement heartbeat greenlet** - `77d10db` (feat)

_Note: TDD tasks — RED committed first (5 failures), GREEN implemented to pass all tests_

## Files Created/Modified
- `tests/test_heartbeat.py` — 6 tests covering BEAT-01 (spawn/no-spawn, tick cadence) and BEAT-02 (kill on close, no-error before start)
- `event_consumer/handlers.py` — Added `_spawn`/`_sleep` module refs, `_heartbeat_loop` function, `self._heartbeat_greenlet = None` in `__init__`, spawn in `start()`, kill in `_close()`

## Decisions Made
- **_spawn/_sleep module-level indirection:** Allows `patch('event_consumer.handlers._spawn', ...)` in tests without monkeypatching the entire eventlet/gevent library. This is cleaner and avoids side effects on other imports.
- **eventlet->gevent->None fallback order:** Matches Celery's existing pool preference. `_spawn = None` means no greenlet is created if neither library is available — safe degradation.
- **_StopLoop BaseException in tests:** Neither eventlet nor gevent is installed in the test venv. Used a custom `BaseException` subclass to terminate the heartbeat loop after one full iteration (sleep -> tick -> sleep raises _StopLoop) to verify `heartbeat_tick()` is actually called.
- **6 tests instead of 5:** Added `test_no_heartbeat_greenlet_when_heartbeat_none` to cover the `None` case explicitly alongside the `0` case.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_heartbeat_tick_called loop termination logic**
- **Found during:** Task 2 (GREEN — running tests after implementation)
- **Issue:** Test raised `_StopLoop` on the FIRST `_sleep` call, before `heartbeat_tick()` was called. The loop is `sleep -> tick -> sleep -> ...` so the tick was never reached, causing assertion failure.
- **Fix:** Changed `if len(sleep_calls) >= 1` to `if len(sleep_calls) >= 2` so `_StopLoop` is raised on the second sleep call (after one complete tick iteration).
- **Files modified:** tests/test_heartbeat.py
- **Verification:** `heartbeat_tick.assert_called()` passes; all 33 tests green.
- **Committed in:** `77d10db` (Task 2 commit)

**2. [Rule 3 - Blocking] Replaced `from greenlet import GreenletExit` with custom sentinel**
- **Found during:** Task 1 (RED — test collection)
- **Issue:** `greenlet` module not installed in test venv (`/tmp/celery-consumer-venv`). Import error prevented test collection.
- **Fix:** Defined `_StopLoop(BaseException)` directly in the test file as a drop-in sentinel to terminate the loop.
- **Files modified:** tests/test_heartbeat.py
- **Verification:** Tests collected successfully; RED phase confirmed with 5 failures.
- **Committed in:** `ea50989` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both auto-fixes were necessary for the test environment. No scope creep. Production code is unchanged from the plan spec.

## Issues Encountered
- `greenlet` and `eventlet` and `gevent` are not installed in the test venv. The implementation correctly falls back to `_spawn = None`, and tests use `patch('event_consumer.handlers._spawn', ...)` to inject a mock greenlet without needing real concurrency libraries.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Heartbeat safety-net greenlet fully implemented and tested
- Phase 05 (integration tests) can now test the full heartbeat behavior end-to-end
- Concern from STATE.md: "Confirm heartbeat greenlet does not double-tick with Celery's own heartbeat machinery" — Phase 05 should verify this

---
*Phase: 04-heartbeat-safety-net*
*Completed: 2026-03-12*
