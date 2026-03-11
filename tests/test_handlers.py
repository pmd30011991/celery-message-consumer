"""
Unit tests for Phase 1 requirements: POOL-01/02/03/05 and ACK-01/02/03/04/05.

These tests describe the EXPECTED behaviour after the fix in Plan 02.
Tests that exercise the broken current code will FAIL intentionally --
that is the correct result for a TDD "RED" phase.
"""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# POOL-01 -- apply_async dispatches the callable, not its return value
# ---------------------------------------------------------------------------

def test_apply_async_dispatches_callable(handler, mock_pool, mock_message):
    """
    POOL-01: handler.__call__ must pass handler.func (the callable itself)
    as the target to pool.apply_async, not the result of calling it.

    Expected: FAIL until Plan 02 implements fix
    """
    body = {'key': 'value'}
    message = mock_message(retry_count=0)

    handler(body, message)

    assert mock_pool.apply_async.called, "pool.apply_async must be called"

    call_kwargs = mock_pool._last_call
    # target must be the callable, not its return value
    assert call_kwargs['target'] is handler.func, (
        "apply_async should receive handler.func as target, "
        "not handler.func(body) (the return value)"
    )
    # args should contain body
    assert call_kwargs['args'] == (body,), (
        "apply_async should be called with args=(body,)"
    )
    # The user's func must NOT have been called synchronously
    assert handler.func.call_count == 0, (
        "handler.func should not be invoked synchronously; "
        "the pool should call it asynchronously"
    )


# ---------------------------------------------------------------------------
# POOL-02 -- handler receives pool from AMQPRetryConsumerStep.get_handlers
# ---------------------------------------------------------------------------

def test_handler_receives_pool_from_get_handlers():
    """
    POOL-02: Each handler created by get_handlers must have its .pool attribute
    set to the worker's pool (c.pool), not None or missing.

    Expected: FAIL until Plan 02 wires pool= through get_handlers
    """
    import django
    from django.conf import settings as dj_settings
    if not dj_settings.configured:
        dj_settings.configure(DEBUG=True, DATABASES={}, INSTALLED_APPS=[])

    from event_consumer.handlers import AMQPRetryConsumerStep, AMQPRetryHandler

    # Build a minimal task registry with one handler
    from event_consumer.types import QueueKey, HandlerRegistration
    dummy_func = MagicMock(name='dummy_func')
    registry = {
        QueueKey(queue='test_queue', exchange='default'): HandlerRegistration(
            routing_key='test.key',
            queue_arguments={},
            handler=dummy_func,
        )
    }

    step = AMQPRetryConsumerStep(tasks=registry)

    # Build a fake consumer 'c' with pool and connection
    mock_worker_pool = MagicMock(name='worker_pool')
    mock_connection = MagicMock(name='connection')
    mock_channel = MagicMock(name='channel')
    mock_connection.channel.return_value = mock_channel
    c = MagicMock(name='c')
    c.pool = mock_worker_pool
    c.connection = mock_connection

    with patch('kombu.Queue'), \
         patch('kombu.Exchange'), \
         patch('kombu.Producer'), \
         patch('kombu.Consumer'), \
         patch.multiple(
             'event_consumer.settings',
             MAX_RETRIES=3,
             USE_DJANGO=False,
             EXCHANGES={'default': {'name': 'default', 'type': 'topic'}},
             ARCHIVE_QUEUE_ARGS={},
             QUEUE_NAME_PREFIX='',
             SERIALIZER='json',
             PREFETCH_COUNT=1,
             ACCEPT=['json'],
             RETRY_HEADER='x-retry-count',
             DEAD_LETTER_EXCHANGE={},
             BACKOFF_FUNC=None,
         ):
        step.start(c)

    assert len(step.handlers) == 1, "Expected exactly one handler"
    h = step.handlers[0]
    assert hasattr(h, 'pool'), "Handler must have a 'pool' attribute after start()"
    assert h.pool is mock_worker_pool, (
        "handler.pool should be set to c.pool by get_handlers/start"
    )


# ---------------------------------------------------------------------------
# POOL-03 -- listener thread returns immediately (no synchronous func call)
# ---------------------------------------------------------------------------

def test_listener_returns_immediately(handler, mock_pool, mock_message):
    """
    POOL-03: __call__ must return immediately without calling handler.func
    synchronously. The pool should call func asynchronously.

    Expected: FAIL until Plan 02 implements fix
    """
    body = {'data': 'test'}
    message = mock_message(retry_count=0)

    handler(body, message)

    # pool.apply_async was called (dispatched to pool)
    assert mock_pool.apply_async.called, "apply_async must be called"
    # func was NOT called directly
    assert not handler.func.called, (
        "handler.func must not be called synchronously; "
        "the pool greenlet should call it"
    )


