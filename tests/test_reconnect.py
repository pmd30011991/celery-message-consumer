"""
Unit tests for reconnect hardening — Phase 3.

Covers:
  CONN-01: _close() resets self.handlers = []
  CONN-02: Pool callbacks guard closed-channel exceptions
  CONN-03: Blueprint restart produces clean handler set
  POOL-04: Prefork pool detected, inline fallback used

All tests in this file should FAIL before production fixes are applied (RED phase).
"""
import logging
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers: build a minimal AMQPRetryConsumerStep with mocked deps
# ---------------------------------------------------------------------------

def make_step(tasks=None):
    """
    Return a fresh AMQPRetryConsumerStep with mocked Kombu/bootstep internals.
    `tasks` defaults to a single task dict to avoid empty-handler edge cases.
    """
    from event_consumer.handlers import AMQPRetryConsumerStep, AMQPRetryHandler

    if tasks is None:
        from event_consumer.types import QueueKey, HandlerRegistration
        tasks = {
            QueueKey(queue='q1', exchange='default'): HandlerRegistration(
                routing_key='key1',
                queue_arguments={},
                handler=MagicMock(name='handler_func_1'),
            ),
            QueueKey(queue='q2', exchange='default'): HandlerRegistration(
                routing_key='key2',
                queue_arguments={},
                handler=MagicMock(name='handler_func_2'),
            ),
        }

    with patch('celery.bootsteps.StartStopStep.__init__', return_value=None):
        step = AMQPRetryConsumerStep(tasks=tasks)

    return step, tasks


def make_mock_c(pool=None):
    """Return a mock `c` (Celery consumer) object for start/stop calls."""
    mock_c = MagicMock(name='mock_c')
    mock_c.connection.channel.return_value = MagicMock(name='channel')
    mock_pool = pool if pool is not None else MagicMock(name='mock_pool')
    mock_pool.limit = 4
    mock_c.pool = mock_pool
    return mock_c


def make_mock_handler():
    """Return a mock AMQPRetryHandler with mocked consumer."""
    h = MagicMock(name='mock_handler')
    h.consumer.channel = MagicMock(name='consumer_channel')
    return h


# ---------------------------------------------------------------------------
# CONN-01: _close() resets self.handlers
# ---------------------------------------------------------------------------

class TestCloseResetsHandlers:
    """CONN-01: After _close(), self.handlers must be an empty list."""

    def test_close_resets_handlers(self):
        """_close() must set self.handlers = [] after cleanup loops."""
        step, tasks = make_step()
        mock_c = make_mock_c()

        # Manually populate handlers (simulating what start() would do)
        step.handlers = [make_mock_handler(), make_mock_handler()]
        assert len(step.handlers) == 2, "Pre-condition: handlers populated"

        with patch('kombu.common.ignore_errors'):
            step._close(mock_c, cancel_consumers=False)

        assert step.handlers == [], (
            "_close() must reset self.handlers = [] to prevent stale references after reconnect"
        )

    def test_close_resets_handlers_after_cancel(self):
        """_close() must reset handlers even when cancel_consumers=True."""
        step, tasks = make_step()
        mock_c = make_mock_c()

        step.handlers = [make_mock_handler()]

        with patch('kombu.common.ignore_errors'):
            step._close(mock_c, cancel_consumers=True)

        assert step.handlers == [], (
            "_close(cancel_consumers=True) must still reset self.handlers = []"
        )


# ---------------------------------------------------------------------------
# CONN-01 / CONN-03: Restart cycle produces no stale handlers
# ---------------------------------------------------------------------------

