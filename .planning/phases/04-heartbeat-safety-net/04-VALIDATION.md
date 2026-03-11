---
phase: 4
slug: heartbeat-safety-net
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-11
---

# Phase 4 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v`
- **Max feedback latency:** 5 seconds

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 0 | BEAT-01 | unit | `pytest tests/test_heartbeat.py::test_heartbeat_tick_called -x` | ❌ W0 | ⬜ pending |
| 4-01-02 | 01 | 0 | BEAT-02 | unit | `pytest tests/test_heartbeat.py::test_greenlet_spawned_when_heartbeat_set -x` | ❌ W0 | ⬜ pending |
| 4-01-03 | 01 | 0 | BEAT-02 | unit | `pytest tests/test_heartbeat.py::test_no_greenlet_when_heartbeat_zero -x` | ❌ W0 | ⬜ pending |
| 4-01-04 | 01 | 0 | BEAT-02 | unit | `pytest tests/test_heartbeat.py::test_greenlet_killed_on_close -x` | ❌ W0 | ⬜ pending |

## Wave 0 Requirements

- [ ] `tests/test_heartbeat.py` — unit tests for BEAT-01, BEAT-02

## Manual-Only Verifications

*All phase behaviors have automated verification.*

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
