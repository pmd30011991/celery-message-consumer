"""
Integration test worker -- started as subprocess by test_integration.py.
Usage: celery -A tests._integration_worker worker -P eventlet -c 4
"""
import json
import os
import threading

from django.conf import settings as django_settings
if not django_settings.configured:
    django_settings.configure(DEBUG=True, DATABASES={}, INSTALLED_APPS=[])

import celery
from event_consumer import message_handler

app = celery.Celery('integration_test')
app.config_from_object({
    'broker_url': os.environ.get('TEST_BROKER_URL', 'amqp://guest:guest@localhost:5672//'),
    'worker_hijack_root_logger': False,
    'worker_prefetch_multiplier': 1,
})

import event_consumer.settings
event_consumer.settings.EXCHANGES = {'default': {'name': 'default', 'type': 'topic'}}
event_consumer.settings.QUEUE_NAME_PREFIX = ''
event_consumer.settings.MAX_RETRIES = 3
event_consumer.settings.SERIALIZER = 'json'
event_consumer.settings.ACCEPT = ['json']
event_consumer.settings.RETRY_HEADER = 'x-retry-count'
event_consumer.settings.ARCHIVE_QUEUE_ARGS = {}
event_consumer.settings.DEAD_LETTER_EXCHANGE = {}
event_consumer.settings.BACKOFF_FUNC = None
event_consumer.settings.PREFETCH_COUNT = 0
event_consumer.settings.USE_DJANGO = False

RESULT_FILE = os.environ.get('RESULT_FILE', '/tmp/integration_test_result.json')
HEARTBEAT_RESULT_FILE = os.environ.get('HEARTBEAT_RESULT_FILE', '/tmp/integration_heartbeat_result.json')


@message_handler('integration.test.dispatch', queue='integration_dispatch_queue', exchange='default')
def dispatch_handler(body):
    import eventlet
    result = {
        'greenlet_id': str(eventlet.getcurrent()),
        'thread_ident': threading.current_thread().ident,
        'main_thread_ident': threading.main_thread().ident,
        'is_main_greenlet': eventlet.getcurrent() == eventlet.hubs.get_hub().greenlet.parent,
    }
    with open(RESULT_FILE, 'w') as f:
        json.dump(result, f)


@message_handler('integration.test.heartbeat', queue='integration_heartbeat_queue', exchange='default')
def heartbeat_handler(body):
    import eventlet
    sleep_duration = body.get('sleep_duration', 8)
    eventlet.sleep(sleep_duration)
    result = {'completed': True, 'slept': sleep_duration}
    with open(HEARTBEAT_RESULT_FILE, 'w') as f:
        json.dump(result, f)


from event_consumer.handlers import AMQPRetryConsumerStep
app.steps['consumer'].add(AMQPRetryConsumerStep)
