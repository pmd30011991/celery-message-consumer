# Codebase Concerns

**Analysis Date:** 2026-03-11

## Tech Debt

**Global REGISTRY dictionary:**
- Issue: `REGISTRY` in `event_consumer/handlers.py` (line 34) is a module-level mutable global dictionary used to store handler registrations. This is an anti-pattern that makes testing difficult and creates hidden state management.
- Files: `event_consumer/handlers.py:34`, `event_consumer/handlers.py:44`, `event_consumer/handlers.py:120`, `event_consumer/handlers.py:165`
- Impact: Difficult to test in isolation, unclear initialization order, requires manual registry clearing between tests, makes concurrent test execution problematic
- Fix approach: Encapsulate REGISTRY within a class-based registry manager or use dependency injection to pass registrations to handlers

**Deprecated Python 2.7 support:**
- Issue: Codebase still supports Python 2.7 as documented in README.rst (line 189) and uses `six` library for compatibility
- Files: `event_consumer/handlers.py:12`, `event_consumer/errors.py:1`, `setup.py:40-41`
- Impact: Unnecessary complexity with compatibility shims, maintenance burden for code that targets Python 2 (which reached end-of-life Jan 2020)
- Fix approach: Drop Python 2.7 support, remove six dependency, use native Python 3 syntax

**Pool implementation unclear in current feature branch:**
- Issue: Recent feature branch change (commit b0bba48) adds `self.pool = c.pool` (line 170) but calls it incorrectly with `self.pool.apply_async(self.func(body))` (line 346)
- Files: `event_consumer/handlers.py:170`, `event_consumer/handlers.py:346`
- Impact: Likely bug - `self.func(body)` is executed immediately and its return value passed to `apply_async()` instead of passing the function itself, defeating the purpose of async execution
- Fix approach: Change to `self.pool.apply_async(self.func, (body,))` to pass the function and arguments separately for async execution

## Known Bugs

**Incorrect pool.apply_async usage:**
- Symptoms: Pool-based async execution won't work as intended; function executes synchronously in handler thread before being passed to pool
- Files: `event_consumer/handlers.py:346`
- Trigger: Any message processed after pool adoption feature is merged
- Impact: Negates the purpose of using a pool for concurrent message processing - defeats worker pool parallelization
- Workaround: Revert to direct function call (current master behavior) until apply_async is corrected

**Undefined exception handling in handler restart:**
- Symptoms: If channel becomes closed during message processing, exception handling in `_close()` may encounter errors that aren't properly surfaced
- Files: `event_consumer/handlers.py:183-192`
- Trigger: Channel closes unexpectedly during `common.ignore_errors()` calls
- Current mitigation: Uses `common.ignore_errors()` wrapper which swallows errors silently

## Security Considerations

**Unvalidated message headers in retry count:**
- Risk: `retry_count()` method retrieves count from message headers without validation - malicious headers could cause unexpected behavior
- Files: `event_consumer/handlers.py:498-499`
- Current mitigation: Only used internally by framework; external message sources have some validation through type hints
- Recommendations: Add bounds checking on retry count, validate header format explicitly before use

**Dynamic exchange creation from message body:**
- Risk: `archive()` method extracts exchange name directly from message body (lines 454-455) without validation
- Files: `event_consumer/handlers.py:450-462`
- Current mitigation: None - code assumes message body contains valid exchange names
- Recommendations: Validate exchange names against whitelist, sanitize routing keys, add logging for dynamic exchange creation

**Exception details exposed in messages:**
- Risk: Full exception tracebacks are included in message headers/archive (lines 354-360, 366-375, 381-388)
- Files: `event_consumer/handlers.py:350-389`
- Current mitigation: None
- Recommendations: Consider sanitizing sensitive information from tracebacks, add option to exclude stack traces in production

## Performance Bottlenecks

**Single channel per handler setup:**
- Problem: Each handler gets a single channel that handles all queues (worker, retry, archive)
- Files: `event_consumer/handlers.py:219-306`
- Cause: Kombu consumer architecture uses one channel per consumer; no connection pooling for multiple handlers
- Improvement path: Profile actual rabbitmq connection limits and consider channel pooling strategy

**Prefetch count hardcoded to 1:**
- Problem: Line 305 sets `prefetch_count=settings.PREFETCH_COUNT` which defaults to 1 (settings.py:23)
- Files: `event_consumer/settings.py:23`, `event_consumer/handlers.py:305`
- Cause: Conservative default designed for long-running tasks, but creates inefficient broker utilization
- Improvement path: Make prefetch count configurable at handler level, document performance implications of different values

**No connection pooling or reuse:**
- Problem: New channel created for each handler instance at startup (line 169) without connection reuse
- Files: `event_consumer/handlers.py:169`, `event_consumer/handlers.py:247-266`, `event_consumer/handlers.py:284-303`
- Cause: Direct channel allocation from connection
- Improvement path: Consider implementing channel pool for high-volume scenarios

