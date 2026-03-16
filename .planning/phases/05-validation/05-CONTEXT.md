# Phase 5: Validation - Context

**Gathered:** 2026-03-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Integration and unit tests confirming correct pool dispatch behavior, connection stability, and callback correctness across supported Celery versions. Regressions are caught before they ship.

This phase adds tests only — no production code changes.

</domain>

<decisions>
## Implementation Decisions

### Integration test strategy (TEST-01, TEST-02)
- Real RabbitMQ via Docker Compose for integration tests
- Full Celery worker subprocess (`celery worker -P eventlet`) — not in-process pool
- Handler communicates results back via shared file/flag (temp file or multiprocessing.Manager)
- Docker Compose includes RabbitMQ only (rabbitmq:3-management), no Redis
- Tests gated behind `@pytest.mark.integration` — skip if RabbitMQ unreachable
- TEST-01: Publish message, Celery worker processes it in eventlet pool greenlet, handler writes greenlet identity to shared file, test asserts it differs from main thread
- TEST-02: RabbitMQ heartbeat set low (e.g. 5s), handler sleeps longer than heartbeat interval (e.g. 8s), after handler completes verify connection is still open and message was acked

### Callback unit tests (TEST-03)
- Dedicated tests in new file — call `_on_pool_success` / `_on_pool_error` directly with controlled inputs
- Primary edge case focus: channel-closed resilience — ack() raises when channel closed by reconnect, verify warning logged but no crash. Same for requeue(). This validates CONN-02 safety net.
- Cover: success path ack, PermanentFailure → archive, transient → retry, retries exhausted → archive, requeue safety net when error handling raises

### Celery version compatibility (TEST-04)
- Parametrized test for `_on_pool_error` with both error_callback signatures:
  - Celery 4.x/5.x: `(exc_type, exc_value, tb)` tuple
  - Celery 3.x: single ExceptionInfo-like object
- Proves the defensive unpack in `_on_pool_error` handles both correctly
- Test only — no runtime version detection or warning needed (defensive unpack already handles it)

### Test organization
- Integration tests: `tests/test_integration.py` with `@pytest.mark.integration` marker
- Callback + version compat unit tests: `tests/test_callbacks.py`
- Docker Compose: `docker-compose.yml` at project root (RabbitMQ only)
- Existing unit tests (`test_handlers.py`, `test_backpressure.py`, `test_reconnect.py`, `test_heartbeat.py`) unchanged

### Claude's Discretion
- Docker Compose configuration details (ports, management plugin settings)
- Celery worker subprocess management in tests (startup/shutdown, timeout handling)
- Exact shared file/flag mechanism for result communication
- pytest marker registration in conftest.py or pyproject.toml
- RabbitMQ connection parameters for integration tests

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing test infrastructure
- `tests/conftest.py` — Shared fixtures (mock_channel, mock_message, mock_pool, handler, settings_patch)
- `tests/test_handlers.py` — Existing unit tests for POOL-01/02/03/05, ACK-01/02/03/04/05 — patterns to follow

### Production code under test
- `event_consumer/handlers.py` — All code being validated: `_on_pool_success`, `_on_pool_error`, `_heartbeat_loop`, pool dispatch in `__call__`, `_inline_dispatch`

### Requirements
- `.planning/REQUIREMENTS.md` — TEST-01 through TEST-04 acceptance criteria

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `conftest.py:mock_message` factory — creates messages with configurable retry_count and acknowledged state
- `conftest.py:mock_pool` — captures apply_async calls with callback/error_callback extraction
- `conftest.py:handler` fixture — AMQPRetryHandler with all Kombu internals mocked
- `conftest.py:settings_patch` — autouse fixture isolating from real Django settings

### Established Patterns
- All unit tests use `patch('kombu.Queue')`, `patch('kombu.Exchange')` etc. to avoid real AMQP
- `_spawn`/`_sleep` module-level indirection allows patching concurrency primitives independently
- `mock_pool._last_call` / `_all_calls` pattern for inspecting pool dispatch arguments
- Lambda default-arg capture pattern (`b=body, m=message, rc=retry_count`) throughout callbacks

### Integration Points
- `AMQPRetryConsumerStep.start(c)` — entry point that wires pool, creates handlers, spawns heartbeat greenlet
- `AMQPRetryHandler.__call__(body, message)` — message dispatch entry point
- `_on_pool_success` / `_on_pool_error` — callback paths to test directly

</code_context>

<specifics>
## Specific Ideas

- Full Celery worker subprocess for integration tests — closer to production behavior than in-process mocking
- Shared file/flag for cross-process result communication — simple, no extra dependencies
- Low heartbeat interval (5s) with handler sleep (8s) to quickly validate heartbeat safety net

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-validation*
*Context gathered: 2026-03-16*
