# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-11)

**Core value:** Messages from RabbitMQ dispatched to Celery's eventlet/gevent pool, keeping listener thread free for heartbeats — zero disconnects, zero message loss.
**Current focus:** Phase 1 — Root Cause Fix

## Current Position

Phase: 1 of 5 (Root Cause Fix)
Plan: 0 of TBD in current phase
Status: Ready to plan
Last activity: 2026-03-11 — Roadmap created

Progress: [░░░░░░░░░░] 0%

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

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Pre-Phase 1]: Use `callback=` / `error_callback=` pattern on `apply_async` — mirrors Celery's own `strategy.py`; separates ack logic from handler logic.
- [Pre-Phase 1]: Lambda default-arg capture (`b=body, m=message`) is mandatory — late-binding bugs will silently ack the wrong message.
- [Pre-Phase 1]: `retry_count` must be captured before `apply_async` dispatch — header is not accessible inside the pool greenlet after dispatch.

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: `error_callback` signature may differ between Celery 3.x and 4.x/5.x — verify against installed version before finalizing callback implementation (MEDIUM confidence per research).
- [Phase 4]: Confirm heartbeat greenlet does not double-tick with Celery's own heartbeat machinery — test before enabling by default.
- [Phase 5]: No test directory present in current checkout — test infrastructure must be created or restored before TEST-01 through TEST-04 can be written.

## Session Continuity

Last session: 2026-03-11
Stopped at: Roadmap written. REQUIREMENTS.md traceability table already populated. Ready for `plan-phase 1`.
Resume file: None