class TestRestartNoStaleHandlers:
    """CONN-01/CONN-03: stop()->start() produces exactly N handlers, not 2N."""

    def test_restart_no_stale_handlers(self):
        """After stop()->start() cycle, handler count matches registered task count."""
        step, tasks = make_step()
        n_tasks = len(tasks)
        mock_c = make_mock_c()

        # Patch everything Kombu-touching so start() runs without a broker
        with patch('kombu.Queue'), \
             patch('kombu.Exchange'), \
             patch('kombu.Producer'), \
             patch('kombu.Consumer'):

            # First start — populates handlers
            step.start(mock_c)
            assert len(step.handlers) == n_tasks, "After first start(), handler count == n_tasks"

            # stop() → _close() — must clear handlers
            with patch('kombu.common.ignore_errors'):
                step.stop(mock_c)

            assert step.handlers == [], "After stop(), handlers must be empty"

            # Second start on fresh channel — must produce exactly n_tasks handlers again
            mock_c2 = make_mock_c()
            step.start(mock_c2)
            assert len(step.handlers) == n_tasks, (
                "After stop()->start() cycle, handler count must equal n_tasks (not 2×n_tasks)"
            )


# ---------------------------------------------------------------------------
# CONN-02: Pool callback guards closed-channel exceptions
# ---------------------------------------------------------------------------

class TestOnPoolSuccessClosedChannel:
    """CONN-02: _on_pool_success must not propagate when ack() raises."""

    def test_on_pool_success_closed_channel(self, handler, mock_message):
        """If message.ack() raises (channel closed), no exception propagates."""
        msg = mock_message(retry_count=0)
        msg.ack.side_effect = Exception("channel closed by reconnect")

        body = {'data': 'test'}

        # Must NOT raise — exception is swallowed and logged as warning
        handler._on_pool_success(body, msg)  # Should complete without exception

    def test_on_pool_success_closed_channel_calls_django_cleanup(self, handler, mock_message):
        """Even when ack() raises, _django_cleanup is still called."""
        msg = mock_message(retry_count=0)
        msg.ack.side_effect = Exception("channel closed")

        body = {'data': 'test'}

        with patch.object(handler, '_django_cleanup') as mock_cleanup:
            handler._on_pool_success(body, msg)

        mock_cleanup.assert_called_once()


class TestOnPoolErrorClosedChannelRequeue:
    """CONN-02: _on_pool_error finally block must not propagate when requeue() raises."""

    def test_on_pool_error_closed_channel_requeue(self, handler, mock_message):
        """If message.requeue() raises in finally block, no exception propagates."""
        msg = mock_message(retry_count=0)
        msg.acknowledged = False
        msg.requeue.side_effect = Exception("channel closed by reconnect")

        body = {'data': 'test'}
        exc_info = (ValueError, ValueError("handler error"), None)

        # Must NOT raise — requeue failure is swallowed and logged as warning
        # _on_pool_error itself may re-raise the original exc, so we patch
        # retry/archive to avoid real AMQP ops
        with patch.object(handler, 'retry'), \
             patch.object(handler, 'archive'):
            handler._on_pool_error(body, msg, exc_info, retry_count=0)  # Should not raise

    def test_on_pool_error_requeue_failure_logs_warning(self, handler, mock_message, caplog):
        """Requeue failure in _on_pool_error finally block logs a warning."""
        msg = mock_message(retry_count=0)
        msg.acknowledged = False
        msg.requeue.side_effect = Exception("channel closed")

        body = {'data': 'test'}
        exc_info = (ValueError, ValueError("handler error"), None)

        with patch.object(handler, 'retry'), \
             patch.object(handler, 'archive'), \
             caplog.at_level(logging.WARNING):
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        # Should log a warning about the requeue failure
        assert any('requeue' in record.message.lower() or 'Could not' in record.message
                   for record in caplog.records), (
            "Expected a warning log about requeue failure, got: "
            + str([r.message for r in caplog.records])
        )


# ---------------------------------------------------------------------------
# POOL-04: Prefork pool guard
# ---------------------------------------------------------------------------

