# Phase 2: Backpressure - Research

**Researched:** 2026-03-11
**Domain:** AMQP QoS / prefetch_count / eventlet Semaphore / Kombu consumer configuration
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BACK-01 | `PREFETCH_COUNT` configurable and aligned with pool concurrency | `settings.PREFETCH_COUNT` already exists and is already applied via `consumer.qos()`. Change its default value and make it derivable from pool concurrency. |
| BACK-02 | RabbitMQ stops delivering messages when all prefetch slots occupied | AMQP `basic.qos` with `prefetch_count=N` is broker-enforced. Once N unacked messages are outstanding, the broker holds additional messages. Already wired; just needs the right value. |
| BACK-03 | Consumer does not accumulate unbounded in-memory messages during pool saturation | `prefetch_count` limits broker delivery. An optional `eventlet.Semaphore(pool_size)` adds app-level defense-in-depth to prevent burst over-dispatch before a slot frees. |
</phase_requirements>

---

## Summary

Phase 1 fixed the root cause: `apply_async` now dispatches the handler callable asynchronously to a pool greenlet, and the listener thread returns to `drain_events()` immediately. This means the listener now eagerly drains messages from the broker. Without a correctly-sized `prefetch_count`, RabbitMQ will keep pushing messages as fast as the network allows, filling consumer memory with unprocessed messages while the pool is fully occupied.

The fix is already 90% in place. `AMQPRetryHandler.__init__` already calls `self.consumer.qos(prefetch_count=settings.PREFETCH_COUNT)` on line 308. The only problem is that `settings.PREFETCH_COUNT` is hardcoded to `1`. With `PREFETCH_COUNT=1`, only one message is ever in-flight at a time — the pool is never utilized for concurrency. The correct value is the pool concurrency (i.e., the number of greenlets Celery allocates), which can be read from `c.pool.limit` at startup in `AMQPRetryConsumerStep.start()`. This value should be exposed as a configurable setting with a sensible default and documented clearly.

The secondary layer of defense is an optional `eventlet.Semaphore`. When `apply_async` is called, Celery may accept the task into the pool's internal queue rather than reject it, so `prefetch_count` alone does not guarantee zero over-dispatch above pool capacity. The semaphore adds a cooperative-yield guard in `__call__` that blocks the listener greenlet (without blocking the OS thread) when all pool slots are busy. Under the project's current requirements (BACK-01 through BACK-03), the semaphore is an enhancement rather than a hard requirement — `prefetch_count` aligned with pool concurrency satisfies all three success criteria.

**Primary recommendation:** Set `PREFETCH_COUNT` to the pool's `.limit` attribute in `AMQPRetryConsumerStep.start()`, expose it as `EVENT_CONSUMER_PREFETCH_COUNT` for operator override, and document the pool-size relationship clearly in settings.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Kombu (already present) | 4.x / 5.x | `consumer.qos(prefetch_count=N)` — sends AMQP `basic.qos` frame | The only interface to RabbitMQ's backpressure primitive; already called in codebase |
| py-amqp (already present) | 2.x / 5.x | Underlying AMQP transport that transmits the QoS frame | Transitively used via Kombu; no direct change required |
| eventlet (already present) | 0.33+ | `eventlet.semaphore.Semaphore(N)` — cooperative-yield app-level gate | Required for `-P eventlet`; semaphore yields instead of blocking OS thread |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| gevent (optional) | 22.x+ | `gevent.lock.BoundedSemaphore(N)` — gevent equivalent | When deploying with `-P gevent` instead of `-P eventlet` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| AMQP `prefetch_count` | Application-level polling / sleep loop | `prefetch_count` is zero-cost broker-enforced; polling wastes CPU and adds latency |
| `eventlet.Semaphore` as defense-in-depth | Rely on `prefetch_count` alone | Semaphore prevents over-queuing inside Celery's pool queue; omitting it is acceptable for Phase 2 success criteria |