# ---------------------------------------------------------------------------
# POOL-05 -- decorator API unchanged
# ---------------------------------------------------------------------------

def test_decorator_api_unchanged():
    """
    POOL-05: The @message_handler decorator must register functions in REGISTRY
    and return the original function unchanged.

    This test should PASS against the current code (decorator is not broken).
    """
    import event_consumer.handlers as handlers_module
    from event_consumer import message_handler

    original_registry = dict(handlers_module.REGISTRY)

    with patch.multiple(
        'event_consumer.settings',
        EXCHANGES={'myexchange': {'name': 'myexchange', 'type': 'topic'}},
        QUEUE_NAME_PREFIX='',
    ):
        @message_handler('pool05.test.key', queue='pool05_queue', exchange='myexchange')
        def dummy_handler(body):
            pass

    # The decorated function is returned unchanged
    assert dummy_handler.__name__ == 'dummy_handler'

    # The function appears in REGISTRY
    from event_consumer.types import QueueKey
    reg_key = QueueKey(queue='pool05_queue', exchange='myexchange')
    assert reg_key in handlers_module.REGISTRY, "Handler must be registered in REGISTRY"
    assert handlers_module.REGISTRY[reg_key].handler is dummy_handler

    # Cleanup
    del handlers_module.REGISTRY[reg_key]


# ---------------------------------------------------------------------------
# ACK-01 -- ack happens in success callback, not inline
# ---------------------------------------------------------------------------

def test_ack_in_success_callback(handler, mock_pool, mock_message):
    """
    ACK-01: message.ack() must NOT be called inline inside __call__.
    It must be called only when the success callback fires.

    Expected: FAIL until Plan 02 implements fix
    """
    body = {'key': 'val'}
    message = mock_message(retry_count=0)

    handler(body, message)

    # ack must NOT have been called yet (only scheduled via pool)
    assert not message.ack.called, (
        "message.ack() should not be called inline; "
        "it belongs in the pool success callback"
    )

    # Now fire the success callback
    callback = mock_pool._last_call['callback']
    assert callback is not None, "apply_async must receive a callback kwarg"
    callback('result')

    # Now ack must have been called exactly once
    assert message.ack.call_count == 1, (
        "message.ack() should be called exactly once after the success callback fires"
    )


# ---------------------------------------------------------------------------
# ACK-02 -- PermanentFailure routes to archive
# ---------------------------------------------------------------------------

def test_permanent_failure_archives(handler, mock_pool, mock_message):
    """
    ACK-02 (PermanentFailure path): When error_callback is invoked with
    a PermanentFailure exc_info, handler.archive must be called and
    handler.retry must NOT be called.

    Expected: FAIL until Plan 02 implements fix
    """
    from event_consumer.errors import PermanentFailure

    body = {'key': 'val'}
    message = mock_message(retry_count=0)

    handler(body, message)

    error_callback = mock_pool._last_call['error_callback']
    assert error_callback is not None, "apply_async must receive an error_callback kwarg"

    exc = PermanentFailure("bad data")
    exc_info = (PermanentFailure, exc, None)

    with patch.object(handler, 'archive') as mock_archive, \
         patch.object(handler, 'retry') as mock_retry:
        error_callback(exc_info)

    mock_archive.assert_called_once(), "archive() must be called for PermanentFailure"
    mock_retry.assert_not_called(), "retry() must NOT be called for PermanentFailure"


# ---------------------------------------------------------------------------
# ACK-02 -- transient exception with retries remaining -> retry
# ---------------------------------------------------------------------------

def test_transient_exception_retries(handler, mock_pool, mock_message):
    """
    ACK-02 (transient path): When error_callback receives a non-permanent
    exception and retries remain, handler.retry must be called.

    Expected: FAIL until Plan 02 implements fix
    """
    body = {'key': 'val'}
    message = mock_message(retry_count=0)  # 0 retries used, MAX_RETRIES=3

    handler(body, message)

    error_callback = mock_pool._last_call['error_callback']

    exc = ValueError("transient error")
    exc_info = (ValueError, exc, None)

    with patch.object(handler, 'retry') as mock_retry, \
         patch.object(handler, 'archive') as mock_archive:
        error_callback(exc_info)

    mock_retry.assert_called_once(), "retry() must be called for transient exception with retries left"
    mock_archive.assert_not_called(), "archive() must NOT be called when retries remain"


# ---------------------------------------------------------------------------
# ACK-02 -- exhausted retries -> archive
# ---------------------------------------------------------------------------

