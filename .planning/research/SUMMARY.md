# Project Research Summary

**Project:** celery-message-consumer — Pool Dispatch Adoption
**Domain:** Celery bootstep / Kombu AMQP consumer / eventlet-gevent pool dispatch
**Researched:** 2026-03-11
**Confidence:** HIGH (core mechanics well-documented; MEDIUM on Celery 3.x edge cases)

---

## Executive Summary

The `celery-message-consumer` library currently contains a single root-cause bug on line 346: `self.pool.apply_async(self.func(body))` calls `self.func(body)` synchronously and passes its return value — not the function itself — to `apply_async`. The result is that every message handler executes inline on the listener thread, which blocks heartbeats, prevents real concurrency, and defeats the purpose of the pool entirely. All four research tracks independently identified this same bug as their starting point, which gives HIGH confidence in the diagnosis.

Fixing the dispatch call is step one, but it immediately exposes four downstream problems that must be resolved in concert: (1) ack/retry/archive logic must move from inline code into pool `callback=` and `error_callback=` parameters so RabbitMQ's channel is not touched from an arbitrary greenlet context; (2) heartbeats need a dedicated greenlet as a safety net so the listener hub can pump the connection while the pool is busy; (3) backpressure must be re-established by aligning `PREFETCH_COUNT` with pool concurrency and adding an `eventlet.Semaphore` to prevent over-dispatch; (4) the bootstep's `_close()` method must clear `self.handlers` to prevent stale handler references surviving a reconnect. All four fixes follow well-documented patterns used by Celery's own internals (`celery/worker/strategy.py` uses the same callback-based ack pattern).

The recommended architecture keeps the existing bootstep/handler structure intact — research confirms this design is correct — and makes targeted, surgical changes: fix the `apply_async` call signature, wire callbacks for all post-execution side effects, add a heartbeat greenlet in `start()`, and tie `PREFETCH_COUNT` to pool size. No rewrite required. The highest remaining risk is ack safety when a reconnect interrupts an in-flight pool task; this is mitigated by wrapping all channel operations in callbacks with `kombu.common.ignore_errors()` guards.

---

## Key Findings

### The Root Cause (All Researchers Agree)

Every research file converged on the same bug independently:

```python
# CURRENT — synchronous, blocks listener thread
self.pool.apply_async(self.func(body))

# CORRECT — async dispatch with deferred ack via callbacks
self.pool.apply_async(
    target=self.func,
    args=(body,),
    callback=lambda result, b=body, m=message: self._on_pool_success(b, m),
    error_callback=lambda exc_info, b=body, m=message, rc=retry_count:
        self._on_pool_error(b, m, exc_info, rc),
)
```

This is the only change needed to unblock the listener thread. Everything else flows from here.

### Pool Dispatch (from pool-dispatch.md)

`BasePool.apply_async` signature is stable across Celery 4.x and 5.x. The pool reference is already correctly captured as `self.pool = c.pool` in `AMQPRetryConsumerStep.start()`. Celery's own worker strategy uses the identical `callback=` / `error_callback=` pattern for deferred acks (`celery/worker/strategy.py`), confirming this is the right approach.

**Key decisions from this research:**
- Lambda default-argument capture (`b=body, m=message`) is mandatory to avoid late-binding bugs — closures over loop variables will silently use the wrong message.
- `retry_count` must be read from the message header at the top of `__call__` before dispatch, not inside the callback.
- A prefork guard is needed: `AsynPool` (prefork) does not support cross-thread dispatch; fall back to inline execution if detected.
- Inline fallback (when `pool is None`) preserves backward compatibility for non-eventlet/gevent deployments.

### Heartbeat Safety (from heartbeat-safety.md)

`py-amqp` heartbeats are not automatic — `heartbeat_tick()` is called by the Celery consumer's `drain_events()` loop on the listener thread. When the listener thread is blocked by a synchronous handler, heartbeats stall. At default RabbitMQ settings (60s interval, 2x timeout = 120s), long handlers will cause connection drops and silent ack failures.

After the dispatch fix, the listener thread returns to the `drain_events()` loop immediately and heartbeats resume naturally. A dedicated heartbeat greenlet is recommended as an additional safety net for periods of high dispatch load:

