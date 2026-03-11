# Coding Conventions

**Analysis Date:** 2026-03-11

## Naming Patterns

**Files:**
- Lowercase with underscores: `handlers.py`, `settings.py`, `errors.py`
- Version metadata in `__about__.py`
- Init files as `__init__.py`

**Functions:**
- Snake case: `message_handler()`, `declare_queues()`, `retry_count()`
- Decorator functions follow same pattern: `@message_handler()`
- Private functions prefixed with single underscore: `_validate_registration()`, `_close()`
- Class methods use `@classmethod` or `@staticmethod` decorators

**Variables:**
- Snake case throughout: `routing_key`, `queue_name`, `retry_count`, `dlx_name`
- Constants in UPPERCASE: `DEFAULT_EXCHANGE`, `REGISTRY`
- Global variables prefixed with underscore when private: `_logger`
- Instance variables prefixed with `self.`: `self.channel`, `self.routing_key`, `self.func`

**Types:**
- Type hints in comments using mypy syntax: `# type: (QueueKey) -> None`
- Named tuples for structured data: `QueueKey`, `HandlerRegistration` in `event_consumer/types.py`
- Optional types indicated: `Optional[Callable[[int], float]]`

**Classes:**
- PascalCase: `AMQPRetryConsumerStep`, `AMQPRetryHandler`, `PermanentFailure`

## Code Style

**Formatting:**
- No explicit code formatter configured (no `.flake8`, `.pylintrc`, black config)
- Generally follows PEP 8 conventions
- Line breaks: Functions separated by two blank lines at module level
- Indentation: 4 spaces (Python standard)

**Linting:**
- No linting configuration found in repository
- Module uses `# noqa` comments to suppress linting warnings where needed: `from event_consumer.handlers import message_handler  # noqa`

**Documentation Style:**
- Module-level docstrings with triple quotes at top of file
- Function docstrings with Args, Returns, Raises sections
- Detailed inline comments explaining complex AMQP patterns
- Example code in docstrings using `Usage:` section

## Import Organization

**Order:**
1. Standard library imports: `logging`, `traceback`, `os`, `datetime`
2. Third-party imports: `six`, `celery`, `kombu`, `amqp`
3. Local/relative imports: `from event_consumer import settings`, `from event_consumer.errors import ...`
4. Conditional imports for optional features: Django imports wrapped in `if settings.USE_DJANGO:`

**Path Aliases:**
- No import aliases configured
- Full module paths used: `from event_consumer.handlers import message_handler`
- Conditional Django imports: `if settings.USE_DJANGO: from django.core.signals import request_finished`

**Example pattern from `event_consumer/handlers.py` lines 1-27:**
```python
import logging
import traceback

import six
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

import amqp
import celery.bootsteps as bootsteps
import kombu
import kombu.message
import kombu.common as common
from event_consumer import settings

from event_consumer.errors import InvalidQueueRegistration, NoExchange, PermanentFailure
from event_consumer.types import HandlerRegistration, QueueKey

if settings.USE_DJANGO:
    from django.core.signals import request_finished
```

## Error Handling

