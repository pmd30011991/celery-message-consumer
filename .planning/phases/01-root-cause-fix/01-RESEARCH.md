# Phase 1: Root Cause Fix - Research

**Researched:** 2026-03-11
**Domain:** Celery pool dispatch / Kombu AMQP ack lifecycle / eventlet greenlet callback safety
**Confidence:** HIGH (core fix pattern confirmed by Celery source; MEDIUM on error_callback signature in Celery 3.x)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| POOL-01 | Message handler execution dispatched to Celery's eventlet/gevent pool via correct `apply_async(target, args)` signature | `BasePool.apply_async` signature confirmed HIGH confidence; correct call form documented in Celery source |
| POOL-02 | `AMQPRetryHandler` receives pool reference from `AMQPRetryConsumerStep` | `self.pool = c.pool` already set in `start()` (line 170); handler needs a `pool=` parameter added to `__init__` and `get_handlers()` |
| POOL-03 | Listener thread returns to `drain_events()` immediately after dispatching | Follows directly from POOL-01 fix; eventlet GreenPool's `spawn()` returns immediately |
| POOL-05 | Existing `@message_handler` decorator and `AMQPRetryConsumerStep` registration API unchanged | `@message_handler` decorator untouched; internal wiring change only; confirmed no public API change needed |
| ACK-01 | Messages acked only after successful handler completion in pool | Ack moves from inline `else` block to `_on_pool_success` callback |
| ACK-02 | Failed messages trigger retry or archive via pool callbacks — same semantics as current | Error handling logic moves from inline `except` block to `_on_pool_error` callback |
| ACK-03 | Unacknowledged messages requeued on handler crash or connection loss | Safety-net `if not message.acknowledged: message.requeue()` moved into `_on_pool_error` finally block; AMQP guarantees requeue on connection loss |
| ACK-04 | Lambda captures in callbacks use default-argument binding to avoid late-binding bugs | `lambda result, b=body, m=message:` pattern mandatory; documented pitfall in research |
| ACK-05 | `retry_count` captured from message headers before pool dispatch | Already captured at top of `__call__` (line 337); must remain before `apply_async` call |
</phase_requirements>

---

## Summary

The single root-cause bug is on line 346 of `event_consumer/handlers.py`:

```python
self.pool.apply_async(self.func(body))
```

This calls `self.func(body)` synchronously (blocking the listener thread) and passes the return value — not the function — to `apply_async`. The pool never receives work to dispatch. The listener thread blocks for the full handler duration, starving the `drain_events()` heartbeat loop.

The fix is a targeted, surgical change to `AMQPRetryHandler.__call__`: pass `target=self.func` and `args=(body,)` with deferred ack/retry/archive logic in `callback=` and `error_callback=` parameters. All downstream side effects (ack, retry, archive, Django cleanup) move from inline code into two new methods: `_on_pool_success` and `_on_pool_error`. No public API changes are required; `@message_handler` and `AMQPRetryConsumerStep` remain stable.

Three decisions from prior research are locked and must be respected: (1) use the `callback=`/`error_callback=` pattern (not a closure wrapper), (2) use default-argument lambda capture to avoid late-binding bugs, (3) capture `retry_count` before `apply_async`. The Celery 3.x `error_callback` signature is a known MEDIUM-confidence risk that needs a version check or defensive unpacking.

**Primary recommendation:** Fix `apply_async` call signature, wire `callback=` / `error_callback=` parameters, implement `_on_pool_success` and `_on_pool_error`, and move all post-execution side effects into those callbacks.

---

## Standard Stack

### Core (no new dependencies needed)

| Library | Version | Purpose | Already Present |
|---------|---------|---------|----------------|
| celery | 3.x / 4.x | `BasePool.apply_async` with callback support | Yes — install_requires |
| kombu | 3.x / 4.x | AMQP message, ack, Consumer, Producer | Yes — via celery |
| amqp | any | Channel/Connection objects | Yes — via kombu |
| kombu.common | any | `ignore_errors()` utility | Yes — already imported |
| six | 1.x | Python 2/3 compat (`string_types`) | Yes — used in decorator |

