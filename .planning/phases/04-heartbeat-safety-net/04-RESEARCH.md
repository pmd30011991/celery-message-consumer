# Phase 4: Heartbeat Safety Net - Research

**Researched:** 2026-03-11
**Domain:** AMQP heartbeat mechanics, eventlet green threads, py-amqp connection lifecycle
**Confidence:** HIGH (heartbeat mechanism confirmed from py-amqp source in prior research; greenlet pattern validated by project research/heartbeat-safety.md)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BEAT-01 | AMQP heartbeats maintained during long-running handler execution | Dedicated heartbeat greenlet calls `connection.heartbeat_tick()` on `interval/2` cadence, independent of listener loop |
| BEAT-02 | Dedicated heartbeat greenlet spawned in `start()` as safety net (conditional on connection heartbeat being set) | `eventlet.spawn(heartbeat_loop, c.connection, c.connection.heartbeat)` guarded by `if c.connection.heartbeat:` in `AMQPRetryConsumerStep.start()` |
</phase_requirements>

---

## Summary

`py-amqp` heartbeats are not automatic. The `connection.heartbeat_tick()` method must be called manually — it is invoked by Celery's `drain_events()` loop on the listener thread. Before Phase 1, the listener thread was blocked by inline handler execution, which meant heartbeats could not be sent. After Phase 1, the listener thread returns to `drain_events()` immediately after dispatching to the pool, so heartbeats resume naturally under normal conditions.

Phase 4 adds a defense-in-depth safety net: a dedicated greenlet that calls `heartbeat_tick()` on `interval/2` cadence, independent of the listener loop. This guards against edge cases where the listener is continuously busy dispatching many fast-arriving messages and cannot reliably pump `drain_events()` between dispatches. The greenlet is only spawned when `c.connection.heartbeat` is non-zero (i.e., heartbeating is enabled on the connection).

The implementation is a single small addition to `AMQPRetryConsumerStep.start()`. No changes to `AMQPRetryHandler` are required. Under eventlet, the `heartbeat_loop` greenlet runs on the same OS thread as the listener via cooperative scheduling — `amqp.Connection` is not OS-thread-safe but is safe from multiple green threads on the same OS thread.

**Primary recommendation:** Spawn `eventlet.spawn(heartbeat_loop, c.connection, c.connection.heartbeat)` at the end of `AMQPRetryConsumerStep.start()`, guarded by `if c.connection.heartbeat:`. Stop the greenlet in `_close()` by storing it as `self._heartbeat_greenlet` and calling `self._heartbeat_greenlet.kill()` if set.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `eventlet` | already in venv | Spawn heartbeat greenlet; cooperative sleep | Project already uses eventlet pool; monkey-patched |
| `amqp` (py-amqp) | already in venv | `connection.heartbeat_tick()` sends/receives heartbeat frames | py-amqp is Celery's AMQP transport; this is its documented heartbeat API |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `gevent` | already in venv | Alternative to eventlet | Only if worker started with `-P gevent`; `gevent.spawn` + `gevent.sleep` instead |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `eventlet.spawn` | `gevent.spawn` | gevent variant required when `-P gevent`; same pattern, different import |
| `interval/2` sleep | `interval` sleep | Half-interval is safer — gives two chances per heartbeat window; standard Celery practice |

**Installation:** No new dependencies. `eventlet` is already required by the worker pool.

---

## Architecture Patterns

### Recommended Change: Add heartbeat greenlet to `start()`

The only file that changes is `event_consumer/handlers.py`. The change is confined to `AMQPRetryConsumerStep`.

**Pattern: Heartbeat Loop Greenlet**

What: A long-running green thread that sleeps for `interval/2` seconds then calls `connection.heartbeat_tick()`.

When to use: Always, when `c.connection.heartbeat` is non-zero at the time `start()` is called.

```python
# Source: project research/heartbeat-safety.md (verified pattern)

def _heartbeat_loop(connection, interval):
    """Send AMQP heartbeats at interval/2 cadence as a safety net."""
    while True:
        eventlet.sleep(interval / 2)
        connection.heartbeat_tick()
```

