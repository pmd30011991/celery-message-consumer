# AMQP Heartbeat & Thread-Safety Research

**Research Date:** 2026-03-11

## Q1: How do AMQP heartbeats work — which thread sends them?

`py-amqp`'s `connection.heartbeat_tick()` is **not automatic**. There is no background timer. The Celery consumer's `drain_events()` loop calls `heartbeat_tick()` after each timeout on the **single listener thread**. Both reading messages and sending heartbeats happen on the same thread.

## Q2: What happens when the callback blocks?

The listener thread is occupied running `AMQPRetryHandler.__call__()`. `heartbeat_tick()` cannot be called until the callback returns. If the handler takes longer than `2 × heartbeat_interval` seconds (the RabbitMQ default is 120s with a 60s interval), RabbitMQ closes the TCP connection. Unacked messages are re-queued. Any subsequent `message.ack()` raises or silently fails.

**Current bug on line 346 makes this worse:**
```python
# WRONG — executes handler synchronously, then passes return value to apply_async
self.pool.apply_async(self.func(body))

# CORRECT — passes function and args; returns immediately if pool is async
self.pool.apply_async(self.func, args=(body,), callback=on_success, error_callback=on_error)
```

## Q3: How does Celery handle heartbeats with eventlet/gevent?

`eventlet.monkey_patch()` / `gevent.monkey_patch()` makes `drain_events()` cooperative — it yields to the hub on socket I/O. A heartbeat green thread can run while the listener yields. **However**: CPU-bound handlers that never yield will still starve the hub. Only I/O-bound handlers benefit automatically.

## Q4: Can we run heartbeats on a separate green thread?

Yes, for I/O-bound handlers:
```python
import eventlet

def heartbeat_loop(connection, interval):
    while True:
        eventlet.sleep(interval / 2)
        connection.heartbeat_tick()

# In AMQPRetryConsumerStep.start():
if c.connection.heartbeat:
    eventlet.spawn(heartbeat_loop, c.connection, c.connection.heartbeat)
```

For CPU-bound handlers, use `eventlet.tpool.execute()` (real OS thread) and bridge acks back to the hub via an `eventlet.Queue`.

## Q5: Thread-safety constraints of Connection and Channel objects

`amqp.Connection` and `amqp.Channel` are **not OS-thread-safe** — no internal locks. Under eventlet/gevent, green threads on the **same OS thread** are safe because cooperative scheduling prevents simultaneous access. Operations from a real OS thread (e.g., `eventlet.tpool`) on the same channel are **unsafe** and must be bridged back to the hub.

## Q6: Is it safe to ack from a different green thread?

- **Green thread (`eventlet.spawn`)**: Safe — same OS thread, cooperative scheduling prevents races.
- **Real OS thread (`eventlet.tpool`)**: Unsafe — must queue the ack back to the hub before calling `message.ack()`.
- **Celery pool callback**: Safe if the pool is eventlet/gevent (callbacks run on the hub). Needs validation — the `callback=` and `error_callback=` parameters to `apply_async` are the correct integration point.

## Key Implications for Architecture

1. The current `self.pool.apply_async(self.func(body))` call is **synchronous** — it calls `self.func(body)` first (blocking), then passes the return value to `apply_async`. This is the root cause.
2. Fix must change to `self.pool.apply_async(self.func, args=(body,))` to truly dispatch async.
3. Acking must happen in pool callbacks, not inline after the handler call.
4. A heartbeat green thread is recommended as a safety net.
5. All ack/nack operations from pool callbacks are safe under eventlet/gevent since they run on the same OS thread (the hub).

---
*Research: 2026-03-11*