**No new dependencies required.** All necessary libraries are already present.

---

## Architecture Patterns

### What Already Exists (Phase 1 output)

```python
# event_consumer/handlers.py — AMQPRetryConsumerStep.start()
def start(self, c):
    channel = c.connection.channel()
    self.pool = c.pool            # pool captured here
    self.handlers = self.get_handlers(channel)
    for handler in self.handlers:
        handler.declare_queues()
        handler.consumer.consume()

# event_consumer/handlers.py — AMQPRetryHandler.__init__()
self.consumer.qos(prefetch_count=settings.PREFETCH_COUNT)  # line 308

# event_consumer/settings.py
PREFETCH_COUNT = 1   # <- THE ONLY VALUE THAT NEEDS TO CHANGE
```

### Pattern 1: Pool-Sized PREFETCH_COUNT

**What:** Read the pool's concurrency limit in `start()` and store it so `get_handlers` can pass it through to each handler, which applies it via `consumer.qos()`.

**When to use:** Always — this is the standard RabbitMQ backpressure pattern.

**How the pool limit is accessed:**

```python
# Source: Celery BasePool — celery/concurrency/base.py
# c.pool is a BasePool subclass; .limit is the concurrency count
pool_size = getattr(c.pool, 'limit', None)
```

For Celery's eventlet pool (`celery/concurrency/eventlet.py`), `pool.limit` returns the greenlet count passed via `-c N` (defaults to CPU count or 1 for eventlet). This is a public, stable attribute.

**Recommended change to `AMQPRetryConsumerStep.start()`:**

```python
# Source: pattern from celery/concurrency/base.py and codebase convention
def start(self, c):
    channel = c.connection.channel()
    self.pool = c.pool
    pool_limit = getattr(self.pool, 'limit', None)
    # Allow explicit override; fall back to pool size; final fallback = 1
    self.prefetch_count = settings.PREFETCH_COUNT or pool_limit or 1
    self.handlers = self.get_handlers(channel)
    for handler in self.handlers:
        handler.declare_queues()
        handler.consumer.consume()
```

**Recommended change to `get_handlers()`:**

```python
def get_handlers(self, channel):
    return [
        AMQPRetryHandler(
            channel=channel,
            ...
            pool=self.pool,
            prefetch_count=self.prefetch_count,  # NEW
        )
        for queue_key, handler_registration in self._tasks.items()
    ]
```

**Recommended change to `AMQPRetryHandler.__init__()`:**

```python
def __init__(self, ..., pool=None, prefetch_count=None):
    ...
    self.consumer.qos(
        prefetch_count=prefetch_count if prefetch_count is not None else settings.PREFETCH_COUNT
    )
```

### Pattern 2: settings.py PREFETCH_COUNT as Operator Override

**What:** `PREFETCH_COUNT` in `settings.py` transitions from a hardcoded `1` to an operator-configurable value that defaults to `0` (meaning "derive from pool"). When set explicitly, it overrides the pool-derived value.

**Recommended change to `settings.py`:**

```python
# 0 means "use pool concurrency" — set explicitly to override
PREFETCH_COUNT = get('PREFETCH_COUNT', 0)
```

This preserves the existing `EVENT_CONSUMER_PREFETCH_COUNT` Django settings key for operators who want manual control, and adds the automatic derivation path when unset.

### Pattern 3: eventlet.Semaphore as Optional Defense-in-Depth

**What:** An `eventlet.Semaphore(N)` in `__call__` ensures the listener greenlet yields cooperatively when all pool slots are taken, rather than over-queuing inside the pool's internal task queue.

**When to use:** Optional for Phase 2. Include if over-dispatch in testing is observed; otherwise document as a v2 enhancement (CONC-01 in REQUIREMENTS.md).

**Pattern (if implemented):**