**Spawn in `start()` after handlers are set up:**

```python
def start(self, c):
    # ... existing pool/prefetch/handler setup ...

    # BEAT-02: Spawn heartbeat safety net greenlet if connection heartbeat is set
    self._heartbeat_greenlet = None
    if c.connection.heartbeat:
        self._heartbeat_greenlet = eventlet.spawn(
            _heartbeat_loop, c.connection, c.connection.heartbeat
        )
        _logger.info(
            'AMQPRetryConsumerStep: heartbeat greenlet started (interval=%ds)',
            c.connection.heartbeat,
        )
```

**Kill in `_close()`:**

```python
def _close(self, c, cancel_consumers=True):
    # ... existing close logic ...
    if getattr(self, '_heartbeat_greenlet', None) is not None:
        self._heartbeat_greenlet.kill()
        self._heartbeat_greenlet = None
    self.handlers = []
```

**Initialize in `__init__()` to avoid AttributeError:**

```python
def __init__(self, *args, **kwargs):
    self.handlers = []
    self._heartbeat_greenlet = None
    # ... rest of __init__ ...
```

### Module-level vs. method-level function

Define `_heartbeat_loop` as a module-level function (not a method) so it holds no reference to `self`. This prevents a reference cycle that could delay garbage collection of the step after stop.

### Anti-Patterns to Avoid

- **Calling `heartbeat_tick()` from a real OS thread (`eventlet.tpool`):** `amqp.Connection` is not OS-thread-safe. The greenlet must run on the eventlet hub (same OS thread as listener), not a real thread.
- **Not killing the greenlet in `_close()`:** A leaked greenlet will continue calling `heartbeat_tick()` on a closed connection after reconnect, causing errors or interfering with the new connection's heartbeat.
- **Spawning the greenlet unconditionally:** Connections without heartbeat configured (`c.connection.heartbeat == 0` or `None`) must not spawn the greenlet. The guard `if c.connection.heartbeat:` handles both `0` and `None`.
- **Double-tick interference:** Celery's own consumer loop also calls `heartbeat_tick()` via `drain_events()`. This is safe — `heartbeat_tick()` is idempotent with respect to timing and will not send extra frames if the interval has not elapsed. Do not suppress Celery's own calls.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Heartbeat timing | Custom timer thread, `threading.Timer` | `eventlet.spawn` + `eventlet.sleep` | OS threads are unsafe for `amqp.Connection`; eventlet green threads are safe on the same OS thread |
| Greenlet lifecycle | Manual flag / event polling loop | `greenlet.kill()` | `kill()` raises `GreenletExit` into the greenlet cleanly; flag polling adds unnecessary complexity |

---

## Common Pitfalls

### Pitfall 1: Leaked heartbeat greenlet after reconnect
**What goes wrong:** `_close()` is called on reconnect. If the greenlet is not killed, it keeps calling `heartbeat_tick()` on the old (closed) connection. On the next `start()`, a second greenlet is spawned for the new connection. Two greenlets fight over different connection objects.

**Why it happens:** `_close()` is called by both `stop()` and `shutdown()`. If the developer forgets to kill the greenlet in `_close()`, the leak is silent until a reconnect occurs.

**How to avoid:** Store the greenlet reference as `self._heartbeat_greenlet`. Kill and clear it as the first action in `_close()` before any channel teardown.

**Warning signs:** After a reconnect cycle, log shows two heartbeat log lines per interval, or `heartbeat_tick()` raises on a closed connection.

### Pitfall 2: `AttributeError` on `_heartbeat_greenlet` in `_close()`
**What goes wrong:** `_close()` is called before `start()` has ever run (e.g., during error recovery). `self._heartbeat_greenlet` does not exist, raising `AttributeError`.

**Why it happens:** `_close()` is callable independently of `start()`.

**How to avoid:** Initialize `self._heartbeat_greenlet = None` in `__init__()`. Use `getattr(self, '_heartbeat_greenlet', None)` as a belt-and-suspenders guard in `_close()`.

### Pitfall 3: Spawning greenlet when heartbeat is disabled
**What goes wrong:** With `heartbeat=0` or `heartbeat=None`, `_heartbeat_loop` divides by zero or spins in a zero-sleep loop.

