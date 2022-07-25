
import os
from datetime import timedelta
from django.conf import settings


def get(key, default):
    return getattr(settings,"EVENT_CONSUMER_" + key, default)

    

SERIALIZER = get('SERIALIZER', 'json')
ACCEPT = [SERIALIZER]

QUEUE_NAME_PREFIX = ''

# By default will use `AMQPRetryHandler.backoff`, otherwise supply your own.
# Should accept a single arg <retry number> and return a delay time (seconds).
BACKOFF_FUNC = get('BACKOFF_FUNC', None)  # type: Optional[Callable[[int], float]]

RETRY_HEADER = 'x-retry-count'
# Set the consumer prefetch limit
PREFETCH_COUNT = 1
# to set TTL for archived message (milliseconds)
ARCHIVE_EXPIRY = get('ARCHIVE_EXPIRY', int(timedelta(days=24).total_seconds() * 1000))  # type: int
# max size of archive queue before dropping messages
ARCHIVE_MAX_LENGTH = get('ARCHIVE_MAX_LENGTH', 1000000)  # type: int
ARCHIVE_QUEUE_ARGS = {
    "x-message-ttl": ARCHIVE_EXPIRY,  # Messages dropped after this
    "x-max-length": ARCHIVE_MAX_LENGTH,  # Maximum size of the queue
    "x-queue-mode": "lazy",  # Keep messages on disk (reqs. rabbitmq 3.6.0+)
}

# Construct Dead Letter Queue From Body
DEAD_LETTER_EXCHANGE = get('DEAD_LETTER_EXCHANGE', {
        'exchange': 'replyExchangeName',
        'exchangePostfix' : '.dlx',
        'routingKey': 'replyRoutingKey',
        'routingKeyPostfix': '.archived'
})

EXCHANGES = get('EXCHANGES', {})   # type: Dict[str, Dict[str, str]]
# EXCHANGES = {
#     'default': {  # a reference name for this config, used when attaching handlers
#         'name': 'data',  # actual name of exchange in RabbitMQ
#         'type': 'topic',  # an AMQP exchange type
#     },
#     ...
# }

TASK_DEFAULT_QUEUE = get('TASK_DEFAULT_QUEUE', 'dj2.listener')
USE_DJANGO = get('USE_DJANGO', True)
QUEUE_NAME = get('QUEUE_NAME','')
MAX_RETRIES = get('MAX_RETRIES',4)
