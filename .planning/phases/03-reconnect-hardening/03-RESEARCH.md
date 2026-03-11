# Phase 3: Reconnect Hardening — Research

**Researched:** 2026-03-11
**Domain:** Celery blueprint lifecycle / Kombu connection recovery / prefork pool guard
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| POOL-04 | Prefork pool detected and falls back to inline execution with warning log | AsynPool is importable in Celery 5.x; `isinstance(self.pool, AsynPool)` discrimination confirmed working; inline fallback path (`_inline_dispatch`) already exists from Phase 1 |
| CONN-01 | `_close()` clears `self.handlers = []` to prevent stale handler references after reconnect | Confirmed: blueprint.restart() calls stop() → _close(), then loop re-calls start() — if _close() doesn't reset `self.handlers`, start() appends to stale list |
| CONN-02 | Channel operations in pool callbacks guarded with error handling for closed connections | `kombu.common.ignore_errors(conn, fun)` is the established pattern; already used in `_close()`; callbacks (`_on_pool_success`, `_on_pool_error`) currently use bare `try/except` — needs upgrade to `ignore_errors` or equivalent channel-error catch |
| CONN-03 | Celery's existing blueprint restart correctly rebuilds handlers on fresh connection | Verified: Celery's Consumer.start() loop calls blueprint.start(self) after blueprint.restart(self) — `start(c)` is always called again with a fresh connection object; the current `self.handlers = self.get_handlers(channel)` assignment in `start()` already rebuilds correctly, but only if _close() first cleared the old list |
</phase_requirements>

---

## Summary

Phase 3 delivers three targeted hardening fixes to the reconnect lifecycle. All three are low-risk, surgical changes with no new dependencies.

**CONN-01** is a one-line fix: `_close()` must append `self.handlers = []` after cancelling consumers and closing channels. Without it, `start()` reassigns `self.handlers` correctly but any code path where `stop()` raises mid-iteration leaves stale handlers in the list. The Celery blueprint restart sequence is confirmed: `blueprint.restart(self)` calls `send_all(parent, 'stop')` which calls each step's `stop()`, then the outer `while` loop calls `blueprint.start(self)` again — so `start(c)` is guaranteed to be called with a fresh connection after reconnect. The handler list rebuild in `start()` already works; CONN-01 ensures no staleness can leak through.

**CONN-02** adds channel-error safety to pool callbacks. When a reconnect occurs while a pool greenlet is still executing, the greenlet's callback fires against the now-closed original channel. Currently `_on_pool_success` wraps `message.ack()` in a bare `try/except Exception`, and `_on_pool_error` similarly for retry/archive operations. The fix is to wrap channel operations with `kombu.common.ignore_errors()` — the same pattern already used in `_close()` — or alternatively to catch `kombu`'s connection and channel error tuples explicitly. This prevents unhandled exceptions from crashing the worker when an in-flight callback races a reconnect.