```python
if c.connection.heartbeat:
    eventlet.spawn(heartbeat_loop, c.connection, c.connection.heartbeat)
```

Under eventlet/gevent, green threads on the same OS thread are channel-safe due to cooperative scheduling. Acks from `apply_async` callbacks are safe under eventlet/gevent because callbacks execute on the hub (same OS thread). CPU-bound handlers that never yield are a degenerate case; document this constraint rather than engineering around it.

### Backpressure and Acknowledgment (from backpressure-ack.md)

`prefetch_count` is the primary AMQP-level backpressure mechanism. The codebase already calls `self.consumer.qos(prefetch_count=settings.PREFETCH_COUNT)` — the QoS plumbing is correct. The only change needed is to set `PREFETCH_COUNT` equal to pool concurrency instead of hardcoding `1`. With `prefetch_count = pool_size`, RabbitMQ stops delivering new messages once all pool slots are occupied, at no application-level polling cost.

An `eventlet.Semaphore(pool_size)` adds an app-level safety net that cooperatively yields (does not block the OS thread) when the pool is full. This is a defense-in-depth measure: `prefetch_count` handles the broker side; the semaphore handles any burst between the broker count and actual pool availability.

The alternate closure pattern (embedding ack inside a `worker_task` closure passed to `apply_async`) is also valid and simpler for teams that find callback parameters unfamiliar. Both patterns are safe under eventlet/gevent.

### Auto-Reconnect (from auto-reconnect.md)

Celery's reconnect loop already handles the bootstep correctly: on connection loss, `blueprint.restart()` calls `step.stop()` then `step.start(c)` with a fresh connection object. The existing `get_handlers(channel)` pattern — creating fresh Kombu objects per channel — is architecturally correct and survives restart automatically.

The one concrete bug here is that `_close()` does not reset `self.handlers = []`. If `stop()` fails mid-way, stale handlers persist and `start()` may append to them rather than replace them. The fix is a one-line addition.

In-flight messages during a reconnect are safe at the AMQP level: RabbitMQ requeues all unacknowledged messages on connection close with `redelivered=True`. Handlers must be idempotent (or tolerate duplicates). Callbacks that attempt to ack on a closed channel must be guarded with `kombu.common.ignore_errors()`.

---

## Consensus Patterns (All Researchers Agree)

1. **The `apply_async` call signature is broken and is the single root cause.** Fix it first.
2. **Ack must be deferred to callbacks.** Never ack inline after dispatch.
3. **Channel operations are safe from green threads on the same OS thread.** Use eventlet/gevent pool, not OS threads (tpool), for ack/retry operations.
4. **`prefetch_count` is the right backpressure primitive.** Already wired in the codebase; just change the value.
5. **The bootstep/handler structure is correct.** No architectural redesign needed — only targeted fixes.
6. **Handlers must be idempotent.** RabbitMQ redelivery on reconnect is guaranteed; the library cannot prevent it.

---

## Conflicts and Open Questions

| Question | Status | Resolution |
|----------|--------|------------|
| `error_callback` receives `sys.exc_info()` tuple? | MEDIUM confidence — Celery 5.x yes, Celery 3.x unverified | Verify against installed version at startup; add version check or test |
| Semaphore vs. prefetch_count alone — is semaphore necessary? | Minor conflict — backpressure research says "defense in depth"; pool research does not mention it | Use prefetch_count as primary; add semaphore only if concurrency overshoot is observed in testing |
| Closure pattern vs. callback pattern | Style choice, not technical conflict | Both are correct; callback pattern (`callback=`, `error_callback=`) is preferred because it maps directly to Celery internals and separates concerns |
| CPU-bound handlers that never yield | Heartbeat research notes this as a degenerate case; no resolution offered | Document as unsupported; users should not run CPU-bound work in eventlet/gevent pools |

---

## Recommended Architecture

### Component Changes

