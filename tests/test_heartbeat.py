"""
Unit tests for Phase 4 requirements: BEAT-01 and BEAT-02.

Heartbeat safety-net greenlet — ensures AMQP heartbeat frames are sent
even when the listener thread is busy dispatching messages.

RED phase: all tests fail until _heartbeat_loop and _heartbeat_greenlet
are added to event_consumer/handlers.py.
"""
import pytest
from unittest.mock import MagicMock, patch, call


class _StopLoop(BaseException):
    """Sentinel raised in tests to break the heartbeat loop after one iteration."""


# ---------------------------------------------------------------------------
# Helpers: build a minimal AMQPRetryConsumerStep with mocked deps
# ---------------------------------------------------------------------------

def make_step(tasks=None):
    """
    Return a fresh AMQPRetryConsumerStep with mocked bootstep internals.
    """
    from event_consumer.handlers import AMQPRetryConsumerStep

    if tasks is None:
        from event_consumer.types import QueueKey, HandlerRegistration
        tasks = {
            QueueKey(queue='hb_queue', exchange='default'): HandlerRegistration(
                routing_key='heartbeat.key',
                queue_arguments={},
                handler=MagicMock(name='hb_handler_func'),
            ),
        }

    with patch('celery.bootsteps.StartStopStep.__init__', return_value=None):
        step = AMQPRetryConsumerStep(tasks=tasks)

    return step


def make_mock_c(heartbeat=60):
    """
    Return a mock `c` (Celery consumer) object for start() calls.

    heartbeat: int value for c.connection.heartbeat (0 or None = disabled).
    """
    mock_c = MagicMock(name='mock_c')
    mock_c.connection.channel.return_value = MagicMock(name='channel')
    mock_c.connection.heartbeat = heartbeat
    mock_c.connection.heartbeat_tick = MagicMock(name='heartbeat_tick')
    mock_pool = MagicMock(name='mock_pool')
    mock_pool.limit = 4
    mock_c.pool = mock_pool
    return mock_c


# ---------------------------------------------------------------------------
# BEAT-01: Greenlet spawned when heartbeat is enabled
# ---------------------------------------------------------------------------

class TestHeartbeatGreenletSpawned:
    """BEAT-01: start() spawns a heartbeat greenlet when heartbeat is non-zero."""

    def test_heartbeat_greenlet_spawned_when_heartbeat_set(self):
        """
        BEAT-01: When c.connection.heartbeat is non-zero, start() spawns a greenlet
        and stores it as self._heartbeat_greenlet.
        """
        step = make_step()
        mock_c = make_mock_c(heartbeat=60)

        mock_greenlet = MagicMock(name='mock_greenlet')

        with patch('kombu.Queue'), \
             patch('kombu.Exchange'), \
             patch('kombu.Producer'), \
             patch('kombu.Consumer'), \
             patch('event_consumer.handlers._spawn', return_value=mock_greenlet) as mock_spawn:

            step.start(mock_c)

        # _spawn must have been called with _heartbeat_loop and the connection + interval
        assert mock_spawn.called, "_spawn must be called when heartbeat is enabled"

        # The returned greenlet must be stored on step
        assert step._heartbeat_greenlet is mock_greenlet, (
            "start() must store spawned greenlet as self._heartbeat_greenlet"
        )

    def test_no_heartbeat_greenlet_when_heartbeat_zero(self):
        """
        BEAT-01: When c.connection.heartbeat is 0, start() must NOT spawn a greenlet.
        self._heartbeat_greenlet must remain None.
        """
        step = make_step()
        mock_c = make_mock_c(heartbeat=0)

        with patch('kombu.Queue'), \
             patch('kombu.Exchange'), \
             patch('kombu.Producer'), \
             patch('kombu.Consumer'), \
             patch('event_consumer.handlers._spawn') as mock_spawn:

            step.start(mock_c)

        assert not mock_spawn.called, (
            "_spawn must NOT be called when c.connection.heartbeat is 0"
        )
        assert step._heartbeat_greenlet is None, (
            "self._heartbeat_greenlet must remain None when heartbeat is disabled"
        )

    def test_no_heartbeat_greenlet_when_heartbeat_none(self):
        """
        BEAT-01: When c.connection.heartbeat is None, start() must NOT spawn a greenlet.
        """
        step = make_step()
        mock_c = make_mock_c(heartbeat=None)

        with patch('kombu.Queue'), \
             patch('kombu.Exchange'), \
             patch('kombu.Producer'), \
             patch('kombu.Consumer'), \
             patch('event_consumer.handlers._spawn') as mock_spawn:

            step.start(mock_c)

        assert not mock_spawn.called, (
            "_spawn must NOT be called when c.connection.heartbeat is None"
        )
        assert step._heartbeat_greenlet is None, (
            "self._heartbeat_greenlet must remain None when heartbeat is None"
        )


