# Backpressure & Acknowledgment Patterns Research

**Domain:** AMQP backpressure and ack patterns for Kombu + eventlet/gevent pool
**Researched:** 2026-03-11
**Overall Confidence:** HIGH for protocol-level; MEDIUM for Celery-internal pool APIs

## Q1: prefetch_count for Backpressure (HIGH confidence)

`prefetch_count` is native AMQP backpressure at the protocol level. When `consumer.qos(prefetch_count=N)`, RabbitMQ tracks N unacknowledged messages per consumer. When all N slots occupied, broker **stops delivering** — no polling needed.

Setting `prefetch_count = pool concurrency` is the simplest backpressure mechanism.

The codebase already calls `self.consumer.qos(prefetch_count=settings.PREFETCH_COUNT)` (line 305). Change needed: set `PREFETCH_COUNT` to match pool size rather than hardcoding `1`.

## Q2: Delayed Acknowledgment from Pool Worker (HIGH confidence)

Current bug (line 346): `self.pool.apply_async(self.func(body))` executes handler inline.

Fix: pass a closure that encapsulates handler + ack:

```python
def __call__(self, body, message):
    retry_count = self.retry_count(message)

    def worker_task():
        try:
            self.func(body)
            message.ack()
        except PermanentFailure as exc:
            self.archive(body, message, reason=str(exc))
        except Exception as exc:
            if retry_count >= settings.MAX_RETRIES:
                self.archive(body, message, reason=str(exc))
            else:
                self.retry(body, message, reason=str(exc))
        finally:
            if self._semaphore:
                self._semaphore.release()
            if settings.USE_DJANGO:
                request_finished.send(sender="AMQPRetryHandler")
            if not message.acknowledged:
                message.requeue()

    if self._semaphore:
        self._semaphore.acquire()

    self.pool.apply_async(worker_task)
```

## Q3: Tracking In-Flight / Pause-Resume (HIGH confidence)

Two patterns used together:
1. **`prefetch_count = pool_size`** — broker-enforced, zero-overhead
2. **`eventlet.semaphore.Semaphore(pool_size)`** — app-level safety net. Cooperative greenlets yield (don't block OS thread) so heartbeats continue while listener waits for a slot.

## Q4: Unacked Messages on Disconnect (HIGH confidence — AMQP spec)

RabbitMQ immediately requeues all unacknowledged messages on connection close. Messages redelivered with `message.delivery_info['redelivered'] = True`. Handler must be idempotent or tolerate duplicates.

## Q5: Celery's Own Pattern with Eventlet (MEDIUM confidence)

Celery uses `worker_prefetch_multiplier` (default 4) × concurrency = prefetch count, with dynamic `QoS` class. For `acks_late=True`, ack sent from worker greenlet after task completes. With `-P eventlet`, all workers are greenlets on one OS thread — ack calls safe (cooperative scheduling serializes writes).

## Q6: Semaphore/Token-Based Backpressure (HIGH confidence)

`eventlet.semaphore.Semaphore(N)` cooperatively yields instead of blocking OS thread.

Pattern:
- Create semaphore with `N = pool concurrency` in `AMQPRetryConsumerStep.start()`
- Pass to each `AMQPRetryHandler`
- `acquire()` before `pool.apply_async()` in `__call__`
- `release()` in worker's `finally` block (critical — must be in finally)

## Critical Codebase Observations

1. QoS call already in right place, one channel shared across handlers
2. `apply_async` bug (line 346) makes pool dispatch synchronous
3. `PREFETCH_COUNT = 1` prevents real concurrency
4. No semaphore to track in-flight across pool

---
*Research: 2026-03-11*