## Fragile Areas

**Message acknowledgment edge case:**
- Files: `event_consumer/handlers.py:322-408`
- Why fragile: Complex exception handling with multiple code paths (archive, retry, exception) that must properly ack/nack messages. Lines 391-408 contain fallback logic that fires if message not explicitly acknowledged, which is critical safety net but indicates fragility
- Safe modification: Add comprehensive test coverage for each exception path, never remove the final ack/requeue safety check
- Test coverage: No dedicated unit tests visible; integration test coverage unknown

**Hardcoded queue naming conventions:**
- Files: `event_consumer/handlers.py:256`, `event_consumer/handlers.py:269`
- Why fragile: Queue naming uses hardcoded patterns like `{queue}.retry` and `{queue}.archived` - changing these breaks messages already in flight
- Safe modification: Any changes to naming must be backward compatible, migration required
- Test coverage: Unclear how extensively queue naming is tested

**Archive handler conditional logic:**
- Files: `event_consumer/handlers.py:450-475`
- Why fragile: Conditional archive routing based on body contents (lines 454-456) with fallback behavior. If conditions change or message format shifts, archives may silently go to wrong destination
- Safe modification: Add explicit validation of message format before attempting dynamic routing, log warnings when falling back to default archive
- Test coverage: No visible test coverage for dynamic archive routing vs default archive

**Django integration assumptions:**
- Files: `event_consumer/handlers.py:397-400`, `event_consumer/settings.py:4`, `event_consumer/settings.py:52`
- Why fragile: Code assumes Django is available and request_finished signal exists if USE_DJANGO=True (line 397), but doesn't validate this at runtime
- Safe modification: Add explicit exception handling for missing Django, validate USE_DJANGO setting during initialization
- Test coverage: Django integration likely tested but may not cover missing Django scenarios

## Scaling Limits

**Single message processing thread per handler:**
- Current capacity: One handler processes one message at a time (prefetch_count=1) and synchronously calls handler function
- Limit: At prefetch_count=1, theoretical maximum throughput is `1 / (handler_execution_time + retry_overhead)`
- Scaling path: Increase prefetch_count if handlers are I/O-bound, consider async handlers, use multiple worker instances

**Archive queue message retention:**
- Current capacity: Default ARCHIVE_MAX_LENGTH=1000000 messages (settings.py:27)
- Limit: Queue memory grows unbounded until max length, then messages are dropped. RabbitMQ server memory pressure occurs before limit reached
- Scaling path: Reduce ARCHIVE_EXPIRY (default 24 days) for faster cleanup, implement external archive system, monitor queue depth

**No built-in monitoring or metrics:**
- Current capacity: Implicit - relies on logging via Python logging module
- Limit: No structured metrics for handler execution time, success rates, retry patterns
- Scaling path: Add instrumentation for message processing duration, success/failure counts, retry distributions

## Dependencies at Risk

**Celery/Kombu version compatibility:**
- Risk: Supports both Celery 3.x and 4.x with corresponding Kombu 3.x and 4.x (README.rst line 193-195). Both Celery 3.x and Kombu 3.x are outdated
- Impact: Long-term maintenance burden, security patches not available
- Migration plan: Establish minimum version requirements (e.g., Celery 4.4+), test and deprecate Celery 3.x support

**Six library dependency:**
- Risk: Used for Python 2/3 compatibility but Python 2.7 is EOL
- Impact: Unnecessary dependency increasing attack surface
- Migration plan: Remove six dependency entirely, use native Python 3 syntax

**Django version compatibility claims:**
- Risk: README claims support for Django 1.11 (line 204) which reached EOL April 2020
- Impact: If used with Django 1.11, receives no security patches
- Migration plan: Update documented minimum Django version to 2.2+

## Test Coverage Gaps

**No visible test directory in codebase:**
- What's not tested: All message handling paths appear untested in this checkout; README references tests but test directory not present
- Files: No test files found in repository checkout
- Risk: All refactoring and feature changes (like pool adoption) happen without validation
- Priority: High - test infrastructure must be restored or created before further changes

**Message acknowledgment paths untested:**
- What's not tested: Complex ack/nack/requeue logic in lines 391-408, error handling paths for all three queue types
- Files: `event_consumer/handlers.py:322-443`
- Risk: Silent failures where messages aren't properly acknowledged or are lost
- Priority: High

**Dynamic archive routing untested:**
- What's not tested: Conditional archive behavior based on message body (lines 450-475)
- Files: `event_consumer/handlers.py:450-475`
- Risk: Messages silently route to wrong archive exchange/queue
- Priority: Medium - affects error handling accuracy

**Handler registration and initialization:**
- What's not tested: Decorator behavior, REGISTRY validation, duplicate registration detection
- Files: `event_consumer/handlers.py:39-147`
- Risk: Registration errors only surface at worker startup
- Priority: Medium - affects developer experience but not runtime safety

---

*Concerns audit: 2026-03-11*