| Component | Change Required | Rationale |
|-----------|----------------|-----------|
| `AMQPRetryConsumerStep.start()` | Add heartbeat greenlet spawn | Heartbeat safety net |
| `AMQPRetryConsumerStep._close()` | Add `self.handlers = []` | Reconnect stale handler bug |
| `AMQPRetryConsumerStep.get_handlers()` | Pass `pool=self.pool` to each handler | Pool dispatch |
| `AMQPRetryHandler.__init__()` | Accept `pool` parameter | Pool dispatch |
| `AMQPRetryHandler.__call__()` | Fix `apply_async` call; capture `retry_count` before dispatch | Root cause fix |
| `AMQPRetryHandler` | Add `_on_pool_success()` and `_on_pool_error()` | Deferred ack/retry/archive |
| `settings.PREFETCH_COUNT` | Set to pool concurrency (not `1`) | Backpressure |
| New: prefork guard | Detect `AsynPool`; fall back to inline | Safety for non-eventlet deployments |

### Data Flow After Fix

```
drain_events() [listener greenlet]
  │
  ├── message arrives
  │     │
  │     └── AMQPRetryHandler.__call__()
  │           ├── capture retry_count
  │           ├── [optional] semaphore.acquire()
  │           └── pool.apply_async(func, args=(body,),
  │                   callback=_on_pool_success,
  │                   error_callback=_on_pool_error)
  │                         │
  │                         │  [pool greenlet executes func(body)]
  │                         │
  │                   callback fires on hub [listener greenlet]
  │                         ├── SUCCESS: message.ack() + django_cleanup()
  │                         └── ERROR:   archive/retry/requeue + django_cleanup()
  │
  └── [listener returns to drain_events immediately — heartbeats unblocked]

heartbeat_loop [separate greenlet]
  └── eventlet.sleep(interval/2) → connection.heartbeat_tick()
```

### Prefork Guard

```python
try:
    from celery.concurrency.asynpool import AsynPool
    if isinstance(self.pool, AsynPool):
        _logger.warning("Prefork pool detected — falling back to inline dispatch. Use -P eventlet or -P gevent.")
        self.pool = None
except ImportError:
    pass
```

---

## Implications for Roadmap

### Phase 1: Fix the Root Cause Bug
**Rationale:** Every other improvement depends on this. Low risk, high impact. Can be shipped independently.
**Delivers:** True async dispatch — listener thread unblocked, heartbeats restored, pool actually used.
**Implements:**
- Fix `apply_async` call signature in `AMQPRetryHandler.__call__`
- Add `pool` parameter to handler
- Pass `pool=self.pool` from `get_handlers`
- Implement `_on_pool_success` and `_on_pool_error`
- Move `message.ack()`, retry, archive, Django cleanup into callbacks
- Add lambda default-arg capture
- Capture `retry_count` before dispatch
**Avoids:** Lambda late-binding bug (use `b=body, m=message` defaults)

### Phase 2: Backpressure and Concurrency Control
**Rationale:** Once dispatch is async, the consumer will pull messages faster than the pool can process them without backpressure. Must be addressed before production use.
**Delivers:** Broker-enforced flow control; consumer pulls at pool capacity.
**Implements:**
- Set `PREFETCH_COUNT` to pool concurrency
- Optional: `eventlet.Semaphore(pool_size)` as app-level safety net
- Document `prefetch_count` / pool size relationship

### Phase 3: Reconnect Hardening
**Rationale:** The reconnect path has a known bug and in-flight callback risk. Low effort, prevents subtle production failures.
**Delivers:** Clean reconnect lifecycle; no stale handlers; safe in-flight callbacks.
**Implements:**
- Add `self.handlers = []` to `_close()`
- Wrap ack/retry in callbacks with `ignore_errors()` guard
- Add prefork guard with inline fallback

### Phase 4: Heartbeat Safety Net
**Rationale:** After Phase 1 the listener is mostly unblocked; this is defense-in-depth for edge cases. Lower urgency than correctness fixes.
**Delivers:** Heartbeats maintained even under sustained pool saturation.
**Implements:**
- Heartbeat greenlet in `start()` using `eventlet.spawn`
- Conditional on `c.connection.heartbeat` being set

### Phase 5: Validation and Documentation
**Rationale:** Several behaviors are environment-dependent (Celery version, pool type, heartbeat config). Tests and docs prevent regression.
**Delivers:** Confidence in correctness across supported configurations.
**Implements:**
- Integration tests with real eventlet pool
- Verify `error_callback` signature against Celery 3.x and 5.x
- Document `prefetch_count` / pool size guidance
- Document idempotency requirement for handlers