**No new packages to install.** Phase 1 is a pure refactor of existing code.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `callback=` / `error_callback=` on `apply_async` | Closure wrapping ack inside `worker_task` | Both are safe; callback pattern preferred — mirrors Celery internals, separates concerns, named methods are easier to test |
| Default-arg lambda capture | `functools.partial` | Both prevent late binding; lambda is idiomatic for inline callbacks of this length |

---

## Architecture Patterns

### Recommended Project Structure

No directory changes. All modifications are within `event_consumer/handlers.py`.

### Pattern 1: Correct `apply_async` Dispatch with Deferred Callbacks

**What:** Pass the callable and args separately; wire pool callbacks for all post-execution side effects.
**When to use:** Always — this is the only correct way to dispatch to Celery's pool.
**Source:** `celery/worker/strategy.py` (`execute_and_trace` dispatch pattern)

```python
# In AMQPRetryHandler.__call__
def __call__(self, body, message):
    retry_count = self.retry_count(message)  # ACK-05: capture BEFORE dispatch

    _logger.debug(
        'Received: (key=%s, retry_count=%s)',
        self.routing_key,
        retry_count,
    )

    if self.pool is None:
        # Inline fallback (pool not available — e.g. prefork guard, Phase 3)
        self._inline_dispatch(body, message, retry_count)
        return

    self.pool.apply_async(
        target=self.func,
        args=(body,),
        callback=lambda result, b=body, m=message: (  # ACK-04: default-arg capture
            self._on_pool_success(b, m)
        ),
        error_callback=lambda exc_info, b=body, m=message, rc=retry_count: (
            self._on_pool_error(b, m, exc_info, rc)
        ),
    )
    # Listener thread returns here immediately (POOL-03)
```

### Pattern 2: Pool Success Callback (`_on_pool_success`)

**What:** Called by the pool hub after the handler function completes without raising.
**When to use:** Replace the current `else: message.ack()` block.

```python
def _on_pool_success(self, body, message):
    """Called by pool hub after successful handler execution."""
    try:
        message.ack()  # ACK-01: ack only after handler completes
        _logger.debug(
            "Task '%s' processed and ack() sent", self.routing_key
        )
    except Exception:
        _logger.warning(
            "Could not ack message for '%s'", self.routing_key, exc_info=True
        )
    finally:
        self._django_cleanup()
```

### Pattern 3: Pool Error Callback (`_on_pool_error`)

**What:** Called by the pool hub when the handler function raises any exception.
**When to use:** Replace the current `except Exception` block.

```python
def _on_pool_error(self, body, message, exc_info, retry_count):
    """Called by pool hub after handler raises an exception."""
    # exc_info is sys.exc_info() tuple: (type, value, traceback)
    # Celery 4.x/5.x confirmed; Celery 3.x — see Open Questions
    exc_type, exc_value, tb = exc_info

    try:
        if isinstance(exc_value, PermanentFailure):
            self.archive(
                body, message,
                "Task '{key}' raised '{cls}, {err}'\n{tb}".format(
                    key=self.routing_key,
                    cls=exc_type.__name__,
                    err=exc_value,
                    tb=traceback.format_tb(tb),
                )
            )
        elif retry_count >= settings.MAX_RETRIES:
            self.archive(
                body, message,
                "Task '{key}' ran out of retries ({n}) on exception '{cls}, {err}'\n{tb}".format(
                    key=self.routing_key,
                    n=retry_count,
                    cls=exc_type.__name__,
                    err=exc_value,
                    tb=traceback.format_tb(tb),
                )
            )
        else:
            self.retry(
                body, message,
                "Task '{key}' raised '{cls}, {err}', {left} retries left\n{tb}".format(
                    key=self.routing_key,
                    cls=exc_type.__name__,
                    err=exc_value,
                    left=settings.MAX_RETRIES - retry_count,
                    tb=traceback.format_tb(tb),
                )
            )
    finally:
        self._django_cleanup()
        if not message.acknowledged:  # ACK-03: safety-net requeue
            message.requeue()
            _logger.critical(
                "Message for task '%s' unacknowledged after error callback — requeueing.",
                self.routing_key,
            )
```

### Pattern 4: Django Cleanup Extracted to Helper

**What:** Both callbacks need Django cleanup; extract to avoid duplication.

