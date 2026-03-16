"""
Shared pytest fixtures for celery-message-consumer tests.

Provides: mock_channel, mock_message (factory), mock_pool, handler, settings_patch.
No live broker needed -- all AMQP operations are mocked.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests requiring a live RabbitMQ broker (deselect with '-m \"not integration\"')"
    )

# ---------------------------------------------------------------------------
# Django must be configured before any event_consumer import happens,
# because event_consumer/settings.py does `from django.conf import settings`
# at module level.
# ---------------------------------------------------------------------------
import django
from django.conf import settings as django_settings

if not django_settings.configured:
    django_settings.configure(
        DEBUG=True,
        DATABASES={},
        INSTALLED_APPS=[],
    )


# ---------------------------------------------------------------------------
# autouse fixture: patch event_consumer.settings to safe test defaults
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def settings_patch():
    """
    Patch event_consumer.settings attributes to known, safe values for every test.
    This isolates tests from any real Django settings that might be present.
    """
    patches = {
        'event_consumer.settings.MAX_RETRIES': 3,
        'event_consumer.settings.USE_DJANGO': False,
        'event_consumer.settings.EXCHANGES': {'default': {'name': 'default', 'type': 'topic'}},
        'event_consumer.settings.ARCHIVE_QUEUE_ARGS': {},
        'event_consumer.settings.QUEUE_NAME_PREFIX': '',
        'event_consumer.settings.SERIALIZER': 'json',
        'event_consumer.settings.PREFETCH_COUNT': 1,
        'event_consumer.settings.ACCEPT': ['json'],
        'event_consumer.settings.RETRY_HEADER': 'x-retry-count',
        'event_consumer.settings.DEAD_LETTER_EXCHANGE': {},
        'event_consumer.settings.BACKOFF_FUNC': None,
    }
    with patch.multiple('event_consumer.settings', **{k.split('.')[-1]: v for k, v in patches.items()}):
        yield


# ---------------------------------------------------------------------------
# mock_channel
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_channel():
    """
    A MagicMock satisfying the amqp.channel.Channel interface well enough
    for AMQPRetryHandler construction. Kombu uses duck typing, so MagicMock works.
    """
    return MagicMock(name='mock_channel')


# ---------------------------------------------------------------------------
# mock_message (factory fixture)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_message():
    """
    Factory fixture.  Call make_message(retry_count=0, acknowledged=False)
    to get a MagicMock that looks like a kombu.message.Message.

    The 'acknowledged' attribute is a plain bool so tests can mutate it:
        msg.acknowledged = True   # after ack
    """
    def make_message(retry_count=0, acknowledged=False):
        msg = MagicMock(name='mock_message')
        # Headers
        if retry_count:
            msg.headers = {'x-retry-count': retry_count}
        else:
            msg.headers = {}
        # ack/requeue are plain MagicMocks (callable)
        msg.ack = MagicMock(name='ack')
        msg.requeue = MagicMock(name='requeue')
        # acknowledged is a regular attribute so tests can check/flip it.
        # Side-effect: when ack() is called, flip acknowledged to True.
        def _ack_side_effect():
            msg.acknowledged = True
        msg.ack.side_effect = _ack_side_effect
        msg.acknowledged = acknowledged
        return msg

    return make_message


# ---------------------------------------------------------------------------
# mock_pool
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_pool():
    """
    A MagicMock with an apply_async method whose side_effect captures
    the callback and error_callback so tests can invoke them manually.

    Access the last call via:
        mock_pool._last_call  -- dict with keys: target, args, callback, error_callback
    """
    pool = MagicMock(name='mock_pool')
    pool._last_call = None
    pool._all_calls = []

    def apply_async_side_effect(target, args=(), kwargs=None, callback=None, error_callback=None, **kw):
        call_record = {
            'target': target,
            'args': args,
            'callback': callback,
            'error_callback': error_callback,
        }
        pool._last_call = call_record
        pool._all_calls.append(call_record)

    pool.apply_async.side_effect = apply_async_side_effect
    return pool


# ---------------------------------------------------------------------------
# handler (AMQPRetryHandler with mocked Kombu internals)
# ---------------------------------------------------------------------------
@pytest.fixture
def handler(mock_channel, mock_pool):
    """
    Creates an AMQPRetryHandler with:
      - All kombu.Queue / kombu.Exchange / kombu.Producer / kombu.Consumer
        calls patched out so no real AMQP connection is needed.
      - handler.pool set to mock_pool (Plan 02 will wire this through
        get_handlers; for now we set it directly).
    """
    from event_consumer.handlers import AMQPRetryHandler

    func = MagicMock(name='user_handler_func')

    with patch('kombu.Queue'), \
         patch('kombu.Exchange'), \
         patch('kombu.Producer'), \
         patch('kombu.Consumer'):
        h = AMQPRetryHandler(
            channel=mock_channel,
            routing_key='test.routing.key',
            queue='test_queue',
            exchange='default',
            queue_arguments={},
            func=func,
        )

    # Wire pool directly -- get_handlers will do this in Plan 02.
    h.pool = mock_pool
    return h
