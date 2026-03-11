# External Integrations

**Analysis Date:** 2026-03-11

## APIs & External Services

**AMQP Message Broker:**
- RabbitMQ - Message broker for consuming vanilla AMQP messages
  - SDK/Client: Kombu (abstraction layer), amqp (protocol implementation)
  - Configuration: `BROKER_HOST` environment variable
  - Supported versions: 3.6.0 and later

## Data Storage

**Databases:**
- No direct database integration
- Optional Django ORM integration available when `USE_DJANGO=True`
  - Connection: Via Django's configured database (handled by Django settings)
  - Purpose: Allows message handlers to use Django database connections

**Message Queue Storage:**
- RabbitMQ with dead-letter exchange pattern
  - Main queue: Holds incoming messages
  - Retry queue: Holds messages waiting for retry (with TTL)
  - Archive queue: Holds permanently failed messages
  - Configuration files: None (created dynamically by Kombu)

**File Storage:**
- Not applicable - No file storage integration

**Caching:**
- Not detected

## Authentication & Identity

**Auth Provider:**
- None detected in code - RabbitMQ connection auth handled by Celery configuration
- Authentication credentials managed via Celery broker URL configuration

## Message Format & Serialization

**Serializers:**
- JSON (default) - Primary message serializer
- Configurable via `EVENT_CONSUMER_SERIALIZER` setting
- Kombu ACCEPT header configured in `event_consumer/settings.py`
  - Line 13: `ACCEPT = [SERIALIZER]`

**Message Headers:**
- `x-retry-count` - Tracks retry attempts on messages (defined in `event_consumer/settings.py`, line 21)
- Custom headers supported via message.headers

## Queue & Retry Configuration

**Retry Pattern:**
- Max retries: 7 (default, configurable via `EVENT_CONSUMER_MAX_RETRIES`)
- Retry delays: [0.2s, 5s, 60s, 120s, 300s, 600s, 1800s] (exponential backoff)
  - Custom backoff function supported via `EVENT_CONSUMER_BACKOFF_FUNC`
  - Implementation: `AMQPRetryHandler.backoff()` in `event_consumer/handlers.py`, lines 501-513

**Queue Settings:**
- Consumer prefetch count: 1 (line 23, `event_consumer/settings.py`)
- Archive queue TTL: 24 days default (configurable via `EVENT_CONSUMER_ARCHIVE_EXPIRY`)
- Archive queue max length: 1,000,000 messages (configurable via `EVENT_CONSUMER_ARCHIVE_MAX_LENGTH`)
- Queue arguments: Lazy queue mode (requires RabbitMQ 3.6.0+)

## Dead Letter Exchange Configuration

**Archive Routing:**
- Dead letter exchange name: Configurable via `EVENT_CONSUMER_DEAD_LETTER_EXCHANGE`
- Default configuration:
  - Exchange name field: `replyExchangeName`
  - Exchange postfix: `.dlx`
  - Routing key field: `replyRoutingKey`
  - Routing key postfix: `.archived`
- Implementation: `AMQPRetryHandler.archive()` in `event_consumer/handlers.py`, lines 445-490

## Exchange Configuration

**Custom Exchanges:**
- Configurable via `EVENT_CONSUMER_EXCHANGES` setting
- Format: Dictionary with reference names as keys
- Example structure (from `event_consumer/handlers.py`, lines 43-49):
  ```python
  EXCHANGES = {
      'default': {  # reference name
          'name': 'data',  # actual RabbitMQ exchange name
          'type': 'topic',  # AMQP exchange type
      }
  }
  ```
- Default exchange used if not specified
- All exchanges created dynamically by Kombu

## Webhooks & Callbacks

**Incoming:**
- AMQP message handlers registered via `@message_handler` decorator in `event_consumer/handlers.py`
- Handler registration examples:
  - Single routing key: `@message_handler('my.routing.key')`
  - Multiple keys: `@message_handler(['key1', 'key2'])`
  - Wildcard patterns: `@message_handler('my.routing.*')` (requires topic exchange)

**Outgoing:**
- Message handlers can publish to retry/archive queues internally
- Retry queue publisher: `AMQPRetryHandler.retry_producer`
- Archive queue publisher: `AMQPRetryHandler.archive_producer`
- Custom routing via dynamic dead letter exchange configuration

## Django Integration

**Connection Management:**
- File: `event_consumer/handlers.py`, lines 396-400
- Enabled when `USE_DJANGO=True`
- Feature: Handles "current transaction is aborted" errors by resetting Django database connection after each message
- Signal hook: `django.core.signals.request_finished`

## Monitoring & Observability

**Error Tracking:**
- Not integrated with external service
- All errors logged via Python logging module (`_logger` in `event_consumer/handlers.py`)
- Error details captured in archive queue messages

**Logs:**
- Logging module: Python's `logging` (standard library)
- Logger: `event_consumer` module logger
- Log levels used:
  - DEBUG: Message receive/process/retry details
  - WARNING: Retry reasons
  - ERROR: Retry/archive failures
  - CRITICAL: Message acknowledgment failures

## CI/CD & Deployment

**Hosting:**
- Self-hosted (any platform supporting Python and Celery worker)
- No specific cloud provider integration detected

**CI Pipeline:**
- CircleCI 2.0 - `.circleci/config.yml`
- Test jobs: Python 2.7, 3.6, 3.7, 3.8
- Each job spins up RabbitMQ 3.6.6 Docker container
- Cache strategy: venv and dependency files
- Artifact storage: Test results in `/tmp/results`

## Environment Configuration

**Required env vars:**
- `EVENT_CONSUMER_APP_CONFIG` - Python module path to load configuration (required for operation)
- `BROKER_HOST` - RabbitMQ broker hostname (used in tests)

**Optional env vars:**
- `EVENT_CONSUMER_CONFIG_NAMESPACE` - Config key prefix (defaults to `EVENT_CONSUMER`)
- `EVENT_CONSUMER_SERIALIZER` - Message serializer name (defaults to `json`)
- `EVENT_CONSUMER_QUEUE_NAME_PREFIX` - Prefix for queue names
- `EVENT_CONSUMER_BACKOFF_FUNC` - Custom retry backoff function
- `EVENT_CONSUMER_ARCHIVE_EXPIRY` - Archive queue TTL in milliseconds
- `EVENT_CONSUMER_ARCHIVE_MAX_LENGTH` - Max archive queue size
- `EVENT_CONSUMER_DEAD_LETTER_EXCHANGE` - Dead letter exchange configuration
- `EVENT_CONSUMER_USE_DJANGO` - Enable Django integration (defaults to True)
- `EVENT_CONSUMER_MAX_RETRIES` - Maximum retry attempts (defaults to 7)
- `DJANGO_SETTINGS_MODULE` - Django settings module (if using Django integration)

**Secrets location:**
- Not specified in codebase - Managed by Celery broker URL configuration and environment

---

*Integration audit: 2026-03-11*
