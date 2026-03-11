---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 02-backpressure-02-01-PLAN.md (pool-derived prefetch_count)
last_updated: "2026-03-11T09:40:02.550Z"
last_activity: 2026-03-11 — 01-01 test scaffold complete
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 3
  completed_plans: 3
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-11)

**Core value:** Messages from RabbitMQ dispatched to Celery's eventlet/gevent pool, keeping listener thread free for heartbeats — zero disconnects, zero message loss.
**Current focus:** Phase 1 — Root Cause Fix

## Current Position

Phase: 1 of 5 (Root Cause Fix)
Plan: 1 of 2 in current phase (01-01 complete, 01-02 next)
Status: In Progress
Last activity: 2026-03-11 — 01-01 test scaffold complete

Progress: [█████░░░░░] 50%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: none yet
- Trend: -

*Updated after each plan completion*
| Phase 01-root-cause-fix P01 | 20 | 2 tasks | 3 files |
| Phase 01-root-cause-fix P02 | 2 | 2 tasks | 2 files |
| Phase 02-backpressure P01 | 2 | 2 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Pre-Phase 1]: Use `callback=` / `error_callback=` pattern on `apply_async` — mirrors Celery's own `strategy.py`; separates ack logic from handler logic.
- [Pre-Phase 1]: Lambda default-arg capture (`b=body, m=message`) is mandatory — late-binding bugs will silently ack the wrong message.
- [Pre-Phase 1]: `retry_count` must be captured before `apply_async` dispatch — header is not accessible inside the pool greenlet after dispatch.
- [Phase 01-root-cause-fix]: autouse settings_patch fixture isolates all tests from real Django settings
- [Phase 01-root-cause-fix]: mock_pool._all_calls list captures every apply_async invocation for multi-message tests
- [Phase 01-root-cause-fix]: venv at /tmp/celery-consumer-venv for test runs -- project Pipfile is empty
- [Phase 01-root-cause-fix]: apply_async dispatches callable via target=/args= kwargs, not return value -- fixes root-cause bug POOL-01
- [Phase 01-root-cause-fix]: Lambda default-arg capture (b=body, m=message, rc=retry_count) mandatory for correct per-message ack -- late-binding would silently ack wrong message
- [Phase 01-root-cause-fix]: retry_count read from message.headers before apply_async dispatch -- not accessible inside pool greenlet after dispatch
- [Phase 02-backpressure]: PREFETCH_COUNT=0 as sentinel: falsy value enables truthy-chain 'settings.PREFETCH_COUNT or pool_limit or 1' without extra branches
- [Phase 02-backpressure]: prefetch_count resolved once in start() and passed to AMQPRetryHandler constructor -- not re-derived in __init__, keeps resolution logic in one place
- [Phase 02-backpressure]: max(effective_prefetch, 1) floor guard in AMQPRetryHandler.__init__() prevents AMQP unlimited (0) from reaching broker

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1, RESOLVED]: `error_callback` signature -- Celery 5.x installed. error_callback receives a single exc_info tuple argument (verified in test scaffold).
- [Phase 4]: Confirm heartbeat greenlet does not double-tick with Celery's own heartbeat machinery — test before enabling by default.
- [Phase 5]: No test directory present in current checkout — test infrastructure must be created or restored before TEST-01 through TEST-04 can be written.

## Session Continuity

Last session: 2026-03-11T09:37:49.493Z
Stopped at: Completed 02-backpressure-02-01-PLAN.md (pool-derived prefetch_count)
Resume file: None