```python
def _django_cleanup(self):
    """Send Django request_finished signal if USE_DJANGO is enabled."""
    if settings.USE_DJANGO:
        request_finished.send(sender="AMQPRetryHandler")
```

### Pattern 5: Pool Reference Wired Through `get_handlers`

**What:** `self.pool` is already captured in `start()` (line 170). Pass it into each handler at construction.

```python
# In AMQPRetryConsumerStep.get_handlers()
def get_handlers(self, channel):
    return [
        AMQPRetryHandler(
            channel=channel,
            routing_key=handler_registration.routing_key,
            queue=queue_key.queue,
            exchange=queue_key.exchange,
            queue_arguments=handler_registration.queue_arguments,
            func=handler_registration.handler,
            backoff_func=settings.BACKOFF_FUNC,
            pool=self.pool,   # <-- new parameter (POOL-02)
        )
        for queue_key, handler_registration in self._tasks.items()
    ]
```

```python
# In AMQPRetryHandler.__init__() — add pool parameter
def __init__(self,
             channel,
             routing_key,
             queue,
             exchange,
             queue_arguments,
             func,
             backoff_func=None,
             pool=None,        # <-- new parameter (POOL-02)
             ):
    ...
    self.pool = pool
```

### Anti-Patterns to Avoid

- **Calling `self.func(body)` inside `apply_async`:** This is the current bug. `apply_async(self.func(body))` evaluates the function immediately, passing its return value (likely `None`) to the pool. Always pass the callable and args separately.
- **Acking inline after `apply_async` returns:** With the correct async dispatch, the handler has not yet completed when `apply_async` returns. Any `message.ack()` placed after the call (outside a callback) will ack before the handler finishes — breaking at-least-once delivery.
- **Lambda without default-arg capture:** `lambda result: self._on_pool_success(body, message)` captures `body` and `message` by reference. If multiple messages are dispatched before callbacks fire, all callbacks will reference the last message. Use `lambda result, b=body, m=message:` to capture by value.
- **Reading `retry_count` inside the callback:** Message headers may not be accessible in pool greenlet context. `retry_count` must be read in `__call__` before `apply_async`.
- **Removing the safety-net `if not message.acknowledged: message.requeue()` without replacement:** This guard belongs in `_on_pool_error`'s `finally` block. It must not be simply deleted.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Deferring ack to after async work | Custom queue or future-based tracking | `callback=` / `error_callback=` on `apply_async` | Celery's pool already supports this natively; custom tracking adds concurrency complexity |
| Swallowing channel errors on ack | Bare try/except around `message.ack()` | `kombu.common.ignore_errors()` | Already imported; handles all Kombu/AMQP exception variants correctly |
| Exception unpacking from pool | Custom exception wrapper | `sys.exc_info()` tuple from `error_callback` parameter | Celery passes this directly; no additional unpacking layer needed |

**Key insight:** Celery's `BasePool.apply_async` `callback=` / `error_callback=` parameters were designed precisely for deferred ack patterns. This is not a workaround — it is the intended integration point, as confirmed by `celery/worker/strategy.py`.

---

## Common Pitfalls

### Pitfall 1: Lambda Late Binding
**What goes wrong:** `lambda result: self._on_pool_success(body, message)` captures `body` and `message` from the enclosing scope by reference. Under eventlet, all greenlets share the same OS thread. If a second message arrives and `__call__` runs before the first callback fires, `body` and `message` in the lambda now point to the second message. The first message gets silently mis-acked.
**Why it happens:** Python closures bind to the variable, not its value at the time of closure creation.
**How to avoid:** Use default-argument binding: `lambda result, b=body, m=message: self._on_pool_success(b, m)`. Default arguments are evaluated at definition time, capturing the current value.
**Warning signs:** Two messages processed; only one ack received; or wrong message acked.

### Pitfall 2: `error_callback` Signature Differences (Celery 3.x vs 4.x/5.x)
**What goes wrong:** In Celery 4.x and 5.x, `error_callback` receives a `sys.exc_info()` tuple `(exc_type, exc_value, traceback)`. In Celery 3.x, the signature may differ — the callback may receive only the exception value, or the tuple format may be different.
**Why it happens:** `BasePool` API evolved between major versions.
**How to avoid:** Add a defensive unpack with a version check:
```python
# Defensive unpack that works for both tuple and single-value forms:
if isinstance(exc_info, tuple):
    exc_type, exc_value, tb = exc_info
else:
    exc_type = type(exc_info)
    exc_value = exc_info
    tb = None
```
Or check `celery.__version__` at startup and branch accordingly.
**Warning signs:** `TypeError: cannot unpack non-sequence` in error callback path.