**POOL-04** adds a prefork guard in `AMQPRetryConsumerStep.start()`. `AsynPool` (Celery's prefork pool) does not support cross-thread dispatch via `apply_async` in the same way as eventlet/gevent pools. Detection uses `isinstance(self.pool, AsynPool)` with an import guard, logging a clear warning and setting `self.pool = None` to trigger the existing `_inline_dispatch` fallback. This is a graceful degradation, not an error.

**Primary recommendation:** Apply all three fixes in a single plan — they are independent but all target the same reconnect lifecycle and test together naturally.

---

## Standard Stack

### Core (no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `kombu.common.ignore_errors` | Already installed (Kombu 5.x) | Suppress channel/connection errors during cleanup | Already used in `_close()`; Kombu's official cleanup utility |
| `celery.concurrency.asynpool.AsynPool` | Already installed (Celery 5.6.2) | Prefork pool type for isinstance detection | Only way to discriminate prefork pool from eventlet/gevent |

### No New Dependencies

All Phase 3 changes use existing imports. No `pip install` required.

---

## Architecture Patterns

### Reconnect Lifecycle (Verified from Celery 5.6.2 source)

```
Consumer.start() [outer loop]
  while blueprint.state not in STOP_CONDITIONS:
      blueprint.start(self)         ← calls AMQPRetryConsumerStep.start(c)
      # ... connection error raised ...
      blueprint.restart(self)       ← calls send_all(parent, 'stop')
                                       → calls AMQPRetryConsumerStep.stop(c)
                                       → calls _close(c, cancel_consumers=True)
      # loop continues → blueprint.start(self) called again with fresh c
```

Key insight: `blueprint.restart()` only calls `stop` (reverse order). The outer `while` loop calls `blueprint.start()` on the next iteration with a fresh connection. This means `start(c)` is always called again after reconnect — **handlers are rebuilt correctly** as long as `_close()` first empties `self.handlers`.

### Pattern 1: Handler List Reset in `_close()`

**What:** Clear `self.handlers = []` as the last statement in `_close()`.

**When to use:** Always — defensive cleanup.

**Why:** If `stop()` is called mid-iteration (e.g., cancel raises), some stale handlers remain. The next `start(c)` call assigns `self.handlers = self.get_handlers(channel)`, which replaces the list — but only if we clear first. Without the clear, there's a window where a partially-cleaned list exists between `stop()` and the next `start()`.

```python
# Source: auto-reconnect.md (confirmed against Celery source)
def _close(self, c, cancel_consumers=True):
    _logger.debug('Close Consumer')
    channels = set()
    for handler in self.handlers:
        if cancel_consumers:
            common.ignore_errors(c.connection, handler.consumer.cancel)
        if handler.consumer.channel:
            channels.add(handler.consumer.channel)
    for channel in channels:
        common.ignore_errors(c.connection, channel.close)
    self.handlers = []   # CONN-01: clear stale references after every close
```

### Pattern 2: Channel Error Guard in Pool Callbacks

**What:** Wrap `message.ack()`, `message.requeue()`, `retry_producer.publish()`, and `archive_producer.publish()` calls inside callbacks with `kombu.common.ignore_errors()` or an explicit except clause catching connection/channel error types.

**When to use:** In `_on_pool_success` and `_on_pool_error` — anywhere a channel operation fires from a pool callback that may race a reconnect.

**Two valid approaches:**

```python
# Approach A: kombu.common.ignore_errors (context manager form)
# Source: kombu.common source — ignore_errors(conn, fun) or with ignore_errors(conn):
def _on_pool_success(self, body, message):
    try:
        message.ack()
        _logger.debug("Task '%s' processed and ack() sent", self.routing_key)
    except Exception:
        # Channel may be closed due to reconnect — log and move on
        # RabbitMQ will requeue unacked message on connection close automatically
        _logger.warning(
            "Could not ack message for '%s' (channel may be closed)",
            self.routing_key, exc_info=True
        )
    finally:
        self._django_cleanup()
```

```python
# Approach B: Catch connection/channel error tuples explicitly
# kombu exposes: connection.connection_errors, connection.channel_errors
# These are tuples of exception types, usable in except clauses
```

**Recommendation:** Approach A (current `try/except Exception`) is already functionally correct for `_on_pool_success`. For `_on_pool_error`, the `retry()` and `archive()` methods have their own internal error handling that falls back to `message.requeue()` — but if `message.requeue()` itself fails on a closed channel, there is currently no guard. The fix is to wrap `message.requeue()` calls in the `finally` block of `_on_pool_error` with the same bare `try/except Exception` pattern.

**Important:** `kombu.common.ignore_errors(conn, fun)` requires a live `conn` reference. Inside pool callbacks, we do not have direct access to the connection object. The bare `try/except Exception` pattern is therefore the correct approach in callbacks — not `ignore_errors`.

### Pattern 3: Prefork Guard

**What:** In `AMQPRetryConsumerStep.start()`, after `self.pool = c.pool`, detect if the pool is an `AsynPool` instance and set `self.pool = None` to trigger inline fallback.

**When to use:** Once, at worker startup in `start()`.

```python
# Source: pool-dispatch.md + confirmed against Celery 5.6.2 source
# AsynPool is importable: from celery.concurrency.asynpool import AsynPool
def start(self, c):
    channel = c.connection.channel()
    self.pool = c.pool
    # POOL-04: Prefork pool does not support cross-thread apply_async dispatch
    try:
        from celery.concurrency.asynpool import AsynPool
        if isinstance(self.pool, AsynPool):
            _logger.warning(
                "AMQPRetryConsumerStep: Prefork pool detected (-P prefork). "
                "Falling back to inline dispatch. Use -P eventlet or -P gevent "
                "for true async dispatch."
            )
            self.pool = None
    except ImportError:
        pass  # asynpool not available in this Celery build — not prefork
    # ... rest of start() continues unchanged
```

**Why `ImportError` guard:** `celery.concurrency.asynpool` is present in standard Celery but should be treated as optional — defensive import prevents startup failure if Celery build omits it.

### Anti-Patterns to Avoid

- **Calling `ignore_errors(conn, fun)` inside pool callbacks:** No connection object available in callback scope. Use bare `try/except` instead.
- **Resetting `self.handlers = []` at the start of `start()`:** Too late — the stale state exists between `stop()` and `start()`. Reset belongs in `_close()`.
- **Raising in `_close()` after partial cleanup:** `_close()` already uses `ignore_errors` for consumer cancel and channel close. Do not remove these guards.
- **Checking `pool.__class__.__name__ == 'AsynPool'`:** String comparison is fragile across Celery versions. Use `isinstance` with an import guard.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Suppressing channel errors during cleanup | Custom exception-catching wrapper | `kombu.common.ignore_errors` or bare `try/except Exception` | Kombu knows which exceptions are transient channel errors; custom wrappers miss some |
| Detecting pool type | String comparison, duck-typing, pool attribute inspection | `isinstance(pool, AsynPool)` with ImportError guard | AsynPool is the canonical type; isinstance is reliable across Celery 4.x/5.x |
| Reconnect orchestration | Custom retry loop | Celery's `blueprint.restart()` + outer `while` loop | Already handles reconnect; bootstep just needs clean state |

---

## Common Pitfalls

### Pitfall 1: Forgetting to Reset `self.handlers` in `_close()`

**What goes wrong:** After a connection drop, `stop()` → `_close()` runs but `self.handlers` retains the old (now-closed-channel) handler objects. Next `start(c)` assigns `self.handlers = self.get_handlers(channel)` which creates a fresh list — BUT if `stop()` raised mid-iteration before `_close()` completed, the assignment never happened and stale handlers persist.

**Why it happens:** Python's list assignment in `start()` only fires if `start()` is reached. If `stop()` itself raises before reaching `_close()`, the handlers list is never reset.

**How to avoid:** Reset `self.handlers = []` as the final statement in `_close()`, not in `start()`.

**Warning signs:** Duplicate consumer registrations in RabbitMQ management UI; duplicate log lines for the same routing key; messages processed twice after reconnect.

### Pitfall 2: Pool Callback Firing on Closed Channel

**What goes wrong:** A pool greenlet finishes execution milliseconds after a connection drop. Its `_on_pool_success` callback fires and calls `message.ack()` against the already-closed channel. If not guarded, this raises an `amqp.exceptions.AMQPConnectionError` or similar, which propagates as an unhandled exception in the callback context, potentially crashing the worker.

**Why it happens:** Pool greenlets run independently of the listener thread. The listener detects the connection drop and calls `blueprint.restart()`, but an already-dispatched greenlet finishes concurrently and its callback fires on the stale channel.

**How to avoid:** Wrap `message.ack()` and `message.requeue()` in `_on_pool_success` and `_on_pool_error` with `try/except Exception`. Log the failure as a warning — do not re-raise. The message is safe: RabbitMQ requeued it on connection close.

**Warning signs:** Worker crash logs showing `AMQPConnectionError` inside `_on_pool_success`; unexpected worker restarts after connection drops.

### Pitfall 3: Prefork Pool Dispatch Deadlock

**What goes wrong:** `AsynPool.apply_async()` uses a different internal dispatch mechanism (socket-based IPC with worker processes) than eventlet/gevent pools. Calling it from the AMQP listener thread can deadlock or silently fail to dispatch.

**Why it happens:** `AsynPool` is designed for Celery's own task dispatch, not for arbitrary cross-thread callbacks. Its `apply_async` expects to be called from the Celery worker's main process event loop, not from an AMQP bootstep.

**How to avoid:** POOL-04 prefork guard — detect `AsynPool`, set `self.pool = None`, fall back to `_inline_dispatch`. The inline path is correct and safe for prefork; it simply doesn't provide the async benefits.

**Warning signs:** Worker hangs after receiving first message; `apply_async` returns but callback never fires; pool workers show 0% utilization.

### Pitfall 4: `_close()` Reset Placement — Order Matters

**What goes wrong:** If `self.handlers = []` is placed before the loop that cancels consumers and closes channels, the loop has nothing to iterate.

**How to avoid:** Place `self.handlers = []` AFTER the cleanup loops, as the very last statement in `_close()`.

---

## Code Examples

### CONN-01: Complete `_close()` with Handler Reset

```python
# Source: auto-reconnect.md pattern; verified against current handlers.py
def _close(self, c, cancel_consumers=True):
    _logger.debug('Close Consumer')
    channels = set()
    for handler in self.handlers:
        if cancel_consumers:
            common.ignore_errors(c.connection, handler.consumer.cancel)
        if handler.consumer.channel:
            channels.add(handler.consumer.channel)
    for channel in channels:
        common.ignore_errors(c.connection, channel.close)
    self.handlers = []  # CONN-01: prevent stale references after reconnect
```

### CONN-02: Guarded `_on_pool_success`

```python
# Current code already has try/except Exception — this is sufficient.
# The key addition is ensuring the except clause does NOT re-raise,
# and the finally block also guards any channel operations.
def _on_pool_success(self, body, message):
    """Called by pool after successful handler execution. Acks the message."""
    try:
        message.ack()
        _logger.debug("Task '%s' processed and ack() sent", self.routing_key)
    except Exception:
        # Channel may be closed due to reconnect between dispatch and callback.
        # RabbitMQ requeues unacked messages on connection close automatically.
        _logger.warning(
            "Could not ack message for '%s' (channel likely closed by reconnect)",
            self.routing_key, exc_info=True
        )
    finally:
        self._django_cleanup()
```

### CONN-02: Guarded `_on_pool_error` finally block

```python
# The critical addition is guarding message.requeue() in the finally block.
# Currently it calls message.requeue() without a guard; if the channel is
# closed the requeue raises, which surfaces as an unhandled exception.
finally:
    self._django_cleanup()
    if not message.acknowledged:
        try:
            message.requeue()
        except Exception:
            _logger.warning(
                "Could not requeue message for '%s' (channel likely closed by reconnect)",
                self.routing_key, exc_info=True
            )
        else:
            _logger.critical(
                "Message for task '%s' unacknowledged after error callback - requeueing.",
                self.routing_key,
            )
```

### POOL-04: Prefork Guard in `start()`

```python
# Source: pool-dispatch.md + verified AsynPool importable in Celery 5.6.2
def start(self, c):
    channel = c.connection.channel()
    self.pool = c.pool
    pool_limit = getattr(self.pool, 'limit', None)

    # POOL-04: Prefork pool (AsynPool) does not support cross-thread dispatch.
    # Detect and fall back to inline execution with a warning.
    try:
        from celery.concurrency.asynpool import AsynPool
        if isinstance(self.pool, AsynPool):
            _logger.warning(
                "AMQPRetryConsumerStep: Prefork pool detected (-P prefork). "
                "Falling back to inline dispatch. "
                "Use -P eventlet or -P gevent for true async dispatch."
            )
            self.pool = None
            pool_limit = None
    except ImportError:
        pass  # asynpool not available in this Celery build

    # Explicit setting wins; fall back to pool concurrency; final fallback = 1
    self.prefetch_count = settings.PREFETCH_COUNT or pool_limit or 1
    # ... rest of start() unchanged
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Inline `self.func(body)` execution | `pool.apply_async(target, args, callback, error_callback)` | Phase 1 (2026-03-11) | Listener thread unblocked; ack deferred to callbacks |
| Hardcoded `PREFETCH_COUNT=1` | Pool-derived `prefetch_count` from `pool.limit` | Phase 2 (2026-03-11) | Broker enforces backpressure at pool capacity |
| `_close()` without `self.handlers = []` | `_close()` resets handler list | Phase 3 (this phase) | No stale handlers after reconnect |
| Bare `try/except` on `message.requeue()` in callbacks | Guarded requeue in `_on_pool_error` finally | Phase 3 (this phase) | No unhandled exception when callback races reconnect |
| No prefork detection | `isinstance(pool, AsynPool)` guard with inline fallback | Phase 3 (this phase) | `-P prefork` deployments warn and degrade gracefully |

---

## Open Questions

1. **`_on_pool_error` `retry()` and `archive()` — are they already safe?**
   - What we know: `retry()` has its own `try/except` that falls back to `message.requeue()` on failure. `archive()` similarly. Both internally call `message.ack()` in their `else` clauses.
   - What's unclear: If `retry_producer.publish()` raises due to closed channel, `retry()` calls `message.requeue()` — but `message.requeue()` may also fail. The existing `except` in `retry()` does not guard the `message.requeue()` call.
   - Recommendation: The `_on_pool_error` finally block's `message.requeue()` guard (CONN-02 example above) is the right place to add this protection. Internal `retry()` / `archive()` guards are lower priority but can be tightened in Phase 5.

2. **Should `self.pool = None` in the prefork guard reset `pool_limit` too?**
   - What we know: After `self.pool = None`, `pool_limit` must also be `None` or the `prefetch_count` resolution `settings.PREFETCH_COUNT or pool_limit or 1` will still use the prefork pool's limit.
   - Recommendation: Explicitly set `pool_limit = None` immediately after `self.pool = None` in the guard block (shown in the POOL-04 code example above).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (Celery 5.6.2 / Python 3.13) |
| Config file | none — invoked directly |
| Quick run command | `/tmp/celery-consumer-venv/bin/pytest tests/test_reconnect.py -x -q` |
| Full suite command | `/tmp/celery-consumer-venv/bin/pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONN-01 | `_close()` resets `self.handlers = []` | unit | `pytest tests/test_reconnect.py::test_close_resets_handlers -x` | ❌ Wave 0 |
| CONN-01 | After reconnect, `start()` creates exactly N handlers (no duplicates) | unit | `pytest tests/test_reconnect.py::test_restart_no_stale_handlers -x` | ❌ Wave 0 |
| CONN-02 | `_on_pool_success` ack failure (closed channel) does not raise | unit | `pytest tests/test_reconnect.py::test_on_pool_success_closed_channel -x` | ❌ Wave 0 |
| CONN-02 | `_on_pool_error` requeue failure (closed channel) does not raise | unit | `pytest tests/test_reconnect.py::test_on_pool_error_closed_channel_requeue -x` | ❌ Wave 0 |
| POOL-04 | Prefork pool detected → `self.pool = None` + warning logged | unit | `pytest tests/test_reconnect.py::test_prefork_guard_sets_pool_none -x` | ❌ Wave 0 |
| POOL-04 | Prefork pool detected → handler falls back to `_inline_dispatch` | unit | `pytest tests/test_reconnect.py::test_prefork_guard_inline_fallback -x` | ❌ Wave 0 |
| CONN-03 | `blueprint.restart()` sequence leaves handlers clean for next `start()` | unit | `pytest tests/test_reconnect.py::test_blueprint_restart_clean_state -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `/tmp/celery-consumer-venv/bin/pytest tests/test_reconnect.py -x -q`
- **Per wave merge:** `/tmp/celery-consumer-venv/bin/pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_reconnect.py` — covers CONN-01, CONN-02, CONN-03, POOL-04 (7 tests above)

Existing infrastructure sufficient — `conftest.py` provides `mock_channel`, `mock_message`, `mock_pool`, `handler`, and `settings_patch` fixtures. No new fixture work needed for Phase 3 tests. The `mock_message` fixture's `ack.side_effect` pattern can be extended with `side_effect=Exception("channel closed")` for CONN-02 tests.

---

## Sources

### Primary (HIGH confidence)

- Celery 5.6.2 source — `celery/worker/consumer/consumer.py` lines 191-232: confirmed `blueprint.restart()` sequence and outer `while` loop that calls `blueprint.start()` after reconnect
- Celery 5.6.2 source — `celery/bootsteps.py` `Blueprint.restart()`, `send_all()`, `start()`: confirmed `restart()` only calls `stop`; `start()` is the separate loop call
- `kombu.common.ignore_errors` source (installed): confirmed signature `ignore_errors(conn, fun=None)` and context manager form; confirmed it requires a live `conn` object (therefore not usable inside pool callbacks without connection reference)
- `celery.concurrency.asynpool.AsynPool` — confirmed importable in Celery 5.6.2 at `/tmp/celery-consumer-venv`; confirmed `isinstance(AsynPool_instance, AsynPool)` works
- `.planning/research/auto-reconnect.md` — HIGH confidence reconnect lifecycle analysis; CONN-01 fix identified
- `.planning/research/pool-dispatch.md` — POOL-04 prefork guard pattern; inline fallback strategy
- `event_consumer/handlers.py` (current state after Phase 1+2) — confirmed `_close()` missing `self.handlers = []`; confirmed `_on_pool_error` finally block calls `message.requeue()` without guard

### Secondary (MEDIUM confidence)

- `.planning/research/SUMMARY.md` — consensus patterns for reconnect safety; ignore_errors usage pattern

### Tertiary (LOW confidence — not needed for Phase 3)

- Celery 3.x `error_callback` signature — not relevant to Phase 3; flagged for Phase 5

---

## Metadata

**Confidence breakdown:**
- CONN-01 (`_close` reset): HIGH — one-line fix with verified lifecycle sequence from Celery source
- CONN-02 (callback guards): HIGH — pattern confirmed; exact exception types vary by Celery/amqp version but bare `try/except Exception` is correct
- CONN-03 (blueprint restart): HIGH — verified from Celery 5.6.2 source; `start(c)` is always called after reconnect
- POOL-04 (prefork guard): HIGH — `AsynPool` confirmed importable; `isinstance` check confirmed working; inline fallback path exists from Phase 1

**Research date:** 2026-03-11
**Valid until:** 2026-06-11 (stable Celery internals; unlikely to change in minor versions)