def test_exhausted_retries_archives(handler, mock_pool, mock_message):
    """
    ACK-02 (retries exhausted path): When retry_count >= MAX_RETRIES,
    handler.archive must be called.

    Expected: FAIL until Plan 02 implements fix
    """
    body = {'key': 'val'}
    message = mock_message(retry_count=3)  # retry_count == MAX_RETRIES

    handler(body, message)

    error_callback = mock_pool._last_call['error_callback']

    exc = ValueError("transient error")
    exc_info = (ValueError, exc, None)

    with patch.object(handler, 'archive') as mock_archive, \
         patch.object(handler, 'retry') as mock_retry:
        error_callback(exc_info)

    mock_archive.assert_called_once(), "archive() must be called when retries are exhausted"
    mock_retry.assert_not_called(), "retry() must NOT be called when retries are exhausted"


# ---------------------------------------------------------------------------
# ACK-03 -- unacked message requeued on error in callback
# ---------------------------------------------------------------------------

def test_unacked_requeued_on_error(handler, mock_pool, mock_message):
    """
    ACK-03: If the error handling itself raises (e.g., archive raises),
    and message is still unacknowledged, message.requeue() must be called
    as a safety net in the finally block of _on_pool_error.

    Expected: FAIL until Plan 02 implements fix
    """
    body = {'key': 'val'}
    message = mock_message(retry_count=0, acknowledged=False)

    handler(body, message)

    error_callback = mock_pool._last_call['error_callback']
    assert error_callback is not None

    exc = ValueError("transient")
    exc_info = (ValueError, exc, None)

    # Make archive raise so the safety net must kick in
    with patch.object(handler, 'archive', side_effect=RuntimeError("archive broken")), \
         patch.object(handler, 'retry', side_effect=RuntimeError("retry broken")):
        # The error_callback itself should not propagate the RuntimeError
        # (it should be caught internally), and requeue should fire
        try:
            error_callback(exc_info)
        except Exception:
            pass  # If it propagates, requeue still should have been called

    assert message.requeue.called, (
        "message.requeue() must be called when message is unacknowledged "
        "after error handling raises"
    )


# ---------------------------------------------------------------------------
# ACK-04 -- lambda capture: each callback acks the correct message
# ---------------------------------------------------------------------------

def test_lambda_capture_correct_message(handler, mock_pool, mock_message):
    """
    ACK-04: Two messages dispatched via the same handler must each carry
    their own closure-captured message reference. Firing callback 1 acks
    message1 only; firing callback 2 acks message2 only.

    Expected: FAIL until Plan 02 implements fix (default-arg capture)
    """
    body1 = {'id': 1}
    body2 = {'id': 2}
    message1 = mock_message(retry_count=0)
    message2 = mock_message(retry_count=0)

    # Dispatch first message
    handler(body1, message1)
    call1 = dict(mock_pool._last_call)  # snapshot

    # Dispatch second message
    handler(body2, message2)
    call2 = dict(mock_pool._last_call)  # snapshot

    # Fire callback 1 -- only message1 should be acked
    call1['callback']('result1')
    assert message1.ack.call_count == 1, "message1 must be acked after callback 1"
    assert message2.ack.call_count == 0, "message2 must NOT be acked after callback 1"

    # Fire callback 2 -- only message2 should be acked
    call2['callback']('result2')
    assert message2.ack.call_count == 1, "message2 must be acked after callback 2"
    assert message1.ack.call_count == 1, "message1 must not be double-acked"


# ---------------------------------------------------------------------------
# ACK-05 -- retry_count captured before dispatch
# ---------------------------------------------------------------------------

def test_retry_count_captured_before_dispatch(handler, mock_pool, mock_message):
    """
    ACK-05: The retry_count used in the error_callback must be the value
    captured at dispatch time (from message.headers), not read again later.

    We verify: dispatch with retry_count=2, then mutate message.headers,
    then invoke error_callback -- the error handling must still use 2.

    Expected: FAIL until Plan 02 implements fix
    """
    body = {'key': 'val'}
    message = mock_message(retry_count=2)  # 2 retries used -- 1 left (MAX=3)

    handler(body, message)

    # Mutate headers AFTER dispatch to simulate late-binding hazard
    message.headers['x-retry-count'] = 99  # would exhaust retries if re-read

    error_callback = mock_pool._last_call['error_callback']
    assert error_callback is not None

    exc = ValueError("transient")
    exc_info = (ValueError, exc, None)

    with patch.object(handler, 'retry') as mock_retry, \
         patch.object(handler, 'archive') as mock_archive:
        error_callback(exc_info)

    # retry_count was 2 at dispatch time, MAX_RETRIES=3, so retry() should fire
    mock_retry.assert_called_once(), (
        "retry() must be called because retry_count was 2 at dispatch time (< MAX_RETRIES=3). "
        "If archive() was called, retry_count was re-read after header mutation."
    )
    mock_archive.assert_not_called(), (
        "archive() must NOT be called -- retry_count captured at dispatch was 2, not 99"
    )