class TestPreforkGuardSetsPoolNone:
    """POOL-04: When pool is AsynPool instance, start() sets self.pool = None."""

    def test_prefork_guard_sets_pool_none(self):
        """With AsynPool as the pool, start() must set self.pool = None."""
        step, tasks = make_step()

        # Create a fake AsynPool class and instance
        FakeAsynPool = type('AsynPool', (), {'limit': 4})
        fake_pool = FakeAsynPool()
        mock_c = make_mock_c(pool=fake_pool)

        with patch('kombu.Queue'), \
             patch('kombu.Exchange'), \
             patch('kombu.Producer'), \
             patch('kombu.Consumer'), \
             patch('event_consumer.handlers.AMQPRetryConsumerStep.start.__code__',
                   wraps=None) if False else patch('celery.concurrency.asynpool.AsynPool',
                                                    FakeAsynPool, create=True):
            # Patch the import inside start() to return our FakeAsynPool
            with patch.dict('sys.modules', {
                'celery.concurrency.asynpool': MagicMock(AsynPool=FakeAsynPool)
            }):
                step.start(mock_c)

        assert step.pool is None, (
            "When pool is AsynPool instance, start() must set self.pool = None "
            "to trigger inline dispatch fallback"
        )

    def test_prefork_guard_logs_warning(self, caplog):
        """With AsynPool as the pool, start() logs a warning about prefork."""
        step, tasks = make_step()

        FakeAsynPool = type('AsynPool', (), {'limit': 4})
        fake_pool = FakeAsynPool()
        mock_c = make_mock_c(pool=fake_pool)

        with patch('kombu.Queue'), \
             patch('kombu.Exchange'), \
             patch('kombu.Producer'), \
             patch('kombu.Consumer'), \
             patch.dict('sys.modules', {
                 'celery.concurrency.asynpool': MagicMock(AsynPool=FakeAsynPool)
             }), \
             caplog.at_level(logging.WARNING):
            step.start(mock_c)

        assert any('prefork' in record.message.lower() or 'Prefork' in record.message
                   for record in caplog.records), (
            "Expected a warning about prefork pool, got: "
            + str([r.message for r in caplog.records])
        )


class TestPreforkGuardInlineFallback:
    """POOL-04: With prefork pool detected, handler.__call__ uses _inline_dispatch."""

    def test_prefork_guard_inline_fallback(self, handler, mock_message):
        """When handler.pool is None (prefork fallback), __call__ uses _inline_dispatch."""
        # Simulate what start() does after prefork guard: pool=None passed to handler
        handler.pool = None

        msg = mock_message(retry_count=0)
        body = {'data': 'test'}

        with patch.object(handler, '_inline_dispatch') as mock_inline:
            handler(body, msg)

        mock_inline.assert_called_once_with(body, msg, 0), (
            "_inline_dispatch must be called when handler.pool is None"
        )


# ---------------------------------------------------------------------------
# CONN-03: Blueprint restart clean state
# ---------------------------------------------------------------------------

class TestBlueprintRestartCleanState:
    """CONN-03: Full stop->start cycle leaves handlers list fresh (no stale refs)."""

    def test_blueprint_restart_clean_state(self):
        """After stop()->start(), handlers list contains fresh objects only."""
        step, tasks = make_step()
        n_tasks = len(tasks)
        mock_c = make_mock_c()

        with patch('kombu.Queue'), \
             patch('kombu.Exchange'), \
             patch('kombu.Producer'), \
             patch('kombu.Consumer'):

            # First start
            step.start(mock_c)
            first_handlers = list(step.handlers)
            assert len(first_handlers) == n_tasks

            # Blueprint stop (calls _close)
            with patch('kombu.common.ignore_errors'):
                step.stop(mock_c)

            assert step.handlers == [], "Handlers must be cleared after stop()"

            # Fresh connection for restart
            mock_c2 = make_mock_c()
            step.start(mock_c2)
            second_handlers = list(step.handlers)

        assert len(second_handlers) == n_tasks, (
            "After blueprint restart, handler count must match task count"
        )
        # Handlers must be new objects, not stale references from first start
        for first_h in first_handlers:
            assert first_h not in second_handlers, (
                "Stale handler reference from before stop() found in handlers after restart"
            )
