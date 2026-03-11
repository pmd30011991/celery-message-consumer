"""
Unit tests for Phase 2 backpressure requirements: BACK-01, BACK-02, BACK-03.

These tests verify that PREFETCH_COUNT is derived from pool concurrency,
overridable via settings, and never passes 0 to consumer.qos().

TDD RED: These tests FAIL against the current code (PREFETCH_COUNT=1 hardcoded,
no pool-derived logic). That is the correct red-phase state.
"""
import pytest
from unittest.mock import MagicMock, patch

from event_consumer.handlers import AMQPRetryConsumerStep
from event_consumer.types import QueueKey, HandlerRegistration


def _build_step_and_c(pool_limit):
    """
    Helper: build a minimal AMQPRetryConsumerStep with one handler and a fake
    worker context 'c' whose pool.limit is set to pool_limit.

    Returns (step, c, mock_channel) so tests can call step.start(c) inside
    appropriate patches.
    """
    dummy_func = MagicMock(name='dummy_func')
    registry = {
        QueueKey(queue='test_queue', exchange='default'): HandlerRegistration(
            routing_key='test.key',
            queue_arguments={},
            handler=dummy_func,
        )
    }

    mock_parent = MagicMock(name='parent')
    step = AMQPRetryConsumerStep(mock_parent, tasks=registry)

    mock_worker_pool = MagicMock(name='worker_pool')
    if pool_limit is None:
        # Simulate pool with no .limit attribute
        del mock_worker_pool.limit
    else:
        mock_worker_pool.limit = pool_limit

    mock_connection = MagicMock(name='connection')
    mock_channel = MagicMock(name='channel')
    mock_connection.channel.return_value = mock_channel

    c = MagicMock(name='c')
    c.pool = mock_worker_pool
    c.connection = mock_connection

    return step, c, mock_channel


def _run_start(step, c, prefetch_count_setting):
    """
    Run step.start(c) with all Kombu internals patched and PREFETCH_COUNT
    set to the given value.
    """
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
             PREFETCH_COUNT=prefetch_count_setting,
             ACCEPT=['json'],
             RETRY_HEADER='x-retry-count',
             DEAD_LETTER_EXCHANGE={},
             BACKOFF_FUNC=None,
         ):
        step.start(c)


# ---------------------------------------------------------------------------
# BACK-01 -- PREFETCH_COUNT defaults to pool.limit when setting is 0
# ---------------------------------------------------------------------------

def test_prefetch_defaults_to_pool_limit():
    """
    BACK-01: When EVENT_CONSUMER_PREFETCH_COUNT is not set (settings.PREFETCH_COUNT=0),
    each handler's consumer.qos() must be called with prefetch_count=pool.limit.

    Expected: FAIL until Task 2 implements pool-derived logic.
    """
    step, c, mock_channel = _build_step_and_c(pool_limit=10)
    _run_start(step, c, prefetch_count_setting=0)

    assert len(step.handlers) == 1
    handler = step.handlers[0]

    # consumer.qos() must have been called with prefetch_count=10 (pool.limit)
    handler.consumer.qos.assert_called_once_with(prefetch_count=10)


# ---------------------------------------------------------------------------
# BACK-01 -- Operator override via explicit settings value
# ---------------------------------------------------------------------------

def test_prefetch_override_from_settings():
    """
    BACK-01: When settings.PREFETCH_COUNT is explicitly set to a non-zero value
    (e.g., 5), that value overrides pool.limit.

    Expected: FAIL until Task 2 implements pool-derived logic.
    """
    step, c, mock_channel = _build_step_and_c(pool_limit=10)
    _run_start(step, c, prefetch_count_setting=5)

    assert len(step.handlers) == 1
    handler = step.handlers[0]

    # consumer.qos() must use the explicit setting (5), not pool.limit (10)
    handler.consumer.qos.assert_called_once_with(prefetch_count=5)


# ---------------------------------------------------------------------------
# BACK-02 -- consumer.qos() receives pool-derived value, not hardcoded 1
# ---------------------------------------------------------------------------

def test_qos_called_with_pool_size():
    """
    BACK-02: After start(), each handler's consumer.qos() was called with
    prefetch_count equal to the pool-derived value (not hardcoded 1).

    Expected: FAIL until Task 2 implements pool-derived logic.
    """
    step, c, mock_channel = _build_step_and_c(pool_limit=8)
    _run_start(step, c, prefetch_count_setting=0)

    assert len(step.handlers) == 1
    handler = step.handlers[0]

    call_args = handler.consumer.qos.call_args
    assert call_args is not None, "consumer.qos() must have been called"

    # Extract the prefetch_count keyword argument
    actual_prefetch = call_args.kwargs.get('prefetch_count') \
        if call_args.kwargs else call_args[1].get('prefetch_count')

    assert actual_prefetch == 8, (
        f"consumer.qos() received prefetch_count={actual_prefetch}, "
        "expected 8 (pool.limit). Hardcoded 1 is wrong."
    )


# ---------------------------------------------------------------------------
# BACK-03 -- floor: resolved prefetch_count is never 0
# ---------------------------------------------------------------------------

def test_prefetch_floor_never_zero():
    """
    BACK-03: When pool.limit is None and settings.PREFETCH_COUNT is 0,
    the resolved prefetch_count must be 1 (not 0).

    AMQP treats prefetch_count=0 as "unlimited" -- disabling backpressure
    entirely, which is the exact problem we're solving.

    Expected: FAIL until Task 2 implements the floor guard.
    """
    step, c, mock_channel = _build_step_and_c(pool_limit=None)
    # pool has a .limit attribute but it is None
    c.pool.limit = None
    _run_start(step, c, prefetch_count_setting=0)

    assert len(step.handlers) == 1
    handler = step.handlers[0]

    call_args = handler.consumer.qos.call_args
    assert call_args is not None, "consumer.qos() must have been called"

    actual_prefetch = call_args.kwargs.get('prefetch_count') \
        if call_args.kwargs else call_args[1].get('prefetch_count')

    assert actual_prefetch == 1, (
        f"consumer.qos() received prefetch_count={actual_prefetch}, "
        "expected 1 (floor). Passing 0 disables AMQP backpressure."
    )


# ---------------------------------------------------------------------------
# BACK-03 -- floor: pool has no .limit attribute at all
# ---------------------------------------------------------------------------

def test_prefetch_pool_limit_none_falls_back():
    """
    BACK-03: When pool has no .limit attribute (getattr returns None) and
    settings.PREFETCH_COUNT is 0, the resolved prefetch_count must fall back to 1.

    Expected: FAIL until Task 2 implements the getattr fallback.
    """
    # _build_step_and_c(pool_limit=None) deletes the .limit attribute entirely
    step, c, mock_channel = _build_step_and_c(pool_limit=None)
    _run_start(step, c, prefetch_count_setting=0)

    assert len(step.handlers) == 1
    handler = step.handlers[0]

    call_args = handler.consumer.qos.call_args
    assert call_args is not None, "consumer.qos() must have been called"

    actual_prefetch = call_args.kwargs.get('prefetch_count') \
        if call_args.kwargs else call_args[1].get('prefetch_count')

    assert actual_prefetch == 1, (
        f"consumer.qos() received prefetch_count={actual_prefetch}, "
        "expected 1 (getattr fallback). pool has no .limit attribute."
    )