```python
# In AMQPRetryConsumerStep.start():
import eventlet
self._semaphore = eventlet.semaphore.Semaphore(self.prefetch_count)

# In AMQPRetryHandler.__call__():
if self._semaphore:
    self._semaphore.acquire()   # cooperative yield if pool full

self.pool.apply_async(
    target=self.func,
    args=(body,),
    callback=lambda result, b=body, m=message: ...,
    error_callback=lambda exc_info, b=body, m=message, rc=retry_count: ...,
)

# In _on_pool_success and _on_pool_error (finally blocks):
if self._semaphore:
    self._semaphore.release()
```

**CRITICAL:** Semaphore `release()` MUST be in the `finally` block of both callbacks. If it is placed only in the success path, a pool error will permanently decrement the semaphore counter and eventually deadlock the listener.

**CRITICAL:** The `acquire()` must not block before the `apply_async` call — if it blocks on the OS thread (not cooperatively), it will starve the heartbeat. `eventlet.semaphore.Semaphore` yields to the eventlet hub (cooperative), so heartbeats continue. `threading.Semaphore` would block the OS thread — do NOT use it.

### Anti-Patterns to Avoid

- **`PREFETCH_COUNT = 1` with async pool dispatch:** Prevents any real concurrency. After Phase 1, the pool can process multiple messages simultaneously; `prefetch_count=1` means only one message is ever delivered at a time, serializing execution back to the pre-fix behavior.
- **`threading.Semaphore` instead of `eventlet.Semaphore`:** Blocks the OS thread. The listener greenlet cannot yield to the eventlet hub, heartbeats stall, and the connection drops.
- **Setting `prefetch_count` per-call (outside `__init__`):** `consumer.qos()` sends an AMQP frame on every call. Call it once during handler initialization, not on every message.
- **`prefetch_count=0`:** In AMQP, `prefetch_count=0` means unlimited — no backpressure at all. Do not pass `0` to `consumer.qos()`. Use pool size as the floor.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Broker-level flow control | Custom polling / sleep / rate limiter | `consumer.qos(prefetch_count=N)` | Broker-enforced at protocol level; zero CPU overhead; already in codebase |
| Cooperative greenlet yield | `while pool_full: eventlet.sleep(0.01)` | `eventlet.semaphore.Semaphore(N)` | Semaphore is a proper synchronization primitive; polling wastes CPU and adds dispatch jitter |
| Pool size discovery | Parsing Celery config strings | `c.pool.limit` | Stable public attribute on `BasePool`; avoids re-parsing concurrency config |

**Key insight:** The entire backpressure mechanism is one integer. AMQP's `basic.qos` does the rest at the broker. Custom polling, rate limiters, and buffer managers are not needed.

---

## Common Pitfalls

### Pitfall 1: PREFETCH_COUNT=0 Passed to consumer.qos()

**What goes wrong:** `consumer.qos(prefetch_count=0)` disables backpressure entirely. RabbitMQ delivers all queued messages immediately. Under load, the consumer buffers all messages in memory while the pool processes them one at a time.

**Why it happens:** The `get('PREFETCH_COUNT', 0)` default of `0` (meaning "derive from pool") could be passed directly to `consumer.qos()` if the pool-derivation logic is missing or fails.

**How to avoid:** In `AMQPRetryHandler.__init__`, assert `prefetch_count >= 1` before calling `consumer.qos()`. Fall back to `1` rather than `0` if derivation fails.

**Warning signs:** RabbitMQ management UI shows consumer's unacked count immediately jumping to the full queue depth on worker start.

### Pitfall 2: Semaphore Not Released on Error Path

**What goes wrong:** If `_semaphore.release()` is not in a `finally` block, an exception in the callback (e.g., ack failure) permanently leaks a semaphore slot. After `N` errors, the semaphore count reaches zero and the listener permanently stops dispatching.

**Why it happens:** Developers put `release()` in the success branch only, or forget it entirely in `_on_pool_error`.

**How to avoid:** Always pair `acquire()` / `release()` with `try/finally`. Place `release()` in the `finally` block of both `_on_pool_success` and `_on_pool_error`. Add a unit test that verifies `release()` is called even when the callback raises.

