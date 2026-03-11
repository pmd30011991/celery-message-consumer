---
phase: 01-root-cause-fix
plan: 02
subsystem: messaging
tags: [celery, kombu, amqp, pool, greenlet, eventlet, gevent]

# Dependency graph
requires:
  - phase: 01-root-cause-fix/01-01
    provides: test scaffold with mock_pool, mock_message, mock_channel, settings_patch fixtures
provides:
  - Fixed AMQPRetryHandler.__call__ using async pool dispatch (target=/args=/callback=/error_callback=)
  - _on_pool_success callback: deferred message.ack() after handler completes in pool greenlet
  - _on_pool_error callback: deferred retry/archive/requeue logic after handler failure
  - _django_cleanup helper: Django request_finished signal in callbacks only
  - _inline_dispatch fallback: synchronous execution when pool=None
  - pool wiring: AMQPRetryConsumerStep.get_handlers passes pool=self.pool to each handler
affects:
  - 02-heartbeat-integration
  - 03-connection-resilience
  - 04-observability

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "apply_async with target=/args=/callback=/error_callback= for pool dispatch"
    - "Lambda default-arg capture (b=body, m=message, rc=retry_count) to prevent late-binding bugs"
    - "retry_count captured from message headers before apply_async dispatch"
    - "Inline fallback dispatch when pool is unavailable"

key-files:
  created: []
  modified:
    - event_consumer/handlers.py
    - tests/test_handlers.py

key-decisions:
  - "apply_async receives callable + args tuple via target=/args= kwargs, never the return value of calling handler"
  - "Lambda callbacks use default-arg binding (b=body, m=message) -- mandatory to prevent late-binding ack on wrong message"
  - "retry_count must be read from message.headers before apply_async -- headers not accessible inside pool greenlet"
  - "pool=None fallback uses _inline_dispatch for environments where pool is unavailable"
  - "Django cleanup (_django_cleanup) called only in pool callbacks, not in __call__ directly"

patterns-established:
  - "Callback pattern: success in _on_pool_success, failure in _on_pool_error -- mirrors Celery strategy.py"
  - "Safety-net requeue in _on_pool_error finally block for unacknowledged messages after error handling"

requirements-completed: [POOL-01, POOL-02, POOL-03, POOL-05, ACK-01, ACK-02, ACK-03, ACK-04, ACK-05]

# Metrics
duration: 2min
completed: 2026-03-11
---

# Phase 1 Plan 2: Root Cause Fix Summary

**Async pool dispatch via apply_async(target=func, args=(body,), callback=_on_pool_success, error_callback=_on_pool_error) -- listener thread returns immediately, ack/retry/archive deferred to pool callbacks**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-11T09:13:12Z
- **Completed:** 2026-03-11T09:15:19Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Root-cause bug fixed: `apply_async(self.func(body))` replaced with `apply_async(target=self.func, args=(body,), callback=..., error_callback=...)`
- Listener thread unblocked: `__call__` returns after `apply_async` without blocking on handler execution
- All ack/retry/archive logic moved to pool callbacks with correct lambda default-arg capture
- Pool wired end-to-end: `AMQPRetryConsumerStep.get_handlers` passes `pool=self.pool` to each handler
- All 11 unit tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Add pool parameter wiring and helper methods** - `04d0062` (feat)
2. **Task 2: Fix __call__ to use async pool dispatch with callbacks** - `26a063b` (feat)

## Files Created/Modified

- `event_consumer/handlers.py` - Fixed `__call__`, added `pool=None` param, `_django_cleanup`, `_on_pool_success`, `_on_pool_error`, `_inline_dispatch`; wired `pool=self.pool` in `get_handlers`
- `tests/test_handlers.py` - Fixed `test_handler_receives_pool_from_get_handlers` to pass `mock_parent` to `AMQPRetryConsumerStep`

## Decisions Made

- Used `target=` / `args=` / `callback=` / `error_callback=` keyword arguments to `apply_async` for explicit clarity and alignment with Celery's `BasePool` signature
- Lambda default-arg capture (`b=body, m=message, rc=retry_count`) is mandatory -- late-binding would silently ack the wrong message when two messages are in flight
- `retry_count` captured from `message.headers` before dispatch -- not accessible inside pool greenlet after dispatch
- Inline fallback (`_inline_dispatch`) handles pool=None edge case transparently

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_handler_receives_pool_from_get_handlers missing parent argument**
- **Found during:** Task 2 (running test suite after fixing __call__)
- **Issue:** `AMQPRetryConsumerStep(tasks=registry)` raised `TypeError: Step.__init__() missing 1 required positional argument: 'parent'` -- Celery's `bootsteps.Step.__init__` requires a `parent` positional arg
- **Fix:** Added `mock_parent = MagicMock(name='parent')` and changed call to `AMQPRetryConsumerStep(mock_parent, tasks=registry)`
- **Files modified:** `tests/test_handlers.py`
- **Verification:** Test passes; all 11 tests pass
- **Committed in:** `26a063b` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in test scaffold from Plan 01)
**Impact on plan:** Necessary fix; test was correctly designed but lacked the required Celery bootstep parent argument. No scope creep.

## Issues Encountered

None beyond the auto-fixed test scaffold bug above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 1 implementation complete: listener thread is now free during handler execution
- Heartbeat greenlet (Phase 2) can now be integrated without blocking concerns
- All POOL-0x and ACK-0x requirements satisfied
- No blockers for Phase 2

## Self-Check: PASSED

All files present, all commits verified.

---
*Phase: 01-root-cause-fix*
*Completed: 2026-03-11*
