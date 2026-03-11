# Codebase Structure

**Analysis Date:** 2026-03-11

## Directory Layout

```
celery-message-consumer/
├── .circleci/              # CI/CD configuration (CircleCI)
├── event_consumer/         # Main package with all library code
│   ├── __init__.py         # Public API exports
│   ├── __about__.py        # Version info
│   ├── handlers.py         # Core: @message_handler decorator, bootstep, retry handler
│   ├── types.py            # Type definitions (QueueKey, HandlerRegistration)
│   ├── settings.py         # Configuration (Django integration, defaults)
│   └── errors.py           # Custom exceptions
├── setup.py                # Package metadata and installation config
├── Pipfile                 # Pipenv lock file
├── Pipfile.lock            # Pipenv lock dependencies
└── README.rst              # Documentation
```

## Directory Purposes

**event_consumer/**
- Purpose: Contains all library code - the message consumer toolkit
- Contains: Decorator API, Celery integration, AMQP handler logic, configuration
- Key files: `handlers.py` (largest, most complex), `settings.py`, `types.py`, `errors.py`

**.circleci/**
- Purpose: CI/CD pipeline configuration for automated testing
- Contains: CircleCI workflow definition for testing against Python/Celery/Django matrix
- Committed: Yes (part of repo)

## Key File Locations

**Public API:**
- `event_consumer/__init__.py`: Exports `message_handler` decorator for end users

**Entry Point Configuration:**
- `setup.py`: Defines package metadata, dependencies (celery, kombu, six), installable packages
- `Pipfile`: Python 3.10 requirement for development

**Core Logic:**
- `event_consumer/handlers.py`: All core functionality in 514 lines
  - Lines 55-147: `@message_handler` decorator (registration)
  - Lines 150-207: `AMQPRetryConsumerStep` (Celery bootstep)
  - Lines 209-514: `AMQPRetryHandler` (message processing)
- `event_consumer/settings.py`: Configuration defaults and Django integration
- `event_consumer/types.py`: QueueKey and HandlerRegistration type definitions

**Error Handling:**
- `event_consumer/errors.py`: Three custom exceptions for different failure modes

**Metadata:**
- `event_consumer/__about__.py`: Version string (1.0)

## Naming Conventions

**Files:**
- Lower snake_case: `handlers.py`, `settings.py`, `types.py`, `errors.py`
- Double underscore files: `__init__.py`, `__about__.py`

**Directories:**
- Lower snake_case: `event_consumer/`
- Special prefixes: `.circleci/` (hidden), `.planning/` (hidden, analysis output)

**Python Classes:**
- PascalCase: `AMQPRetryConsumerStep`, `AMQPRetryHandler`, `QueueKey`, `HandlerRegistration`

**Functions/Methods:**
- snake_case: `message_handler()`, `declare_queues()`, `retry()`, `archive()`, `backoff()`
- Private methods: Prefixed with `_` (e.g., `_validate_registration()`, `_close()`)
- Magic methods: Double underscore (e.g., `__init__()`, `__call__()`)

**Constants:**
- UPPER_SNAKE_CASE: `REGISTRY`, `DEFAULT_EXCHANGE`, `PREFETCH_COUNT`, `RETRY_HEADER`, `MAX_RETRIES`

**Variables:**
- snake_case: `routing_key`, `queue_name`, `handler_registration`, `retry_count`
- Global state: `REGISTRY` (dict of QueueKey → HandlerRegistration)

**Types:**
- PascalCase: `QueueKey`, `HandlerRegistration` (as NamedTuples)

## Where to Add New Code

**New Message Handler (Developer Code):**
- Create in application code (outside this package)
- Pattern:
  ```python
  from event_consumer import message_handler

  @message_handler('my.routing.key', queue='my.queue', exchange='my.exchange')
  def handle_message(body):
      # User's handler code here
      pass
  ```
- Import module in Celery app's `CELERY_IMPORTS` list

**New Custom Exception:**
- Location: `event_consumer/errors.py`
- Pattern: Inherit from Exception, add docstring explaining when to raise
- See existing examples: `PermanentFailure`, `NoExchange`, `InvalidQueueRegistration`

**New Configuration Setting:**
- Location: `event_consumer/settings.py`
- Pattern: Use `get()` function to retrieve with EVENT_CONSUMER_ prefix
  ```python
  MY_SETTING = get('MY_SETTING', default_value)
  ```
- Document in docstring and in README.rst Configuration section

**New Handler Lifecycle Hook:**
- Location: `event_consumer/handlers.py` - extend `AMQPRetryConsumerStep` class
- Add method following pattern: `start()`, `stop()`, `shutdown()`
- Pattern: Use Celery bootsteps.StartStopStep as parent class

**New Message Processing Logic:**
- Location: `event_consumer/handlers.py` - methods in `AMQPRetryHandler` class
- Call from: `__call__()` method (the main handler callback)
- Pattern: Keep side effects (queuing, acking) explicit

**Utilities/Helpers:**
- Location: Create new file in `event_consumer/` directory (e.g., `event_consumer/utils.py`)
- Export from: `event_consumer/__init__.py` if public API
- Pattern: Keep focused on single responsibility (e.g., retry logic, archival logic)

## Special Directories

**event_consumer/ (main package):**
- Purpose: Distributable library code
- Generated: No
- Committed: Yes
- Note: Packaged and installed via setup.py

**.circleci/ (CI configuration):**
- Purpose: CircleCI pipeline definitions
- Generated: No
- Committed: Yes
- Note: Defines test matrix for Python 2.7, 3.6-3.8 × Celery/Kombu 3.x & 4.x × Django versions

**.planning/codebase/ (analysis output):**
- Purpose: GSD codebase analysis documents (ARCHITECTURE.md, STRUCTURE.md, etc.)
- Generated: Yes (by GSD mapping agents)
- Committed: Yes
- Note: Read-only reference for code generation and planning

## Code Organization Principles

**Single Responsibility:**
- `handlers.py`: All AMQP handling and retry logic
- `settings.py`: All configuration loading
- `types.py`: Type definitions only
- `errors.py`: Exception definitions only

**Import Organization:**
- Top: Standard library (logging, traceback, os, etc.)
- Middle: Third-party (six, typing, amqp, celery, kombu)
- Bottom: Local package imports (from event_consumer import ...)

**Public vs Private:**
- Public: `message_handler` (decorator), `AMQPRetryConsumerStep` (bootstep), `PermanentFailure` (exception)
- Private: All other classes/functions prefixed with underscore or not exported

**Module Dependencies:**
```
errors.py (no dependencies)
  ↑
types.py (imports from errors)
  ↑
settings.py (imports from types)
  ↑
handlers.py (imports all above)
  ↑
__init__.py (exports from handlers)
```

---

*Structure analysis: 2026-03-11*
