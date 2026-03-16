"""
Unit tests for pool callback paths — Phase 5 Validation.

Covers:
  TEST-03: _on_pool_success and _on_pool_error callback correctness
  TEST-04: Celery version compatibility (3.x single-object vs 4.x/5.x tuple exc_info)

All tests call the callback methods directly (no pool dispatch needed).
No live broker required — all AMQP operations are mocked via conftest fixtures.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from event_consumer.errors import PermanentFailure


# ---------------------------------------------------------------------------
# TEST-03: _on_pool_success tests
# ---------------------------------------------------------------------------

class TestOnPoolSuccess:
    """TEST-03: _on_pool_success acks message and cleans up on all paths."""

    def test_success_acks_message(self, handler, mock_message):
        """_on_pool_success(body, message) calls message.ack() exactly once."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}

        handler._on_pool_success(body, msg)

        assert msg.ack.call_count == 1, (
            "_on_pool_success must call message.ack() exactly once"
        )

    def test_success_calls_django_cleanup(self, handler, mock_message):
        """_on_pool_success calls _django_cleanup() in finally block."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}

        with patch.object(handler, '_django_cleanup') as mock_cleanup:
            handler._on_pool_success(body, msg)

        mock_cleanup.assert_called_once()

    def test_success_closed_channel_no_crash(self, handler, mock_message):
        """When message.ack() raises Exception, _on_pool_success must not propagate."""
        msg = mock_message(retry_count=0)
        msg.ack.side_effect = Exception("channel closed")
        body = {'data': 'test'}

        # Must not raise — exception is swallowed and logged as warning
        handler._on_pool_success(body, msg)

    def test_success_closed_channel_still_cleans_up(self, handler, mock_message):
        """Even when ack() raises, _django_cleanup() is still called (finally block)."""
        msg = mock_message(retry_count=0)
        msg.ack.side_effect = Exception("channel closed")
        body = {'data': 'test'}

        with patch.object(handler, '_django_cleanup') as mock_cleanup:
            handler._on_pool_success(body, msg)

        mock_cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# TEST-03: _on_pool_error tests
# ---------------------------------------------------------------------------

class TestOnPoolError:
    """TEST-03: _on_pool_error routes to archive or retry based on exception type and retry count."""

    def test_permanent_failure_archives(self, handler, mock_message):
        """exc_info with PermanentFailure -> handler.archive() called, handler.retry() NOT called."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}
        exc_info = (PermanentFailure, PermanentFailure("bad message"), None)

        with patch.object(handler, 'archive') as mock_archive, \
             patch.object(handler, 'retry') as mock_retry:
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        mock_archive.assert_called_once()
        mock_retry.assert_not_called()

    def test_transient_retries_when_retries_left(self, handler, mock_message):
        """Transient ValueError with retry_count=0 (MAX_RETRIES=3) -> retry() called, archive() NOT called."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}
        exc_info = (ValueError, ValueError("transient error"), None)

        with patch.object(handler, 'retry') as mock_retry, \
             patch.object(handler, 'archive') as mock_archive:
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        mock_retry.assert_called_once()
        mock_archive.assert_not_called()

    def test_transient_archives_when_retries_exhausted(self, handler, mock_message):
        """Transient ValueError with retry_count=3 (== MAX_RETRIES) -> archive() called, retry() NOT called."""
        msg = mock_message(retry_count=3)
        body = {'data': 'test'}
        exc_info = (ValueError, ValueError("transient error"), None)

        with patch.object(handler, 'archive') as mock_archive, \
             patch.object(handler, 'retry') as mock_retry:
            handler._on_pool_error(body, msg, exc_info, retry_count=3)

        mock_archive.assert_called_once()
        mock_retry.assert_not_called()

    def test_requeue_safety_net(self, handler, mock_message):
        """When retry() raises and message not acknowledged -> message.requeue() called as safety net."""
        msg = mock_message(retry_count=0)
        msg.acknowledged = False
        body = {'data': 'test'}
        exc_info = (ValueError, ValueError("transient error"), None)

        with patch.object(handler, 'retry', side_effect=RuntimeError("retry failed")), \
             patch.object(handler, 'archive'):
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        assert msg.requeue.called, (
            "message.requeue() must be called as safety net when message is not acknowledged"
        )

    def test_requeue_failure_no_crash(self, handler, mock_message, caplog):
        """When message.requeue() raises in finally block -> no exception propagates, warning logged."""
        msg = mock_message(retry_count=0)
        msg.acknowledged = False
        msg.requeue.side_effect = Exception("channel closed")
        body = {'data': 'test'}
        exc_info = (ValueError, ValueError("transient error"), None)

        with patch.object(handler, 'retry', side_effect=RuntimeError("retry failed")), \
             patch.object(handler, 'archive'), \
             caplog.at_level(logging.WARNING):
            # Must not propagate
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        assert any(
            'requeue' in record.message.lower() or 'Could not' in record.message
            for record in caplog.records
        ), (
            "Expected a warning log about requeue failure, got: "
            + str([r.message for r in caplog.records])
        )

    def test_django_cleanup_always_called(self, handler, mock_message):
        """_django_cleanup() called in finally block of _on_pool_error regardless of path."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}
        exc_info = (ValueError, ValueError("transient error"), None)

        with patch.object(handler, '_django_cleanup') as mock_cleanup, \
             patch.object(handler, 'retry'), \
             patch.object(handler, 'archive'):
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        mock_cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# TEST-04: Celery version compat tests
# ---------------------------------------------------------------------------

class TestCeleryVersionCompat:
    """TEST-04: Both Celery 3.x (single-object) and 4.x/5.x (tuple) exc_info formats handled."""

    def test_celery_4x_5x_tuple_transient(self, handler, mock_message):
        """Celery 4.x/5.x tuple exc_info with transient error -> retry() called."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}
        exc_info = (ValueError, ValueError("err"), None)

        with patch.object(handler, 'retry') as mock_retry, \
             patch.object(handler, 'archive') as mock_archive:
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        mock_retry.assert_called_once()
        mock_archive.assert_not_called()

    def test_celery_3x_single_object_transient(self, handler, mock_message):
        """Celery 3.x single-object exc_info with transient error -> retry() called via type(exc_info)."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}
        exc_info = ValueError("err")  # bare exception, not a tuple

        with patch.object(handler, 'retry') as mock_retry, \
             patch.object(handler, 'archive') as mock_archive:
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        mock_retry.assert_called_once()
        mock_archive.assert_not_called()

    def test_celery_4x_5x_tuple_permanent(self, handler, mock_message):
        """Celery 4.x/5.x tuple exc_info with PermanentFailure -> archive() called."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}
        exc_info = (PermanentFailure, PermanentFailure("bad"), None)

        with patch.object(handler, 'retry') as mock_retry, \
             patch.object(handler, 'archive') as mock_archive:
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        mock_archive.assert_called_once()
        mock_retry.assert_not_called()

    def test_celery_3x_single_object_permanent(self, handler, mock_message):
        """Celery 3.x single-object exc_info with PermanentFailure -> archive() called via type(exc_info)."""
        msg = mock_message(retry_count=0)
        body = {'data': 'test'}
        exc_info = PermanentFailure("bad")  # bare exception, not a tuple

        with patch.object(handler, 'retry') as mock_retry, \
             patch.object(handler, 'archive') as mock_archive:
            handler._on_pool_error(body, msg, exc_info, retry_count=0)

        mock_archive.assert_called_once()
        mock_retry.assert_not_called()
