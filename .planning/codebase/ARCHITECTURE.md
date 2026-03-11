# Architecture

**Analysis Date:** 2026-03-11

## Pattern Overview

**Overall:** Handler Registration + Celery Worker Integration Pattern

This is a message consumption library that integrates with Celery's worker framework to consume vanilla AMQP messages (non-Celery tasks) from RabbitMQ with automatic retry and archival capabilities.

**Key Characteristics:**
- Decorator-based handler registration (similar to Celery's @task pattern)
- Integrates as a Celery "bootstep" (lifecycle hook into worker startup/shutdown)
- Try-Retry-Archive pattern for resilient message handling
- Dead-letter exchange (DLX) based retry mechanism with exponential backoff
- Per-handler state management with dedicated Kombu Consumer instances
- Connection pooling support for worker process management

## Layers

**Registration Layer:**
- Purpose: Allows developers to define message handlers through decorators at module import time
- Location: `event_consumer/handlers.py` (decorator and REGISTRY)
- Contains: `@message_handler` decorator, global REGISTRY dict, QueueKey validation
- Depends on: `event_consumer/types.py` (QueueKey, HandlerRegistration types), `event_consumer/settings.py` (configuration)
- Used by: Developer code that imports the library; `AMQPRetryConsumerStep`

**Consumer/Worker Integration Layer:**
- Purpose: Hooks into Celery worker lifecycle to initialize and manage message consumption
- Location: `event_consumer/handlers.py` (AMQPRetryConsumerStep class)
- Contains: Celery bootstep implementation, handler lifecycle management, channel management
- Depends on: Celery bootsteps, Kombu, registered handlers in REGISTRY
- Used by: Celery worker (via `consumer_app.steps['consumer'].add()`)

**Message Handling Layer:**
- Purpose: Processes individual AMQP messages with retry/archive logic
- Location: `event_consumer/handlers.py` (AMQPRetryHandler class)
- Contains: Message processing logic, retry queue management, archive queue management, error handling
- Depends on: Kombu (exchanges, queues, producers, consumers), `event_consumer/settings.py`, `event_consumer/errors.py`
- Used by: Celery framework (invoked as callback for each message)

**Configuration Layer:**
- Purpose: Centralizes settings loaded from Django or environment
- Location: `event_consumer/settings.py`
- Contains: Default values, Django integration hooks, queue/exchange configuration
- Depends on: Django (when USE_DJANGO=True)
- Used by: All layers (handlers, consumer step, retry handler)

**Type/Error Layer:**
- Purpose: Defines custom exceptions and type definitions
- Location: `event_consumer/errors.py` (exceptions), `event_consumer/types.py` (type definitions)
- Contains: PermanentFailure, NoExchange, InvalidQueueRegistration exceptions; QueueKey, HandlerRegistration NamedTuples
- Depends on: Python standard library only
- Used by: All layers for type safety and error signaling

## Data Flow

**Handler Registration Flow (Import Time):**

1. Developer imports module containing `@message_handler` decorated function
2. Decorator executes, validates registration against REGISTRY
3. HandlerRegistration stored in REGISTRY dict with QueueKey as key
4. Validation ensures no duplicate queue+exchange combinations

**Message Consumption Flow (Runtime):**

1. Celery worker starts and executes bootsteps including `AMQPRetryConsumerStep`
2. `AMQPRetryConsumerStep.start()` creates channel from connection pool
3. Gets all handlers from REGISTRY via `get_handlers()`
4. For each handler, creates `AMQPRetryHandler` instance with channel
5. `AMQPRetryHandler.__init__()` declares 3 queues: worker, retry, archive
6. Registers handler as callback: `kombu.Consumer(callbacks=[self])`
7. Calls `consumer.consume()` to start listening
8. Messages arrive → `AMQPRetryHandler.__call__()` invoked with (body, message)

**Message Processing Flow (Handler Execution):**

1. `AMQPRetryHandler.__call__()` receives message
2. Extracts retry_count from message headers
3. Executes: `self.pool.apply_async(self.func(body))`
4. If handler completes without exception → `message.ack()`
5. If PermanentFailure raised → `archive()` with reason
6. If other exception AND retries exhausted → `archive()` with error details
7. If other exception AND retries remaining → `retry()` with expiration backoff
8. In finally block: handles Django cleanup, requeues unacknowledged messages

**Retry/Archive Flow:**

- **Retry:** Message published to retry queue with calculated TTL (backoff)
- RabbitMQ DLX routes expired retry message back to main queue
- Retry count incremented in x-retry-count header
- **Archive:** Message published to archive queue (or custom DLX if configured)
- Archive queue has 24-day default TTL and max size limits
- Allows manual inspection/replay of failed messages

**Shutdown Flow:**

1. `AMQPRetryConsumerStep.stop()` or `.shutdown()` called
2. Cancels all consumer subscriptions
3. Closes all channels
4. Graceful cleanup prevents message loss

**State Management:**

- Global REGISTRY: Maps (queue, exchange) tuples → handler metadata
- Per-handler state: Kombu Consumer, Producer, Queue, Exchange objects
- Per-message state: Retry count in message headers (x-retry-count)
- Worker pool: Process/thread pool managed by Celery for actual task execution

## Key Abstractions

**Message Handler Registration:**
- Purpose: Declarative interface for subscribing to message routing keys
- Examples: `event_consumer/handlers.py` lines 55-147 (decorator implementation)
- Pattern: Decorator that modifies function and stores metadata in REGISTRY

**AMQP Retry Handler:**
- Purpose: Encapsulates single routing key's message processing, retries, and archival
- Examples: `event_consumer/handlers.py` lines 209-514 (class implementation)
- Pattern: Callable object (implements `__call__`) that acts as Kombu callback

**Celery Bootstep:**
- Purpose: Integrates message consumer into Celery worker lifecycle
- Examples: `event_consumer/handlers.py` lines 150-207 (AMQPRetryConsumerStep)
- Pattern: Extends celery.bootsteps.StartStopStep with start/stop/shutdown hooks

**Queue Key:**
- Purpose: Unique identifier for a queue + exchange combination
- Examples: `event_consumer/types.py` lines 5-11
- Pattern: NamedTuple(queue: str, exchange: str)

**Handler Registration:**
- Purpose: Metadata bundle for a single handler
- Examples: `event_consumer/types.py` lines 14-21
- Pattern: NamedTuple(routing_key: str, queue_arguments: Dict, handler: Callable)

## Entry Points

**Module Initialization:**
- Location: `event_consumer/__init__.py`
- Triggers: `from event_consumer import message_handler`
- Responsibilities: Exports public API (the @message_handler decorator)

**Decorator Entry Point:**
- Location: `event_consumer/handlers.py` lines 55-147
- Triggers: Developer code applies `@message_handler(...)` to function
- Responsibilities: Validate configuration, register handler in REGISTRY, return decorated function

**Celery Integration Entry Point:**
- Location: `event_consumer/handlers.py` lines 150-207 (AMQPRetryConsumerStep)
- Triggers: Developer adds to Celery app: `consumer_app.steps['consumer'].add(AMQPRetryConsumerStep)`
- Responsibilities: Initialize consumer on worker start, manage handler lifecycle, handle graceful shutdown

**Message Processing Entry Point:**
- Location: `event_consumer/handlers.py` lines 322-409 (AMQPRetryHandler.__call__)
- Triggers: Kombu invokes callback when message arrives
- Responsibilities: Execute handler function, manage ack/nack/requeue, orchestrate retry/archive

## Error Handling

**Strategy:** Explicit exception hierarchy with retry/archive decision logic

**Patterns:**

- **PermanentFailure:** Developer raises this to immediately archive without retry
  - Location: `event_consumer/errors.py` lines 4-21
  - Usage: Handler function raises PermanentFailure when error is unrecoverable (bad format, logic error)
  - Result: Message archived immediately

- **Transient Failure (any other Exception):**
  - Location: `event_consumer/handlers.py` lines 349-389
  - Checked against retry count and settings.MAX_RETRIES
  - If retries remain: retry() called (message goes to retry queue)
  - If retries exhausted: archive() called

- **Queue/Exchange Errors:**
  - Location: `event_consumer/errors.py` lines 24-36 (NoExchange, InvalidQueueRegistration)
  - Raised during handler initialization or registration
  - Prevents misconfiguration from silently failing

- **Channel/Connection Errors:**
  - Location: `event_consumer/handlers.py` lines 183-192 (_close method)
  - Wrapped with `common.ignore_errors()` during shutdown
  - Ensures graceful shutdown even if connection already broken

- **Unacknowledged Messages:**
  - Location: `event_consumer/handlers.py` lines 402-408
  - If message not acked/nacked by end of __call__, it's requeued
  - Safety net for unexpected code paths

## Cross-Cutting Concerns

**Logging:**

- Framework: Python's standard `logging` module
- Located at: `event_consumer/handlers.py` line 30 (_logger = logging.getLogger(__name__))
- Debug level: Handler registration, consumer lifecycle events, retry decisions
- Warning level: Retry operations
- Error level: Exception details, archive failures, retry failures
- Critical level: Unacknowledged messages (requires attention)

**Validation:**

- Handler registration validation: `event_consumer/handlers.py` lines 39-52, 100-115
- Queue/exchange configuration validation: Checked during handler init (lines 275-282)
- Routing key rules: Validates string vs list, prevents custom queue with multiple routing keys

**Configuration Management:**

- Centralized in `event_consumer/settings.py`
- Django integration: `get()` function retrieves EVENT_CONSUMER_* prefixed settings
- Environment override capability: Each setting has defaults that can be overridden
- Key settings: EXCHANGES, SERIALIZER, MAX_RETRIES, BACKOFF_FUNC, USE_DJANGO

**Django Integration:**

- Controlled by settings.USE_DJANGO flag
- Located: `event_consumer/handlers.py` lines 26-27 (import), 397-400 (usage)
- Purpose: Signals Django when request is complete to avoid "transaction aborted" errors
- Only active when USE_DJANGO=True

**Message Serialization:**

- Serializer specified in settings.SERIALIZER (default: 'json')
- Applied by Kombu automatically on produce/consume
- Used in both Consumer accept list and Producer configuration

---

*Architecture analysis: 2026-03-11*