**Warning signs:** Consumer processes exactly `N` messages and then goes silent; no errors logged.

### Pitfall 3: QoS Called Per Message Instead of Once at Init

**What goes wrong:** Calling `self.consumer.qos(prefetch_count=N)` inside `__call__` sends an AMQP frame for every message. This adds network overhead and may cause timing issues with in-flight messages.

**Why it happens:** Developers confuse per-message configuration with per-consumer configuration.

**How to avoid:** `consumer.qos()` is called once in `AMQPRetryHandler.__init__()` — this is already the pattern in the codebase. Do not move it.

### Pitfall 4: Multiple Handlers — QoS Applies Per Consumer

**What goes wrong:** Each `AMQPRetryHandler` creates its own `kombu.Consumer` and calls `qos()` independently. If there are 5 handlers and `prefetch_count=10`, each handler can have up to 10 unacked messages — total in-flight is `5 * 10 = 50`, not 10.

**Why it happens:** Misunderstanding of per-consumer vs. per-channel QoS scope.

**How to avoid:** Be explicit in documentation that `PREFETCH_COUNT` is per-handler (per-consumer), not global. If global backpressure across all handlers is needed, use `basic.qos` with `global=True` — but this is a v2 concern (CONC-02).

**Warning signs:** Under load, unacked message count in RabbitMQ is `handler_count * PREFETCH_COUNT` rather than `PREFETCH_COUNT`.

---

## Code Examples

### Reading Pool Concurrency

```python
# Source: Celery BasePool signature — celery/concurrency/base.py
# pool.limit is the worker concurrency count (set via -c N)
pool_limit = getattr(c.pool, 'limit', None)  # None if pool has no limit attr
effective_prefetch = pool_limit or 1          # Never pass 0 to consumer.qos()
```

### Applying QoS in Handler Init (current pattern — already correct location)

```python
# Source: event_consumer/handlers.py line 308 — no location change needed
self.consumer.qos(prefetch_count=prefetch_count)
```

### settings.py PREFETCH_COUNT Change

```python
# Before (Phase 1 state):
PREFETCH_COUNT = 1

# After (Phase 2 change):
# 0 = derive from pool concurrency at runtime (recommended)
# N = explicit override (operator sets EVENT_CONSUMER_PREFETCH_COUNT=N)
PREFETCH_COUNT = get('PREFETCH_COUNT', 0)
```

### Optional Semaphore Pattern (if implementing CONC-01 defense-in-depth)