### Pitfall 3: Acking After `apply_async` Returns (Premature Ack)
**What goes wrong:** Developer places `message.ack()` after the `apply_async` call in `__call__`, reasoning that dispatch succeeded. But with correct async dispatch, the handler has not finished. The ack fires immediately, and if the handler subsequently fails, the message is lost — it was already acked.
**Why it happens:** Confusion between "dispatch succeeded" and "handler completed".
**How to avoid:** The ack must live exclusively in `_on_pool_success`. The `else` block and any `message.ack()` in `__call__` must be removed entirely.
**Warning signs:** Messages lost on handler failure; retry/archive logic never fires for successful dispatch.

### Pitfall 4: Safety-Net Requeue Fires Prematurely in Async Path
**What goes wrong:** The existing `finally` block in `__call__` contains `if not message.acknowledged: message.requeue()`. With async dispatch, the handler has not finished when `finally` runs, so `message.acknowledged` is `False`, and the message is requeued immediately — before the handler even runs.
**Why it happens:** The `finally` block in `__call__` runs when `apply_async` returns, not when the pool greenlet finishes.
**How to avoid:** Remove the `finally` block from `__call__`. Move the safety-net `if not message.acknowledged: message.requeue()` into `_on_pool_error`'s `finally` block. The inline-fallback path (`pool is None`) retains its own `finally` block.
**Warning signs:** Messages immediately requeued and reprocessed; `critical` log fires on every message.

### Pitfall 5: Django Cleanup in `__call__` Finally Instead of Callbacks
**What goes wrong:** If `request_finished.send()` is called in `__call__`'s `finally` block, it fires immediately after dispatch (before handler completion). Django DB connections are cleaned up while the handler is still running in the pool — causing `OperationalError: connection already closed`.
**Why it happens:** Same as Pitfall 4 — the finally block in `__call__` runs at dispatch time, not completion time.
**How to avoid:** Move Django cleanup into `_on_pool_success` and `_on_pool_error` finally blocks via the `_django_cleanup()` helper.

---

## Code Examples

### Current Broken Call (line 346)

```python
# SOURCE: event_consumer/handlers.py line 346
# WRONG: executes self.func(body) synchronously, passes return value to apply_async
self.pool.apply_async(self.func(body))
```

### Correct Dispatch Pattern

```python
# SOURCE: mirrors celery/worker/strategy.py execute_and_trace dispatch
self.pool.apply_async(
    target=self.func,
    args=(body,),
    callback=lambda result, b=body, m=message: self._on_pool_success(b, m),
    error_callback=lambda exc_info, b=body, m=message, rc=retry_count:
        self._on_pool_error(b, m, exc_info, rc),
)
```

### Celery's Own Reference Pattern

```python
# SOURCE: celery/worker/strategy.py (Celery 4.x)
pool.apply_async(
    execute_and_trace,
    args=(task_name, uuid, args, kwargs, request),
    callback=on_ack,
    error_callback=on_ack,
)
```

### `BasePool.apply_async` Signature

```python
# SOURCE: celery/concurrency/base.py
BasePool.apply_async(
    target,              # Callable — function to execute in pool
    args=(),             # tuple — positional arguments
    kwargs={},           # dict — keyword arguments
    callback=None,       # Callable(result) — called on SUCCESS
    error_callback=None, # Callable(exc_info) — called on FAILURE with sys.exc_info()
)
```

### `get_handlers` Updated Signature

```python
# In AMQPRetryConsumerStep.get_handlers()
def get_handlers(self, channel):
    return [
        AMQPRetryHandler(
            channel=channel,
            routing_key=handler_registration.routing_key,
            queue=queue_key.queue,
            exchange=queue_key.exchange,
            queue_arguments=handler_registration.queue_arguments,
            func=handler_registration.handler,
            backoff_func=settings.BACKOFF_FUNC,
            pool=self.pool,  # POOL-02
        )
        for queue_key, handler_registration in self._tasks.items()
    ]
```