**Why it happens:** `interval / 2` where `interval` is `0` causes `eventlet.sleep(0)` — a hot spin consuming 100% CPU.

**How to avoid:** The `if c.connection.heartbeat:` guard (falsy check) prevents spawning when heartbeat is `0` or `None`. Both are falsy in Python.

### Pitfall 4: gevent workers not handled
**What goes wrong:** On `-P gevent` workers, `eventlet` may not be monkey-patched or available. `import eventlet` raises `ImportError`.

**Why it happens:** Phase 4 targets the common eventlet case. gevent requires `gevent.spawn` and `gevent.sleep`.

**How to avoid:** The simplest fix is to try-import eventlet first, fall back to gevent, and log a warning if neither is available. Given the project's existing prefork guard pattern, a similar try/except is appropriate:

```python
try:
    import eventlet as _greenlet_lib
    _spawn = _greenlet_lib.spawn
    _sleep = _greenlet_lib.sleep
except ImportError:
    try:
        import gevent as _greenlet_lib
        from gevent import sleep as _sleep, spawn as _spawn
    except ImportError:
        _spawn = None
        _sleep = None
```

Only spawn the greenlet if `_spawn is not None`.

---

## Code Examples

### Complete heartbeat greenlet implementation

```python
# Source: project research/heartbeat-safety.md (HIGH confidence)

import eventlet

def _heartbeat_loop(connection, interval):
    """
    Safety-net greenlet: sends AMQP heartbeat frames at interval/2 cadence.
    Runs on the eventlet hub (same OS thread as listener) — safe for amqp.Connection.
    Only spawned when connection.heartbeat is non-zero.
    """
    while True:
        eventlet.sleep(interval / 2)
        connection.heartbeat_tick()
```

### `AMQPRetryConsumerStep.__init__` update

```python
def __init__(self, *args, **kwargs):
    self.handlers = []
    self._heartbeat_greenlet = None   # BEAT-02: init before start() is ever called
    self._tasks = kwargs.pop('tasks', REGISTRY)
    super(AMQPRetryConsumerStep, self).__init__(*args, **kwargs)
```

### `AMQPRetryConsumerStep.start()` addition (append after existing handler setup)

```python
# BEAT-02: Heartbeat safety net — only when connection heartbeat is configured
self._heartbeat_greenlet = None
if c.connection.heartbeat:
    self._heartbeat_greenlet = eventlet.spawn(
        _heartbeat_loop, c.connection, c.connection.heartbeat
    )
    _logger.info(
        'AMQPRetryConsumerStep: heartbeat greenlet started (interval=%ds)',
        c.connection.heartbeat,
    )
```

### `AMQPRetryConsumerStep._close()` addition (prepend before channel teardown)