# ---------------------------------------------------------------------------
# BEAT-02: Greenlet killed in _close()
# ---------------------------------------------------------------------------

class TestHeartbeatGreenletKilledOnClose:
    """BEAT-02: _close() kills the heartbeat greenlet and sets it to None."""

    def test_heartbeat_greenlet_killed_on_close(self):
        """
        BEAT-02: After start() with heartbeat enabled, calling _close() kills
        the greenlet and sets self._heartbeat_greenlet to None.
        """
        step = make_step()
        mock_c = make_mock_c(heartbeat=60)

        mock_greenlet = MagicMock(name='mock_greenlet')

        with patch('kombu.Queue'), \
             patch('kombu.Exchange'), \
             patch('kombu.Producer'), \
             patch('kombu.Consumer'), \
             patch('event_consumer.handlers._spawn', return_value=mock_greenlet):

            step.start(mock_c)

        assert step._heartbeat_greenlet is mock_greenlet, (
            "Pre-condition: _heartbeat_greenlet set after start()"
        )

        with patch('kombu.common.ignore_errors'):
            step._close(mock_c, cancel_consumers=False)

        mock_greenlet.kill.assert_called_once(), (
            "_close() must call .kill() on _heartbeat_greenlet"
        )
        assert step._heartbeat_greenlet is None, (
            "_close() must set self._heartbeat_greenlet = None after killing"
        )

    def test_close_before_start_no_error(self):
        """
        BEAT-02: Calling _close() before start() must not raise AttributeError.
        self._heartbeat_greenlet must be initialized to None in __init__.
        """
        step = make_step()
        mock_c = make_mock_c(heartbeat=60)

        # _close() called without ever calling start() first — must not crash
        with patch('kombu.common.ignore_errors'):
            step._close(mock_c, cancel_consumers=False)  # Must not raise AttributeError


# ---------------------------------------------------------------------------
# BEAT-01: _heartbeat_loop calls heartbeat_tick at interval/2 cadence
# ---------------------------------------------------------------------------

class TestHeartbeatLoopBehavior:
    """BEAT-01: _heartbeat_loop calls connection.heartbeat_tick() after sleeping interval/2."""

    def test_heartbeat_tick_called(self):
        """
        The _heartbeat_loop function must:
        1. Sleep for interval/2
        2. Call connection.heartbeat_tick()
        3. Loop until GreenletExit

        We run one iteration then raise GreenletExit to stop the loop.
        Mock eventlet.sleep to count calls and raise GreenletExit after the first iteration.
        """
        from event_consumer.handlers import _heartbeat_loop

        mock_connection = MagicMock(name='connection')
        interval = 60
        sleep_calls = []

        def mock_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 2:
                # Stop after the second sleep call (i.e., after one full iteration
                # of: sleep -> tick -> sleep -> STOP)
                raise _StopLoop()

        with patch('event_consumer.handlers._sleep', side_effect=mock_sleep):
            try:
                _heartbeat_loop(mock_connection, interval)
            except _StopLoop:
                pass  # Expected: loop terminated after first full iteration

        # Sleep must have been called with interval/2
        assert len(sleep_calls) >= 1, "_sleep must be called at least once"
        assert sleep_calls[0] == interval / 2, (
            f"_sleep must be called with interval/2={interval/2}, got {sleep_calls[0]}"
        )

        # heartbeat_tick must have been called
        mock_connection.heartbeat_tick.assert_called(), (
            "connection.heartbeat_tick() must be called after sleeping"
        )
