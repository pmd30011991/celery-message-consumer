# Pool Dispatch Research: Celery Eventlet/Gevent Pool Integration

**Domain:** Celery bootstep → pool dispatch for Kombu consumers
**Researched:** 2026-03-11
**Overall Confidence:** MEDIUM-HIGH

## Executive Summary

The project already has the structural plumbing — `self.pool = c.pool` is captured in `AMQPRetryConsumerStep.start()` (line 170). The critical bug is on line 346:

```python
# WRONG — executes func(body) synchronously, then passes return value to apply_async
self.pool.apply_async(self.func(body))

# CORRECT — passes callable + args tuple; pool executes them asynchronously
self.pool.apply_async(self.func, args=(body,))
```

But fixing the call signature is only step one. Dispatching to the pool creates four interrelated problems:
1. The `apply_async` signature — how to call it correctly
2. Ack timing — message must be acked *after* pool task completes
3. Error propagation — exceptions in pool must feed retry/archive logic
4. Thread/greenlet safety — Kombu channel ops must run on the listener thread

## 1. Celery Pool Internals

### BasePool.apply_async Signature (HIGH confidence — Celery 4.x/5.x)

```python
BasePool.apply_async(
    target,              # Callable — the function to call in the pool
    args=(),             # tuple — positional arguments
    kwargs={},           # dict — keyword arguments
    callback=None,       # Callable(result) — called on SUCCESS
    error_callback=None, # Callable(exc_info) — called on FAILURE with sys.exc_info()
)
```

### EventletPool internals

Wraps eventlet's `GreenPool`. `spawn()` returns a `GreenThread` immediately. All greenlets share a single OS thread via cooperative scheduling. The listener greenlet is free to loop back for heartbeats.

## 2. Correct apply_async from Bootstep

Pass pool to handlers:
```python
def get_handlers(self, channel):
    return [
        AMQPRetryHandler(..., pool=self.pool)
        for queue_key, handler_registration in self._tasks.items()
    ]
```

The fix with callbacks:
```python
self.pool.apply_async(
    target=self.func,
    args=(body,),
    callback=lambda result, b=body, m=message: self._on_pool_success(b, m),
    error_callback=lambda exc_info, b=body, m=message, rc=retry_count:
        self._on_pool_error(b, m, exc_info, rc),
)
```

## 3. Ack Timing — Defer to Callbacks

```python
def _on_pool_success(self, body, message):
    try:
        message.ack()
    except Exception:
        _logger.warning("Could not ack message for '%s'", self.routing_key, exc_info=True)
    finally:
        self._django_cleanup()

def _on_pool_error(self, body, message, exc_info, retry_count):
    exc_type, exc_value, tb = exc_info
    try:
        if isinstance(exc_value, PermanentFailure):
            self.archive(body, message, ...)
        elif retry_count >= settings.MAX_RETRIES:
            self.archive(body, message, ...)
        else:
            self.retry(body, message, ...)
    finally:
        self._django_cleanup()
        if not message.acknowledged:
            message.requeue()
```

## 4. Thread/Greenlet Safety

Under eventlet/gevent with prefetch_count=1: safe — only one message in-flight. With prefetch_count > 1: need eventlet Queue to route Kombu ops back to listener.

**Recommendation:** Start with prefetch_count=1 (existing default).

## 5. Celery's Own Pattern (Reference)

```python
# celery/worker/strategy.py (Celery 4.x)
pool.apply_async(
    execute_and_trace,
    args=(task_name, uuid, args, kwargs, request),
    callback=on_ack,
    error_callback=on_ack,
)
```

Celery's own code defers ack to callbacks — same pattern.

## 6. Prefork Guard

```python
try:
    from celery.concurrency.asynpool import AsynPool
    if isinstance(pool, AsynPool):
        _logger.warning("Prefork pool detected. Use -P eventlet or -P gevent.")
        pool = None
except ImportError:
    pass
```

## 7. Critical Pitfalls

| Pitfall | Severity | Fix |
|---------|----------|-----|
| Lambda late binding | CRITICAL | Use default args: `lambda result, b=body, m=message:` |
| apply_async on prefork deadlocks | HIGH | Prefork guard, fallback to inline |
| Retry count must be captured before dispatch | HIGH | Capture at top of `__call__` |
| Channel closure during in-flight callbacks | MEDIUM | Wrap channel ops in try/except |
| error_callback signature differs in Celery 3.x | MEDIUM | Verify against installed version |

## 8. Minimal Implementation Checklist

1. Add `pool` parameter to `AMQPRetryHandler.__init__`
2. Pass `pool=self.pool` from `get_handlers`
3. Add prefork guard
4. Replace `self.pool.apply_async(self.func(body))` with correct call + callbacks
5. Remove inline `message.ack()` and `finally` safety net from `__call__`
6. Implement `_on_pool_success` and `_on_pool_error`
7. Move Django cleanup into callbacks
8. Add channel-close guard in callbacks
9. Add inline fallback when pool is None

## 9. Confidence Assessment

| Area | Confidence |
|------|------------|
| `c.pool` is correct pool reference | HIGH |
| `apply_async(target, args, callback, error_callback)` | HIGH |
| callback/error_callback semantics | HIGH |
| error_callback receives sys.exc_info() | MEDIUM (verify for Celery 3.x) |
| Greenlet safety at prefetch_count=1 | MEDIUM |

---
*Research: 2026-03-11*
