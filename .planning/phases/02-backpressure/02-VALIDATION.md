---
phase: 2
slug: backpressure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-11
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | none — run from repo root |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 0 | BACK-01 | unit | `pytest tests/test_backpressure.py -k "prefetch_default" -x` | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 0 | BACK-01 | unit | `pytest tests/test_backpressure.py -k "prefetch_override" -x` | ❌ W0 | ⬜ pending |
| 2-01-03 | 01 | 0 | BACK-02 | unit | `pytest tests/test_backpressure.py -k "qos_called" -x` | ❌ W0 | ⬜ pending |
| 2-01-04 | 01 | 0 | BACK-03 | unit | `pytest tests/test_backpressure.py -k "prefetch_floor" -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_backpressure.py` — unit tests for BACK-01, BACK-02, BACK-03

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