```python
def _close(self, c, cancel_consumers=True):
    # BEAT-02: Kill heartbeat greenlet before tearing down connection
    if getattr(self, '_heartbeat_greenlet', None) is not None:
        self._heartbeat_greenlet.kill()
        self._heartbeat_greenlet = None

    # ... existing channel/consumer teardown ...
    self.handlers = []
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Listener thread handles heartbeats via `drain_events()` only | Dedicated safety-net greenlet + listener | Phase 4 | Heartbeats survive listener saturation |
| Inline handler execution blocked heartbeats entirely | Async pool dispatch (Phase 1) unblocks listener | Phase 1 (complete) | Phase 4 is now truly defense-in-depth, not critical path |

**Deprecated/outdated:**
- Inline handler execution (line 346 bug): Fixed in Phase 1. Phase 4 is no longer plugging a critical gap — it is hardening an already-working system.

---

## Open Questions

1. **Does `heartbeat_tick()` interfere with Celery's own heartbeat calls in `drain_events()`?**
   - What we know: `heartbeat_tick()` tracks time internally and only sends frames when the interval has elapsed. Calling it more frequently than needed is safe — it is a no-op if called too early.
   - What's unclear: Whether concurrent calls from two green threads (listener loop + heartbeat greenlet) can interleave in a way that corrupts the connection's send buffer.
   - Recommendation: Under eventlet cooperative scheduling, only one green thread runs at a time on the OS thread. True concurrent calls are not possible. This is safe. Flag for confirmation in Phase 5 integration test (TEST-02).

2. **What if the connection object is replaced during reconnect before the greenlet is killed?**
   - What we know: `_close()` kills the greenlet. `start()` spawns a new one with the new `c.connection`. The sequence is `stop()` → `_close()` → kill greenlet → `start()` → spawn new greenlet.
   - What's unclear: Whether Celery's reconnect always calls `stop()` before `start()` (i.e., never `start()` without a preceding `stop()`).
   - Recommendation: Initialize `_heartbeat_greenlet = None` in `__init__()` and always kill-then-clear in `_close()`. This makes `start()` safe to call even if `_close()` was not called first.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (venv at /tmp/celery-consumer-venv) |
| Config file | none — inline pytest invocation |
| Quick run command | `/tmp/celery-consumer-venv/bin/pytest tests/test_handlers.py -x -q` |
| Full suite command | `/tmp/celery-consumer-venv/bin/pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BEAT-01 | Heartbeat maintained during handler execution | unit (mock connection) | `/tmp/celery-consumer-venv/bin/pytest tests/test_handlers.py::test_heartbeat_tick_called -x` | Wave 0 |
| BEAT-02 | Greenlet spawned only when `c.connection.heartbeat` is non-zero | unit | `/tmp/celery-consumer-venv/bin/pytest tests/test_handlers.py::test_heartbeat_greenlet_spawned_when_heartbeat_set tests/test_handlers.py::test_no_heartbeat_greenlet_when_heartbeat_zero -x` | Wave 0 |
| BEAT-02 | Greenlet killed in `_close()` | unit | `/tmp/celery-consumer-venv/bin/pytest tests/test_handlers.py::test_heartbeat_greenlet_killed_on_close -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `/tmp/celery-consumer-venv/bin/pytest tests/test_handlers.py -x -q`
- **Per wave merge:** `/tmp/celery-consumer-venv/bin/pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_handlers.py` — add BEAT-01 and BEAT-02 test cases (file exists from Phase 1; new test functions needed)
- [ ] Mock for `c.connection` with `.heartbeat` attribute needed in test fixtures

*(Existing test infrastructure in place; only new test functions required — no new files)*

---

## Sources

### Primary (HIGH confidence)
- `project .planning/research/heartbeat-safety.md` — py-amqp `heartbeat_tick()` mechanics, greenlet safety, `heartbeat_loop` pattern. Verified by project research team against py-amqp source.
- `project .planning/research/SUMMARY.md` — Cross-researcher consensus on heartbeat greenlet architecture; confirmed HIGH confidence rating.
- `event_consumer/handlers.py` (current) — Actual `AMQPRetryConsumerStep.start()` and `_close()` code; identifies exact insertion points.

### Secondary (MEDIUM confidence)
- Celery `celery/concurrency/eventlet.py` — callbacks from `apply_async` run on the hub (same OS thread); confirms greenlet ack safety. Referenced in SUMMARY.md.
- AMQP 0-9-1 spec — heartbeat frame semantics; `heartbeat_tick()` sends a heartbeat frame if the interval has elapsed since last frame sent or received.

### Tertiary (LOW confidence — flag for validation)
- Heartbeat greenlet interference with Celery's own `drain_events()` heartbeat calls: theoretically safe under cooperative scheduling; confirm empirically in Phase 5 TEST-02.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — eventlet is already in use; `heartbeat_tick()` API confirmed against py-amqp source
- Architecture: HIGH — pattern confirmed by project heartbeat-safety.md research; insertion points visible in current handlers.py
- Pitfalls: HIGH — greenlet leak and AttributeError pitfalls are mechanical; zero-division guard is straightforward
- Greenlet/Celery interference: MEDIUM — theoretically safe, confirm in Phase 5

**Research date:** 2026-03-11
**Valid until:** 2026-04-11 (stable APIs; eventlet and py-amqp heartbeat mechanics are unlikely to change)
