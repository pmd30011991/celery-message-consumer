# Testing Patterns

**Analysis Date:** 2026-03-11

## Test Framework

**Runner:**
- pytest (py.test)
- Version not pinned in Pipfile - managed via requirements files and tox
- Config: Configured in `.circleci/config.yml` and references `tox.ini` (location not provided in current directory listing)

**Assertion Library:**
- Standard Python assertions (part of pytest)

**Run Commands:**
```bash
py.test -v -s --pdb tests/              # Run all tests with verbose output, print statements, and debugger
tox -e py36-dj111-cel3                  # Run tox with specific environment (Python 3.6, Django 1.11, Celery 3)
tox -e py37-dj22-cel3,py37-dj22-cel4   # Run multiple environment combinations
```

**CI Environment:**
- CircleCI orchestrates testing across Python versions 2.7, 3.6, 3.7, 3.8
- Each version runs against multiple dependency combinations (Django 1.11/2.2, Celery 3.x/4.x)
- RabbitMQ 3.6.6 required as service dependency for integration tests

## Test File Organization

**Location:**
- Tests in `tests/` directory (referenced in README, not in current directory listing)
- Separate from source code directory `event_consumer/`
- Co-located test app at `test_app/` with Django-specific settings

**Naming:**
- Test modules follow `test_*.py` pattern
- Test app includes version-specific settings: `test_app/dj111/settings.py`

**Structure:**
- Test discovery via pytest standard conventions
- Environment configuration via env vars:
  - `DJANGO_SETTINGS_MODULE=test_app.dj111.settings` (for Django integration)
  - `EVENT_CONSUMER_APP_CONFIG=test_app.settings` (for consumer config)
  - `BROKER_HOST=localhost` (RabbitMQ broker location)

## Test Types

**Unit Tests:**
- Scope: Individual handler registration, queue creation, exception handling
- Approach: Isolated function testing with mocking of Kombu/AMQP components
- Coverage of: Decorator behavior, validation logic, backoff calculations

**Integration Tests:**
- Scope: Full message flow through retry/archive queues
- Approach: Real RabbitMQ instance required (via docker-compose)
- Coverage of: End-to-end message processing, retry queue mechanics, archive behavior
- Requires: `docker-compose up -d` to start RabbitMQ 3.6.6
- Broker connection: `localhost:5672` via env var `BROKER_HOST`

**E2E Tests:**
- Not separated from integration tests - integration tests serve as E2E validation
- Full celery worker lifecycle tested via CircleCI jobs

## Dependency Testing

**Matrix Coverage:**
The project tests against a full compatibility matrix to ensure support across multiple dependency versions.

**Python Versions:** 2.7, 3.6, 3.7, 3.8

**Framework Combinations:**
- Django 1.11 with Celery/Kombu 3.x
- Django 1.11 with Celery/Kombu 4.x
- Django 2.2 with Celery/Kombu 3.x
- Django 2.2 with Celery/Kombu 4.x
- Celery 3.x and 4.x with optional Django support

**Tox Configuration:**
Referenced via `requirements-base.txt` and `tox.ini` (exact content not available in exploration, but CircleCI config shows environments like `py27-dj111-cel3`, `py36-dj22-cel4`, etc.)

**Requirements Management:**
- `requirements-base.txt`: Base dependencies across Python versions
- `requirements-test.txt`: Testing-specific dependencies (pytest, plugins, etc.)
- Per-environment pins managed via tox configuration

## Test Execution Flow

**Local Development:**
```bash
# 1. Start RabbitMQ service
docker-compose up -d

# 2. Get broker host (varies by Docker setup)
export BROKER_HOST=$(docker-machine ip default)

# 3. Set Django and app settings
export DJANGO_SETTINGS_MODULE=test_app.dj111.settings
export EVENT_CONSUMER_APP_CONFIG=test_app.settings

# 4. Install dependencies
pip install -r requirements-test.txt

# 5. Run tests
PYTHONPATH=. py.test -v -s --pdb tests/
```

**CircleCI Automated:**
- Creates virtualenv (venv or python -m venv based on Python version)
- Installs tox
- Runs tox with environment specification: `tox -e py27-dj111-cel3,py27-dj111-cel4`
- Stores artifacts in `/tmp/results` for inspection

## Coverage

**Requirements:** No strict coverage threshold mentioned in documentation or CircleCI config

**View Coverage:**
Not explicitly documented - would follow pytest-cov conventions:
```bash
pytest --cov=event_consumer --cov-report=html tests/
```

**Notable Gaps:**
- Test files not present in current directory listing (existing repo likely has tests in separate tests/ directory)
- Coverage percentage not enforced in CI

## Service Dependencies

**RabbitMQ:**
- Version: 3.6.6 (specified in CircleCI config)
- Required for: Integration tests (retry queue mechanics, dead-letter exchange, message TTL)
- Started via: `docker-compose.yml` (content not provided)
- Admin UI: `http://{BROKER_HOST}:15672/` with `rabbitmqadmin` for debugging

**Django (Optional):**
- Required for: Tests using Django ORM or signals
- Configured via: Test settings in `test_app/dj111/settings.py` and `test_app/dj22/settings.py`
- Integration: Django's request_finished signal used in handler cleanup (line 400 of `handlers.py`)

**Celery:**
- Required for: All tests (framework integration)
- Multiple versions tested: 3.x and 4.x
- Usage: Worker pool, bootsteps integration

## Key Testing Concerns

**Complex Behaviors Requiring Tests:**
1. Handler registration (duplicate detection, validation)
2. Message retry logic with exponential backoff
3. Archive queue behavior after max retries
4. PermanentFailure exception handling
5. Message acknowledgment/requeue in various failure scenarios
6. Django signal integration (request_finished) for connection cleanup
7. Exception handling across retry/archive flows with full traceback logging
8. Queue and exchange creation via Kombu

**Message Flow Testing:**
The critical test scenarios based on `AMQPRetryHandler.__call__()` (lines 322-408):
- Successful message processing → message.ack()
- Exception with retries remaining → retry() → message.ack()
- Exception exceeds MAX_RETRIES → archive() → message.ack()
- PermanentFailure → archive() immediately → message.ack()
- Failure in retry/archive logic → message.requeue()
- Missing acknowledgment → critical log + message.requeue()

**Configuration Variations:**
- Custom backoff functions (BACKOFF_FUNC setting)
- Custom exchanges (settings.EXCHANGES dict)
- Django integration (USE_DJANGO setting)
- Dead letter exchange configuration (DEAD_LETTER_EXCHANGE)
- Serialization formats (SERIALIZER setting: json, etc.)

---

*Testing analysis: 2026-03-11*