### Phase Ordering Rationale

- Phase 1 must be first: it is the dependency for all other phases and can be merged independently.
- Phase 2 immediately follows: without backpressure, a working async dispatch will overwhelm the pool.
- Phase 3 is low-effort cleanup that prevents rare but hard-to-debug production failures.
- Phase 4 is defense-in-depth; the listener is already mostly unblocked after Phase 1.
- Phase 5 is last because it validates the behavior established in Phases 1–4.

### Research Flags

Phases with well-established patterns (no additional research needed):
- **Phase 1:** `apply_async` callback pattern is documented in Celery source and confirmed by multiple researchers.
- **Phase 2:** `prefetch_count` and `eventlet.Semaphore` are well-documented primitives.
- **Phase 3:** Reconnect lifecycle is documented in Kombu and confirmed HIGH confidence.

Phases that may benefit from targeted investigation during implementation:
- **Phase 1 / Celery 3.x:** Verify `error_callback` receives `sys.exc_info()` tuple (not the exception directly). Check installed Celery version.
- **Phase 4:** Confirm heartbeat greenlet does not interfere with Celery's own heartbeat machinery if it has one active.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Root cause identification | HIGH | All 4 researchers independently identified the same bug on line 346 |
| `apply_async` callback signature | HIGH | Consistent across Celery 4.x and 5.x; confirmed against Celery source |
| Ack deferral to callbacks | HIGH | Celery's own strategy.py uses identical pattern |
| Heartbeat mechanism | HIGH | py-amqp source confirms manual `heartbeat_tick()` calls |
| Greenlet ack safety | HIGH | Cooperative scheduling semantics well-understood |
| Backpressure via prefetch_count | HIGH | AMQP protocol level; broker-enforced |
| Reconnect lifecycle | HIGH | Kombu/Celery source confirmed |
| Celery 3.x `error_callback` signature | MEDIUM | Not verified against Celery 3.x; may differ |
| CPU-bound handler behavior | MEDIUM | Degenerate case; not tested |
| Semaphore necessity | MEDIUM | Theoretically motivated; practical necessity depends on pool implementation |

**Overall confidence:** HIGH for the core fix; MEDIUM for edge cases.

### Gaps to Address During Implementation

- **Celery version compatibility:** Verify `error_callback` receives `sys.exc_info()` tuple in all supported Celery versions. Add a version check or test at startup if needed.
- **Pool callback thread context:** Confirm empirically (not just theoretically) that `callback=` and `error_callback=` on `apply_async` execute on the eventlet hub thread rather than a pool greenlet. Write a test that asserts `message.ack()` is safe to call from within a callback.
- **Semaphore interaction with prefetch_count:** If both are used, verify they do not create deadlock when pool is saturated and the semaphore blocks `apply_async` dispatch while the listener waits for a callback that cannot fire because the hub is blocked.

---

## Sources

### Primary (HIGH confidence)
- `celery/worker/strategy.py` — `execute_and_trace` with `callback=on_ack, error_callback=on_ack` pattern
- `celery/concurrency/base.py` — `BasePool.apply_async` signature
- `py-amqp` source — `connection.heartbeat_tick()` is manual, called from `drain_events()` loop
- AMQP 0-9-1 spec — `basic.qos` prefetch_count semantics; unacked message requeue on connection close

### Secondary (MEDIUM confidence)
- Celery eventlet pool (`celery/concurrency/eventlet.py`) — wraps `eventlet.GreenPool`; callbacks run on hub
- `kombu.common.ignore_errors` — documented utility for swallowing channel errors during cleanup
- Celery blueprint restart pattern — inferred from `ConsumerMixin` and `Blueprint` source

### Tertiary (requires verification)
- Celery 3.x `error_callback` signature — not independently verified; assume `sys.exc_info()` but confirm before shipping 3.x support
- Heartbeat greenlet interference — theoretical; test in integration environment before enabling by default

---

*Research completed: 2026-03-11*
*Ready for roadmap: yes*