```python
# In AMQPRetryConsumerStep.start():
import eventlet.semaphore
self._semaphore = eventlet.semaphore.Semaphore(self.prefetch_count)

# Pass to each handler:
AMQPRetryHandler(..., semaphore=self._semaphore)

# In AMQPRetryHandler.__call__():
if self._semaphore:
    self._semaphore.acquire()    # cooperative yield; never blocks OS thread

# In _on_pool_success and _on_pool_error (MUST be in finally):
try:
    ...
finally:
    if self._semaphore:
        self._semaphore.release()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `PREFETCH_COUNT = 1` (blocks all concurrency) | `PREFETCH_COUNT = pool.limit` (matches pool concurrency) | Phase 2 | Pool actually runs N handlers concurrently; broker stops after N unacked |
| Manual ack inline in `__call__` | Deferred ack in `_on_pool_success` callback | Phase 1 | `prefetch_count` slots are held correctly until ack fires in callback |

**Deprecated/outdated:**
- `PREFETCH_COUNT = 1` hardcoded in `settings.py`: This was a safe sentinel while ack happened inline. After Phase 1, it becomes a concurrency bottleneck. Phase 2 replaces it.

---

## Open Questions

1. **Does `c.pool.limit` reliably exist for all pool types in use?**
   - What we know: `BasePool` in Celery 4.x and 5.x has a `limit` property. Eventlet pool wraps `eventlet.GreenPool(size=N)` and exposes `.limit`. Gevent pool is analogous.
   - What's unclear: Celery 3.x BasePool — whether `limit` is the same attribute name. The codebase targets Celery 5.x (confirmed installed in Phase 1).
   - Recommendation: Use `getattr(c.pool, 'limit', None)` with `None` fallback. If `None`, log a warning and default to `settings.PREFETCH_COUNT or 1`. This is safe.

2. **Should the semaphore be implemented in Phase 2 or deferred to v2 (CONC-01)?**
   - What we know: `prefetch_count` alone satisfies BACK-01, BACK-02, BACK-03. The semaphore is defense-in-depth.
   - What's unclear: Whether Celery's eventlet pool internally queues beyond `pool.limit` before rejecting. If it does, over-dispatch is possible without the semaphore.
   - Recommendation: Defer semaphore to CONC-01 (v2). Phase 2 delivers broker-level backpressure via `prefetch_count`. Document semaphore as the next layer.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (present at `/tmp/celery-consumer-venv`) |
| Config file | none — run from repo root |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BACK-01 | `PREFETCH_COUNT` defaults to pool size when `EVENT_CONSUMER_PREFETCH_COUNT` not set | unit | `pytest tests/test_handlers.py -k "prefetch" -x` | Wave 0 |
| BACK-01 | `EVENT_CONSUMER_PREFETCH_COUNT` override applies when set | unit | `pytest tests/test_handlers.py -k "prefetch_override" -x` | Wave 0 |
| BACK-02 | `consumer.qos(prefetch_count=N)` called with pool size on handler init | unit | `pytest tests/test_handlers.py -k "qos" -x` | Wave 0 |
| BACK-03 | `PREFETCH_COUNT` never passes `0` to `consumer.qos()` — floor is 1 | unit | `pytest tests/test_handlers.py -k "prefetch_floor" -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_backpressure.py` — covers BACK-01, BACK-02, BACK-03 prefetch behavior
  - Test: `AMQPRetryConsumerStep.start()` sets `prefetch_count = pool.limit` when `PREFETCH_COUNT=0`
  - Test: `AMQPRetryHandler.__init__()` calls `consumer.qos(prefetch_count=N)` with the resolved value
  - Test: `prefetch_count` is never `0` when passed to `consumer.qos()`
  - Test: explicit `EVENT_CONSUMER_PREFETCH_COUNT` override takes precedence over pool size

---

## Sources

### Primary (HIGH confidence)

- `event_consumer/handlers.py` lines 168–207, 308 — existing QoS call location and pool capture; change scope is minimal
- `event_consumer/settings.py` lines 23–24 — `PREFETCH_COUNT = 1` is the only value to change
- AMQP 0-9-1 specification — `basic.qos` `prefetch_count` semantics: broker stops delivery when N unacked messages are outstanding; this is protocol-level, not library-level
- `.planning/research/backpressure-ack.md` — confirms `prefetch_count = pool concurrency` pattern; QoS already in right place

### Secondary (MEDIUM confidence)

- Celery `celery/concurrency/base.py` — `BasePool.limit` attribute; stable across 4.x and 5.x
- Celery `celery/concurrency/eventlet.py` — eventlet pool wraps `eventlet.GreenPool`; `.limit` == greenlet count
- `eventlet.semaphore.Semaphore` docs — cooperative yield semantics confirmed

### Tertiary (LOW confidence — deferred to CONC-01)

- Whether Celery's eventlet pool internally queues beyond `pool.limit` before rejecting — not verified empirically; semaphore need depends on this behavior

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — no new libraries; change is one integer value and wiring
- Architecture: HIGH — QoS already wired in correct place; pattern is AMQP spec
- Pitfalls: HIGH — `prefetch_count=0` and semaphore leak are well-understood failure modes

**Research date:** 2026-03-11
**Valid until:** 2026-09-11 (stable AMQP spec; Kombu API stable)
