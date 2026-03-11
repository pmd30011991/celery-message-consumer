# Technology Stack

**Analysis Date:** 2026-03-11

## Languages

**Primary:**
- Python 3.10 - Core runtime (specified in Pipfile)
- Python 2.7, 3.6, 3.7, 3.8 - Tested compatibility (see README.rst)

## Runtime

**Environment:**
- Python 3.10 (primary)
- Supports Python 2.7 and 3.6-3.8 for backward compatibility

**Package Manager:**
- pip - Primary package management
- Pipenv - Configured (Pipfile/Pipfile.lock present)
- Setuptools - Used for package distribution (setup.py)

## Frameworks

**Core:**
- Celery 3.x and 4.x - Task queue and worker framework for consuming AMQP messages
- Kombu 3.x and 4.x - AMQP messaging library (version compatibility matches Celery)

**Message Queue:**
- RabbitMQ 3.6+ - Only supported message broker (via AMQP protocol)

**Optional Integration:**
- Django 1.11, 2.2 - Optional framework support for Django-based applications
  - Used when `USE_DJANGO` setting is enabled
  - Provides Django database connection handling in message handlers

## Key Dependencies

**Critical:**
- celery - Message consumer framework, versions 3.x or 4.x
- kombu - AMQP client library, versions 3.x or 4.x (must match Celery version)
- amqp - Low-level AMQP protocol implementation
- six - Python 2/3 compatibility utilities (version 1.x)
- typing - Type hints support for Python < 3.6 (conditional)

**Optional:**
- django - Optional dependency for Django integration (versions 1.11, 2.2)

## Configuration

**Environment:**
- Configured primarily via Python module imports (e.g., `settings.py` or Django's `settings.py`)
- Environment variables control config loading:
  - `EVENT_CONSUMER_APP_CONFIG` - Import path to Python configuration module
  - `EVENT_CONSUMER_CONFIG_NAMESPACE` - Prefix for loading additional config values (defaults to `EVENT_CONSUMER`)
  - `BROKER_HOST` - RabbitMQ broker host (used in tests)
  - `DJANGO_SETTINGS_MODULE` - Django settings module (for Django-dependent tests)

**Build:**
- `setup.py` - Standard Python package setup and distribution
- `.circleci/config.yml` - CI/CD pipeline configuration (CircleCI 2.0)
- Test configuration via tox (see `tox.ini` if present)

## Platform Requirements

**Development:**
- Python 2.7 or 3.6+ (as per test matrix)
- Docker (for local RabbitMQ testing via docker-compose)
- pyenv (recommended for Python version management)
- tox (for testing across version matrix)
- CircleCI CLI (optional, for local CI testing)

**Production:**
- RabbitMQ 3.6.0 or later (required - only supported message broker)
- Python 3.6+ (though 2.7 is still tested)
- Celery worker process
- Network access to RabbitMQ broker

## Testing & Quality Tools

**Test Framework:**
- pytest (py.test) - Test runner
- tox - Test automation across multiple Python/dependency combinations

**Test Matrix:**
- Combinations tested: Python 2.7, 3.6, 3.7, 3.8 × Django 1.11, 2.2 × Celery/Kombu 3.x, 4.x
- RabbitMQ 3.6.6 used in testing via Docker

---

*Stack analysis: 2026-03-11*
