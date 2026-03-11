# Auto-Reconnect Patterns Research

**Domain:** Kombu auto-reconnect for Celery bootsteps
**Researched:** 2026-03-11
**Overall Confidence:** HIGH

## Q1: Connection.ensure_connection() (HIGH confidence)

Blocking loop that retries `connection.connect()` with exponential backoff:

```python
conn.ensure_connection(
    errback=lambda exc, interval: logger.warning('Retrying in %ds: %r', interval, exc),
    max_retries=None,     # retry forever
    interval_start=1,
    interval_step=1,
    interval_max=10,
)
```

All channel-bound objects (Consumer, Producer, Queue) are invalid after reconnect and must be rebuilt.

## Q2: Celery's Internal Reconnect Pattern (HIGH confidence)

Celery's `Consumer.start()` catches `connection_errors + channel_errors`, calls `connection.ensure_connection()`, then `blueprint.restart(consumer_obj)`. Blueprint restart calls `step.stop()` then `step.start()` on every running bootstep — including `AMQPRetryConsumerStep`.

**This means `start(c)` is called again with a fresh connection after every reconnect.**

## Q3: Bootstep Restart (HIGH confidence)

The bootstep gets `start(c)` called again. Current code handles this structurally (reassigns `self.handlers`), but there is a bug: `_close()` does not clear `self.handlers = []`. Stale handlers could persist if stop fails mid-way.

**Fix:** Add `self.handlers = []` at end of `_close()`.

## Q4: In-Flight Messages During Reconnect (HIGH confidence — AMQP spec)

- Unacked messages at connection drop are **automatically requeued** by RabbitMQ — zero message loss
- If handler is mid-execution and hasn't sent `ack()` yet, message is requeued and re-delivered
- Handlers must be idempotent
- `x-retry-count` header is NOT incremented on automatic requeue (correct — transport fault, not handler fault)

## Q5: Re-declare Queues After Reconnect (HIGH confidence)

Since `start(c)` is called again, re-declaration uses existing `start()` logic. `queue.declare()` is idempotent in RabbitMQ. Current `get_handlers(channel)` correctly creates fresh Kombu objects on new channel.

## Q6: eventlet/gevent Recovery (MEDIUM confidence)

- Listener green thread must stay non-blocking so Celery can pump heartbeats via `drain_events()`
- Pool dispatch must defer execution with correct `apply_async` signature
- Message `ack()` should happen on listener green thread for channel safety
- Use `callback=` and `error_callback=` on `apply_async()` to schedule ack/retry back on listener

## Q7: ConsumerMixin — NOT the Right Tool (HIGH confidence)

`ConsumerMixin.run()` owns its own event loop and calls `ensure_connection()` directly. Using it inside a bootstep creates a conflicting event loop.

However, `ConsumerMixin.get_consumers(Consumer, channel)` is architecturally identical to existing `get_handlers(channel)` — validates current design is correct.

## Critical Pitfalls

| Pitfall | Severity | Fix |
|---------|----------|-----|
| `_close()` doesn't clear `self.handlers = []` | HIGH | Add at end of `_close()` |
| `self.pool.apply_async(self.func(body))` synchronous | CRITICAL | Fix signature |
| All handlers share one channel; concurrent acks | MEDIUM | One channel per handler or serialize acks |
| Queue args mismatch raises 406 on reconnect | MEDIUM | Never change queue args without deleting first |
| Pool callback may hold stale channel after reconnect | MEDIUM | Guard ack with `common.ignore_errors()` |

---
*Research: 2026-03-11*
