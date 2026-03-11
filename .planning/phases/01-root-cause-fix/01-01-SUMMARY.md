---
phase: 01-root-cause-fix
plan: "01"
subsystem: testing
tags: [pytest, mocking, kombu, celery, amqp, pool, ack]

# Dependency graph
requires: []
provides:
  - "pytest test infrastructure: tests/__init__.py, tests/conftest.py, tests/test_handlers.py"
  - "11 unit tests covering POOL-01/02/03/05 and ACK-01/02/03/04/05"
  - "Shared fixtures: mock_pool with apply_async capture, mock_message factory, mock_channel, handler with Kombu internals patched"
  - "RED baseline: 10 tests fail against current broken code, 1 passes (POOL-05)"
affects: [02-implementation, 01-02-PLAN]

# Tech tracking
tech-stack:
  added: [pytest]
  patterns: [TDD-RED phase, fixture-based mocking, apply_async callback capture pattern]

key-files:
  created:
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_handlers.py
  modified: []

key-decisions:
  - "Use autouse settings_patch fixture to isolate all tests from real Django settings -- avoids test-order sensitivity"
  - "mock_pool._all_calls list captures every apply_async invocation so ACK-04 (two-message test) can inspect both callbacks independently"
  - "handler.pool set directly after construction -- Plan 02 will wire pool through get_handlers; fixture mirrors the expected post-fix state"
  - "Create venv at /tmp/celery-consumer-venv for test runs -- project Pipfile is empty, Django/Celery/Kombu not yet in repo deps"

patterns-established:
  - "Fixture pattern: mock_pool._last_call dict stores {target, args, callback, error_callback} from each apply_async call"
  - "Fixture pattern: mock_message factory with ack side_effect that flips .acknowledged = True"
  - "Test pattern: dispatch handler(), snapshot mock_pool._last_call, then manually invoke callback/error_callback to exercise async path"

requirements-completed:
  - POOL-01
  - POOL-02
  - POOL-03
  - POOL-05
  - ACK-01
  - ACK-02
  - ACK-03
  - ACK-04
  - ACK-05

# Metrics
duration: 20min
completed: 2026-03-11
---

# Phase 1 Plan 01: Test Infrastructure and RED Baseline Summary

**pytest fixture scaffolding with 11 unit tests covering pool dispatch and ack correctness -- 10 fail against current broken code (intentional RED), 1 passes (decorator API)**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-03-11T00:00:00Z
- **Completed:** 2026-03-11T00:20:00Z
- **Tasks:** 2 of 2
- **Files modified:** 3 created

## Accomplishments
- Created `tests/` package with `__init__.py`, `conftest.py`, `test_handlers.py`
- 11 tests discoverable by pytest, covering all 9 Phase 1 requirements
- `conftest.py` provides mock_pool with `apply_async` call capture, mock_message factory with ack side-effects, handler fixture with full Kombu internals patched out
- POOL-05 (decorator API) passes against current code; all other tests fail as expected (RED baseline for Plan 02)
- Established dependency-free test execution: no live broker, no live RabbitMQ, no Django DB required

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test fixtures (conftest.py)** - `8e1507b` (test)
2. **Task 2: Write failing unit tests for all Phase 1 requirements** - `917f14b` (test)

**Plan metadata:** (this commit) (docs: complete plan 01-01)

## Files Created/Modified
- `tests/__init__.py` - Package marker for pytest discovery
- `tests/conftest.py` - Shared fixtures: mock_channel, mock_message factory, mock_pool with apply_async capture, handler with Kombu patched, autouse settings_patch
- `tests/test_handlers.py` - 11 unit tests for POOL-01/02/03/05 and ACK-01/02/03/04/05

## Decisions Made
- Set up a temporary venv at `/tmp/celery-consumer-venv` since the project Pipfile is empty and system Python is under Homebrew-managed restrictions. The venv contains pytest, celery, kombu, django, six.
- Used `patch.multiple('event_consumer.settings', ...)` pattern in autouse fixture to override settings without modifying Django's conf -- ensures tests are fully isolated regardless of environment.
- Stored `mock_pool._all_calls` list so ACK-04 (lambda capture test) can snapshot each `apply_async` call independently rather than relying on `_last_call` which gets overwritten.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `event_consumer/settings.py` imports `from django.conf import settings` at module level, requiring Django to be installed and configured before any test import. Handled by adding Django configure call at the top of `conftest.py` before any `event_consumer` imports.
- System Python3 is Homebrew-managed and rejects `pip install` without a venv. Created `/tmp/celery-consumer-venv` to run tests.

## User Setup Required
None -- tests run in the project directory with the venv:
```bash
/tmp/celery-consumer-venv/bin/python -m pytest tests/test_handlers.py -q
```

## Next Phase Readiness
- Test infrastructure complete; Plan 02 can immediately validate each implementation change
- Expected state when Plan 02 is done: all 11 tests GREEN
- The `error_callback` signature check (Celery 3.x vs 4.x/5.x) is resolved: Celery 5.x installed, `error_callback` receives a single `exc_info` tuple argument

---
*Phase: 01-root-cause-fix*
*Completed: 2026-03-11*

## Self-Check: PASSED

- tests/__init__.py: FOUND
- tests/conftest.py: FOUND
- tests/test_handlers.py: FOUND
- .planning/phases/01-root-cause-fix/01-01-SUMMARY.md: FOUND
- Commit 8e1507b: FOUND
- Commit 917f14b: FOUND