**Patterns:**
- Custom exceptions defined in `event_consumer/errors.py`: `PermanentFailure`, `NoExchange`, `InvalidQueueRegistration`
- Try-except-else-finally blocks used throughout: See `AMQPRetryHandler.__call__()` lines 339-408
- Exception context preserved: `except KeyError as key_exc:` (line 275)
- Exception logging with full traceback: `traceback.format_exc()` included in log messages
- Three-tier error strategy:
  1. PermanentFailure → archive immediately (don't retry)
  2. Max retries exceeded → archive after logging
  3. Temporary exception → retry with backoff
- Message acknowledgment handling: `message.ack()` or `message.requeue()` called explicitly

**Example from `event_consumer/handlers.py` lines 349-390:**
```python
except Exception as e:
    if isinstance(e, PermanentFailure):
        self.archive(body, message, "Task '{}' raised '{}...'".format(...))
    elif retry_count >= settings.MAX_RETRIES:
        self.archive(body, message, "Task '{}' ran out of retries...".format(...))
    else:
        self.retry(body, message, "Task '{}' raised exception...".format(...))
else:
    message.ack()
    _logger.debug("Task '{}' processed and ack() sent".format(...))
finally:
    if settings.USE_DJANGO:
        request_finished.send(sender="AMQPRetryHandler")
    if not message.acknowledged:
        message.requeue()
        _logger.critical("Messages not sending ack()...")
```

## Logging

**Framework:** Python's standard `logging` module

**Patterns:**
- Logger instance created at module level: `_logger = logging.getLogger(__name__)` (line 30)
- Log levels used: `debug()`, `warning()`, `error()`, `critical()`
- Debug logs for operational flow: `_logger.debug('registered: %s to handler: %s.%s', ...)`
- Warning logs for retry scenarios: `_logger.warning(reason)` in `retry()` method
- Error logs for failures: `_logger.error("Retry failure: ...")` with full traceback context
- Critical logs for unexpected states: `_logger.critical("Messages not sending ack()...")` when message handling breaks

**Log message format:**
- String interpolation with positional arguments: `%s`, `%d`
- Context-rich messages that include routing_key, retry_count, queue names
- Full exception tracebacks included: `traceback.format_exc()`

## Comments

**When to Comment:**
- Complex AMQP message flow explained with multi-line comments
- Algorithm explanations: e.g., backoff calculation logic in `backoff()` method (line 508)
- Non-obvious design decisions documented: "N.B." prefix used for important notes (line 259)
- Configuration options explained in docstrings with links to external resources

**JSDoc/TSDoc:**
- Not used (Python project)
- Triple-quote docstrings follow Google/Sphinx style
- Args, Returns, Raises sections in docstrings
- Type hints in comments for compatibility with older Python versions

## Function Design

**Size:**
- Varied but generally focused
- `__call__()` method is ~70 lines (lines 322-408) - handles main message processing flow
- Utility methods like `retry()` and `archive()` are 30-40 lines each
- No exceptionally long functions

**Parameters:**
- Type hints in comments for all parameters
- Kwargs used for optional configuration: `queue=None`, `exchange=DEFAULT_EXCHANGE`, `queue_arguments=None`
- Variable argument handling with `Union` types: `routing_keys` can be string or Iterable (line 55)

**Return Values:**
- Decorators return the wrapped function: `def decorator(f):` pattern (line 119)
- Class methods marked with `@classmethod` or `@staticmethod`
- None return values implicit when not specified
- Handler functions expected to return None (called async via celery pool)

**Example from `message_handler()` decorator (lines 55-147):**
```python
def message_handler(routing_keys,  # type: Union[str, Iterable]
                    queue=None,  # type: Optional[str]
                    exchange=DEFAULT_EXCHANGE,  # type: str
                    queue_arguments=None,  # Optional[Dict[str, object]]
                    ):
    # type: (...) ->  Callable[[Callable], Any]
    # ... validation logic ...

    def decorator(f):  # type: (Callable) -> Callable
        # ... registration logic ...
        return f

    return decorator
```

## Module Design

**Exports:**
- `event_consumer/__init__.py` exports key public API: `from event_consumer.handlers import message_handler`
- Handler registration occurs via import side-effect (decorator execution at import time)
- `REGISTRY` global dict used as the single source of truth for all registered handlers

**Barrel Files:**
- Minimal barrel file usage
- `__init__.py` imports only the public decorator: `message_handler`
- Settings and errors accessed via direct imports

**Module Organization:**
- `event_consumer/__about__.py`: Version metadata
- `event_consumer/__init__.py`: Public API re-exports
- `event_consumer/types.py`: Type definitions (NamedTuples)
- `event_consumer/errors.py`: Custom exception classes
- `event_consumer/settings.py`: Configuration loading
- `event_consumer/handlers.py`: Main implementation (decorator, handler class, consumer step)

---

*Convention analysis: 2026-03-11*
