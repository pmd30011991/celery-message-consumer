"""
Integration tests for celery-message-consumer.

TEST-01: Handler runs in pool greenlet, not listener thread.
TEST-02: RabbitMQ connection survives handler sleeping longer than heartbeat interval.

These tests require a live RabbitMQ broker on localhost:5672.
They are gated behind @pytest.mark.integration and skip gracefully when
RabbitMQ is not reachable.

To run with Docker:
    docker compose up -d
    pytest tests/test_integration.py -v -m integration --tb=long
    docker compose down
"""
import json
import os
import socket
import subprocess
import sys
import time

import pytest


def _rabbitmq_reachable():
    """Return True if RabbitMQ is accepting connections on localhost:5672."""
    try:
        with socket.create_connection(('localhost', 5672), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.integration

skip_no_rabbit = pytest.mark.skipif(
    not _rabbitmq_reachable(),
    reason="RabbitMQ not reachable on localhost:5672"
)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULT_FILE = '/tmp/integration_test_result.json'
_HEARTBEAT_RESULT_FILE = '/tmp/integration_heartbeat_result.json'


def _start_worker(worker_args):
    """Start the integration worker subprocess with the given extra CLI args."""
    # Remove stale result files
    for path in (_RESULT_FILE, _HEARTBEAT_RESULT_FILE):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    cmd = [
        sys.executable, '-m', 'celery',
        '-A', 'tests._integration_worker',
        'worker',
    ] + worker_args

    process = subprocess.Popen(
        cmd,
        cwd=_PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Give the worker time to start and bind queues
    time.sleep(5)
    return process


def _stop_worker(process):
    """Terminate worker subprocess gracefully."""
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@pytest.fixture
def dispatch_worker():
    """Worker fixture for TEST-01 (pool greenlet dispatch, no heartbeat)."""
    process = _start_worker(['-P', 'eventlet', '-c', '4', '--without-heartbeat'])
    yield process
    _stop_worker(process)


@pytest.fixture
def heartbeat_worker():
    """Worker fixture for TEST-02 (heartbeat survival with 5s heartbeat interval)."""
    process = _start_worker(['-P', 'eventlet', '-c', '4', '--broker-heartbeat=5'])
    yield process
    _stop_worker(process)


def _publish_message(routing_key, body):
    """Publish a message to the default exchange using kombu."""
    import kombu
    with kombu.Connection('amqp://guest:guest@localhost:5672//') as conn:
        exchange = kombu.Exchange('default', type='topic', durable=True)
        with conn.channel() as channel:
            exchange.declare(channel=channel)
            producer = kombu.Producer(channel, exchange=exchange, routing_key=routing_key)
            producer.publish(body, content_type='application/json', content_encoding='utf-8')


def _poll_result_file(path, timeout, interval=0.5):
    """Poll for a JSON result file and return parsed content or None on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(interval)
    return None


@skip_no_rabbit
def test_pool_greenlet_dispatch(dispatch_worker):
    """TEST-01: Handler runs in an eventlet pool greenlet, not the main greenlet.

    Publishes a message to the dispatch handler and checks that the handler
    executed in a non-main greenlet (proving pool dispatch is working).
    """
    _publish_message('integration.test.dispatch', {'test': 'dispatch'})

    result = _poll_result_file(_RESULT_FILE, timeout=15, interval=0.5)
    assert result is not None, (
        "Handler did not write result within 15s. "
        "Check worker logs for errors."
    )
    assert result['is_main_greenlet'] is False, (
        "Handler ran in the main greenlet — pool dispatch is NOT working. "
        f"Result: {result}"
    )


@skip_no_rabbit
def test_heartbeat_survival(heartbeat_worker):
    """TEST-02: Connection survives handler sleeping 8s with a 5s heartbeat interval.

    The dedicated heartbeat greenlet (BEAT-01) must keep sending heartbeat frames
    while the handler is asleep. If the connection drops, the worker process
    will exit — heartbeat_worker.poll() will be non-None.
    """
    _publish_message('integration.test.heartbeat', {'sleep_duration': 8})

    result = _poll_result_file(_HEARTBEAT_RESULT_FILE, timeout=25, interval=1)
    assert result is not None, (
        "Heartbeat handler did not write result within 25s. "
        "Connection may have dropped or handler crashed."
    )
    assert result['completed'] is True, (
        f"Handler did not complete successfully. Result: {result}"
    )
    assert result['slept'] == 8, (
        f"Handler slept unexpected duration. Result: {result}"
    )
    assert heartbeat_worker.poll() is None, (
        "Worker process exited during test — connection likely dropped due to "
        "missed heartbeats. The heartbeat safety-net greenlet may not be working."
    )
