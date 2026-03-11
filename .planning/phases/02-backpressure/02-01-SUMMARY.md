---
phase: 02-backpressure
plan: 01
subsystem: messaging
tags: [rabbitmq, kombu, amqp, backpressure, prefetch_count, celery, pool]

# Dependency graph
requires:
  - phase: 01-root-cause-fix
    provides: pool dispatch wired through AMQPRetryConsumerStep.get_handlers() and AMQPRetryHandler.pool
provides:
  - PREFETCH_COUNT defaults to pool.limit (not hardcoded 1)
  - Operator override via EVENT_CONSUMER_PREFETCH_COUNT Django setting
  - consumer.qos() floor guard prevents 0 (AMQP unlimited) from reaching broker
  - Unit tests for BACK-01, BACK-02, BACK-03
affects:
  - 02-backpressure (subsequent plans, if any)
  - Phase 4 (heartbeat) — pool concurrency awareness already established

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "settings.PREFETCH_COUNT=0 as sentinel meaning 'derive from pool at runtime'"
    - "settings.PREFETCH_COUNT or pool_limit or 1 — truthy-chain for fallback resolution"
    - "max(effective_prefetch, 1) floor guard before passing to AMQP consumer.qos()"
    - "getattr(self.pool, 'limit', None) — safe attribute access on Celery pool object"

key-files:
  created:
    - tests/test_backpressure.py
  modified:
    - event_consumer/settings.py
    - event_consumer/handlers.py

key-decisions:
  - "PREFETCH_COUNT=0 as default sentinel: 0 is falsy in Python, enabling 'settings.PREFETCH_COUNT or pool_limit or 1' resolution chain without extra branches"
  - "prefetch_count passed as constructor param to AMQPRetryHandler, not re-derived inside __init__ — keeps resolution logic in one place (start())"
  - "max(effective_prefetch, 1) in handler __init__ as a second safety net in case prefetch_count=0 reaches handler directly (e.g. from tests or future callers)"
  - "getattr(self.pool, 'limit', None) guards against pools that lack a .limit attribute (solo pool, custom pool implementations)"

patterns-established:
  - "Pool attribute access: always use getattr(pool, 'limit', None) not pool.limit directly"
  - "AMQP QOS floor: always wrap consumer.qos(prefetch_count=...) with max(..., 1)"
  - "Backpressure tests: use _build_step_and_c() + _run_start() helpers to exercise start() path"

requirements-completed: [BACK-01, BACK-02, BACK-03]

# Metrics
duration: 2min
completed: 2026-03-11
---

# Phase 2 Plan 01: Backpressure — Pool-derived PREFETCH_COUNT Summary

**PREFETCH_COUNT now derives from pool.limit at startup instead of hardcoded 1, enabling true concurrent processing while letting the broker enforce backpressure at the pool concurrency ceiling**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-11T09:35:00Z
- **Completed:** 2026-03-11T09:36:45Z
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 3

## Accomplishments

- `settings.PREFETCH_COUNT` changed from hardcoded `1` to `get('PREFETCH_COUNT', 0)` — 0 is the new sentinel meaning "derive from pool concurrency at runtime"
- `AMQPRetryConsumerStep.start()` resolves effective `prefetch_count` via `settings.PREFETCH_COUNT or pool_limit or 1` (explicit setting wins, pool.limit fallback, floor=1)
- `AMQPRetryHandler.__init__()` accepts `prefetch_count` parameter; `max(effective_prefetch, 1)` guard prevents AMQP unlimited (0) from reaching the broker
- Operator override via `EVENT_CONSUMER_PREFETCH_COUNT` Django setting works end-to-end
- 5 new tests covering all three requirements; full suite 16/16 passing with no Phase 1 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing tests for backpressure requirements** - `9f23d20` (test)
2. **Task 2: Implement pool-derived prefetch_count and make tests green** - `0466e45` (feat)

_Note: TDD tasks have separate test (RED) and feat (GREEN) commits_

## Files Created/Modified

- `tests/test_backpressure.py` - 5 unit tests covering BACK-01/02/03; uses _build_step_and_c() + _run_start() helpers to exercise the full start() path
- `event_consumer/settings.py` - PREFETCH_COUNT changed from `1` to `get('PREFETCH_COUNT', 0)` with explanatory comment
- `event_consumer/handlers.py` - pool_limit resolution in start(), prefetch_count param through get_handlers(), max() floor guard in __init__()

## Decisions Made

- **0-as-sentinel pattern:** Using `PREFETCH_COUNT=0` as default (instead of `None`) means the `settings.PREFETCH_COUNT or pool_limit or 1` truthy-chain works naturally without `if/elif` branching. The comment documents this contract.
- **Two-layer floor guard:** The `max(effective_prefetch, 1)` in `AMQPRetryHandler.__init__` is a second safety net in addition to the `or 1` in `start()`. Belt and suspenders for a correctness-critical path.
- **Resolution location:** prefetch_count is computed once in `start()` and passed down. It is NOT re-derived inside `__init__`. This keeps the resolution logic in a single place and makes the constructor's behavior predictable regardless of call site.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Operators who want to override the pool-derived default can set `EVENT_CONSUMER_PREFETCH_COUNT` in their Django settings.

## Next Phase Readiness

- Backpressure requirements BACK-01, BACK-02, BACK-03 complete
- Pool concurrency now controls broker delivery rate — no unbounded in-memory accumulation
- Phase 2 plan 01 is the only plan in this phase; phase 02-backpressure is complete
- Ready to proceed to Phase 3 (or next planned phase)

---
*Phase: 02-backpressure*
*Completed: 2026-03-11*
