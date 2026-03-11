---
phase: 3
slug: reconnect-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-11
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | none — run from repo root |
| **Quick run command** | `pytest tests/test_reconnect.py -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_reconnect.py -x -q`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 0 | CONN-01 | unit | `pytest tests/test_reconnect.py::test_close_resets_handlers -x` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 0 | CONN-01 | unit | `pytest tests/test_reconnect.py::test_restart_no_stale_handlers -x` | ❌ W0 | ⬜ pending |
| 3-01-03 | 01 | 0 | CONN-02 | unit | `pytest tests/test_reconnect.py::test_on_pool_success_closed_channel -x` | ❌ W0 | ⬜ pending |
| 3-01-04 | 01 | 0 | CONN-02 | unit | `pytest tests/test_reconnect.py::test_on_pool_error_closed_channel_requeue -x` | ❌ W0 | ⬜ pending |
| 3-01-05 | 01 | 0 | POOL-04 | unit | `pytest tests/test_reconnect.py::test_prefork_guard_sets_pool_none -x` | ❌ W0 | ⬜ pending |
| 3-01-06 | 01 | 0 | POOL-04 | unit | `pytest tests/test_reconnect.py::test_prefork_guard_inline_fallback -x` | ❌ W0 | ⬜ pending |
| 3-01-07 | 01 | 0 | CONN-03 | unit | `pytest tests/test_reconnect.py::test_blueprint_restart_clean_state -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_reconnect.py` — unit tests for CONN-01, CONN-02, CONN-03, POOL-04

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