### Inline Fallback Path (when pool is None)

```python
def _inline_dispatch(self, body, message, retry_count):
    """Execute handler inline when pool is unavailable (e.g. pool=None guard)."""
    try:
        self.func(body)
    except Exception as e:
        if isinstance(e, PermanentFailure):
            self.archive(body, message, ...)
        elif retry_count >= settings.MAX_RETRIES:
            self.archive(body, message, ...)
        else:
            self.retry(body, message, ...)
    else:
        message.ack()
    finally:
        self._django_cleanup()
        if not message.acknowledged:
            message.requeue()
            _logger.critical(...)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `apply_async(self.func(body))` — sync inline | `apply_async(target=func, args=..., callback=..., error_callback=...)` — async with deferred ack | Phase 1 (now) | Listener thread unblocked; heartbeats restored; pool actually used |
| Inline ack in `else` block of `__call__` | Ack in `_on_pool_success` callback | Phase 1 (now) | Ack only fires after handler completes in pool |
| Inline retry/archive in `except` block | Retry/archive in `_on_pool_error` callback | Phase 1 (now) | Error handling runs after pool task fails, not at dispatch time |
| Django cleanup in `__call__` `finally` | Cleanup in `_on_pool_success` / `_on_pool_error` via `_django_cleanup()` | Phase 1 (now) | Cleanup after actual handler completion, not at dispatch time |

**Deprecated patterns after Phase 1:**
- Inline `else: message.ack()` in `__call__` — replace entirely with callback
- Inline `except` handling in `__call__` — replace entirely with `_on_pool_error`
- `finally` block in `__call__` for safety-net requeue — move to `_on_pool_error`

---

## Open Questions

1. **`error_callback` signature in Celery 3.x**
   - What we know: Celery 4.x and 5.x pass a `sys.exc_info()` tuple `(type, value, traceback)` to `error_callback`. Celery 3.x source not independently verified.
   - What's unclear: Whether Celery 3.x passes the exception object directly or the full tuple.
   - Recommendation: Add defensive unpacking in `_on_pool_error`:
     ```python
     if isinstance(exc_info, tuple) and len(exc_info) == 3:
         exc_type, exc_value, tb = exc_info
     else:
         exc_type = type(exc_info)
         exc_value = exc_info
         tb = None
     ```
     Then add a note to the TEST-04 requirement (Phase 5) to verify under Celery 3.x.

2. **Whether pool callbacks run on the eventlet hub (same OS thread as channel ops)**
   - What we know: Under eventlet, `GreenPool.spawn()` executes in a greenlet on the same OS thread. Celery's eventlet pool wraps this. Channel/connection operations are not OS-thread-safe but are safe across greenlets on the same OS thread due to cooperative scheduling.
   - What's unclear: Whether `callback=` and `error_callback=` in `BasePool.apply_async` execute on the hub (listener) greenlet or in the pool greenlet. If they execute in the pool greenlet, channel operations such as `message.ack()` would still be safe (same OS thread), but this assumption should be confirmed empirically in Phase 5 (TEST-03).
   - Recommendation: Proceed with the callback pattern — either execution context is safe under eventlet/gevent due to the single-OS-thread cooperative model. Add a test assertion in Phase 5.

3. **Inline fallback scope for Phase 1**
   - What we know: POOL-04 (prefork guard with inline fallback) is assigned to Phase 3, not Phase 1.
   - What's unclear: Whether Phase 1 should include a minimal `pool is None` guard to allow the new code path to degrade gracefully without Phase 3's explicit prefork detection.
   - Recommendation: Include a minimal `if self.pool is None: self._inline_dispatch(...)` guard in Phase 1. This keeps the existing behavior for `pool=None` and makes Phase 1 deployable without requiring Phase 3.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (referenced in STACK.md; `py.test` runner) |
| Config file | `tox.ini` (not present in current checkout — Wave 0 gap) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| POOL-01 | `apply_async` receives callable + args tuple, not return value | unit | `pytest tests/test_handlers.py::test_apply_async_dispatches_callable -x` | Wave 0 |
| POOL-02 | Handler receives pool from `get_handlers` | unit | `pytest tests/test_handlers.py::test_handler_receives_pool -x` | Wave 0 |
| POOL-03 | `apply_async` call returns before handler completes | unit | `pytest tests/test_handlers.py::test_listener_returns_immediately -x` | Wave 0 |
| POOL-05 | `@message_handler` decorator API unchanged | unit | `pytest tests/test_handlers.py::test_decorator_api_unchanged -x` | Wave 0 |
| ACK-01 | `message.ack()` called in success callback, not inline | unit | `pytest tests/test_handlers.py::test_ack_in_success_callback -x` | Wave 0 |
| ACK-02 | `PermanentFailure` routes to archive in error callback | unit | `pytest tests/test_handlers.py::test_permanent_failure_archives -x` | Wave 0 |
| ACK-02 | Transient exception triggers retry in error callback | unit | `pytest tests/test_handlers.py::test_transient_exception_retries -x` | Wave 0 |
| ACK-02 | Exhausted retries route to archive in error callback | unit | `pytest tests/test_handlers.py::test_exhausted_retries_archives -x` | Wave 0 |
| ACK-03 | Unacknowledged message requeued in error callback finally | unit | `pytest tests/test_handlers.py::test_unacked_requeued_on_error -x` | Wave 0 |
| ACK-04 | Lambda default-arg capture prevents late-binding bugs | unit | `pytest tests/test_handlers.py::test_lambda_capture_correct_message -x` | Wave 0 |
| ACK-05 | `retry_count` captured before dispatch (not inside callback) | unit | `pytest tests/test_handlers.py::test_retry_count_captured_before_dispatch -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_handlers.py -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/__init__.py` — package marker
- [ ] `tests/test_handlers.py` — unit tests for all POOL-* and ACK-* requirements listed above
- [ ] `tests/conftest.py` — shared fixtures: mock pool, mock message, mock channel
- [ ] Framework config: `tox.ini` or `pytest.ini` (if not present after checkout inspection)

Test infrastructure must be created before implementation can be verified. No test directory present in current checkout (confirmed by CONCERNS.md).

---

## Sources

### Primary (HIGH confidence)

- `celery/worker/strategy.py` — `execute_and_trace` dispatch with `callback=on_ack, error_callback=on_ack` — confirms the callback pattern is Celery's own standard for deferred ack
- `celery/concurrency/base.py` — `BasePool.apply_async` signature — confirms `target`, `args`, `callback`, `error_callback` parameter names
- `event_consumer/handlers.py` (this codebase) — lines 170, 346, 337, 391-408 — exact bug location and current inline logic to be replaced
- `.planning/research/pool-dispatch.md` — pool dispatch pattern research (HIGH confidence)
- `.planning/research/heartbeat-safety.md` — greenlet ack safety analysis (HIGH confidence)
- `.planning/research/backpressure-ack.md` — ack deferral pattern alternatives (HIGH confidence)
- `.planning/research/SUMMARY.md` — consolidated findings and confidence assessment

### Secondary (MEDIUM confidence)

- `celery/concurrency/eventlet.py` — EventletPool wraps `eventlet.GreenPool`; callbacks run on hub (inferred from source structure, not directly verified for callback execution context)
- `kombu.common.ignore_errors` — documented utility; already imported in codebase

### Tertiary (LOW confidence — flagged for Phase 5 validation)

- Celery 3.x `error_callback` signature — assumed to match 4.x/5.x tuple form; not independently verified
- Callback execution context (hub vs pool greenlet) — theoretically safe under eventlet; empirical test needed

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — no new libraries; all changes are within existing imports
- Core fix pattern: HIGH — confirmed by Celery source (`strategy.py`) and four independent research files
- Architecture: HIGH — surgical changes to `AMQPRetryHandler.__call__`, `get_handlers`, and `__init__`; no structural redesign
- Pitfalls: HIGH — lambda late binding and premature ack are well-understood Python and async patterns
- Celery 3.x `error_callback` signature: MEDIUM — needs verification or defensive implementation

**Research date:** 2026-03-11
**Valid until:** 2026-04-10 (Celery/Kombu are stable; MEDIUM risk is on Celery 3.x edge case only)
