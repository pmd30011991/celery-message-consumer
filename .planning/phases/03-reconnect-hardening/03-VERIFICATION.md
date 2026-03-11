---
phase: 03-reconnect-hardening
verified: 2026-03-11T00:00:00Z
status: passed
score: 4/4 must-haves verified
re_verification: false
---

# Phase 3: Reconnect Hardening Verification Report

**Phase Goal:** A RabbitMQ reconnect produces a clean handler set with no stale references, in-flight callbacks are safe to execute against a closed channel, and prefork pool deployments get a warning and inline fallback.
**Verified:** 2026-03-11
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After a connection drop and reconnect, `_close()` leaves `self.handlers` as an empty list | VERIFIED | `handlers.py` line 216: `self.handlers = []  # CONN-01`; 2 dedicated tests pass |
| 2 | A pool callback that fires after a reconnect does not raise when ack/requeue fails on a closed channel | VERIFIED | `_on_pool_success` try/except line 365-369; `_on_pool_error` finally guard lines 427-433; 4 dedicated tests pass |
| 3 | Starting with `-P prefork` logs a warning and falls back to inline dispatch | VERIFIED | `isinstance(self.pool, AsynPool)` guard lines 176-184; sets `self.pool = None`; 3 dedicated tests pass |
| 4 | Blueprint restart sequence (stop → start) produces a clean handler set with no duplicates | VERIFIED | Enabled by CONN-01 fix; `test_restart_no_stale_handlers` and `test_blueprint_restart_clean_state` both pass |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/test_reconnect.py` | Unit tests for CONN-01, CONN-02, CONN-03, POOL-04; min 80 lines | VERIFIED | 333 lines, 11 tests across 6 test classes, all 11 pass |
| `event_consumer/handlers.py` | Production fixes; contains `self.handlers = []` | VERIFIED | Contains all 3 fixes; substantive implementation confirmed |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `handlers.py::_close` | `self.handlers` | list reset after cleanup loops | WIRED | Line 216: `self.handlers = []` is the final statement after the channel-close loop (lines 208-215) |
| `handlers.py::_on_pool_error` | `message.requeue()` | try/except guard in finally block | WIRED | Lines 426-433: `finally` block wraps `message.requeue()` in `try/except Exception`; failure logs warning, success logs critical |
| `handlers.py::start` | `AsynPool` | isinstance check with ImportError guard | WIRED | Lines 175-186: `try: from celery.concurrency.asynpool import AsynPool; if isinstance(self.pool, AsynPool): ...` with `except ImportError: pass` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CONN-01 | 03-01-PLAN.md | `_close()` clears `self.handlers = []` to prevent stale handler references after reconnect | SATISFIED | Line 216 in `_close()`; `TestCloseResetsHandlers` (2 tests), `TestRestartNoStaleHandlers` (1 test) all pass |
| CONN-02 | 03-01-PLAN.md | Channel operations in pool callbacks guarded with error handling for closed connections | SATISFIED | `_on_pool_success` lines 360-371 (try/except on ack); `_on_pool_error` lines 427-433 (try/except on requeue); `TestOnPoolSuccessClosedChannel` (2 tests), `TestOnPoolErrorClosedChannelRequeue` (2 tests) all pass |
| CONN-03 | 03-01-PLAN.md | Celery's blueprint restart correctly rebuilds handlers on fresh connection | SATISFIED | No separate code change needed — CONN-01 fix enables correct restart; `TestBlueprintRestartCleanState` and `TestRestartNoStaleHandlers` both pass; second `start()` produces exactly N handlers, not 2N, with fresh object references |
| POOL-04 | 03-01-PLAN.md | Prefork pool detected and falls back to inline execution with warning log | SATISFIED | Lines 173-186 in `start()`; `TestPreforkGuardSetsPoolNone` (2 tests), `TestPreforkGuardInlineFallback` (1 test) all pass; `__call__` routes to `_inline_dispatch` when `self.pool is None` (line 524-527) |

No orphaned requirements — all 4 IDs declared in plan frontmatter are accounted for, and REQUIREMENTS.md traceability table maps all 4 to Phase 3.

---

### Anti-Patterns Found

No blockers or warnings detected.

| File | Pattern | Severity | Notes |
|------|---------|----------|-------|
| — | No TODO/FIXME/placeholder found in modified files | — | Clean |
| — | No empty `return null / return {}` stubs | — | All paths fully implemented |
| — | No console.log-only handlers | — | All callbacks log via `_logger` and perform real operations |

---

### Human Verification Required

None. All observable truths are verifiable programmatically for this phase:

- Handler list reset is a state assertion (tested directly).
- Closed-channel guard is a try/except presence + test coverage (confirmed).
- Prefork warning and fallback are mocked and tested without a live broker.
- Blueprint restart clean state is confirmed by object identity comparison in `test_blueprint_restart_clean_state`.

---

### Test Suite Results

```
tests/test_reconnect.py  — 11/11 PASSED
tests/ (full suite)      — 27/27 PASSED  (zero regressions)
```

---

### Summary

Phase 3 goal is fully achieved. Three surgical fixes were applied to `event_consumer/handlers.py`:

1. **CONN-01** (`_close` line 216): `self.handlers = []` as the final statement guarantees no stale references survive between stop and the next start after reconnect. This also directly satisfies CONN-03 — blueprint restart is correct without further code changes.

2. **CONN-02** (`_on_pool_error` lines 427-433): `message.requeue()` in the `finally` block is wrapped in `try/except Exception`. Failures log a warning; successful requeues log critical as before (moved to `else` clause). `_on_pool_success` already had a guard; its warning message was updated to mention reconnect context.

3. **POOL-04** (`start` lines 175-186): `isinstance(self.pool, AsynPool)` wrapped in `try/except ImportError` detects prefork pools, emits a warning, and sets `self.pool = None` (and `pool_limit = None`) to engage the existing `_inline_dispatch` fallback in `__call__`.

All 11 reconnect tests pass. All 27 suite tests pass. No regressions.

---

_Verified: 2026-03-11_
_Verifier: Claude (gsd-verifier)_
