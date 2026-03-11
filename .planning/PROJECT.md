# Celery Message Consumer — Thread-Safe Pool Dispatch

## What This Is

A RabbitMQ/AMQP adapter library for Celery that consumes vanilla (non-Celery-task) messages using a decorator-based registration pattern and integrates as a Celery bootstep. The library provides retry/archive semantics via dead-letter exchanges. This project fixes a critical thread-safety issue where message processing blocks the AMQP listener thread instead of being dispatched to Celery's worker pool.

## Core Value

Messages from RabbitMQ must be dispatched to Celery's eventlet/gevent pool for processing, keeping the AMQP listener thread free for heartbeats and new messages — ensuring zero disconnects and zero message loss.

## Requirements

### Validated

<!-- Existing capabilities confirmed from codebase -->

- ✓ Decorator-based handler registration (`@message_handler`) — existing
- ✓ Celery bootstep integration (`AMQPRetryConsumerStep`) — existing
- ✓ Retry with exponential backoff via DLX — existing
- ✓ Archive queue for permanently failed messages — existing
- ✓ Django integration support (optional) — existing
- ✓ Per-handler queue/exchange/routing key configuration — existing
- ✓ Configurable serializer, max retries, backoff function — existing

### Active

<!-- Current scope. Building toward these. -->

- [ ] Message processing dispatched to Celery's eventlet/gevent pool instead of inline on listener thread
- [ ] AMQP heartbeats maintained during long-running handler execution
- [ ] Auto-reconnect to RabbitMQ on connection loss without manual intervention
- [ ] Message acknowledgment only after successful pool processing (at-least-once delivery)
- [ ] Backpressure: stop consuming when pool is saturated to prevent memory buildup
- [ ] Multiple queue support with different handlers (already partially exists, needs thread-safe handling)
- [ ] Backward-compatible API — existing `@message_handler` decorator and `AMQPRetryConsumerStep` interface preserved

### Out of Scope

- Celery task protocol support — this library handles vanilla AMQP messages, not Celery tasks
- Prefork pool support — focusing on eventlet/gevent for this iteration
- Broker migration away from RabbitMQ — RabbitMQ is the only supported broker
- Python 2.7 support — modernizing to Python 3.x only
- New serialization formats — using existing Kombu serialization

## Context

- The codebase is a published Python library (`celery-message-consumer`) with existing users
- Current architecture: `AMQPRetryHandler.__call__()` processes messages inline on the Kombu consumer callback thread
- Line 322-409 in `event_consumer/handlers.py` is where `self.pool.apply_async(self.func(body))` executes — but the pool dispatch isn't truly async; it blocks waiting for the result
- AMQP connections have heartbeat timeouts; if the listener thread is blocked processing a message, heartbeats are missed and RabbitMQ drops the connection
- Kombu consumers are not thread-safe by default — need careful handling when dispatching to pool
- The library already has a connection pool concept (`AMQPRetryConsumerStep` manages channels) but it's tied to the single listener thread
- Existing test suite uses pytest with Docker-based RabbitMQ

## Constraints

- **API compatibility**: Existing `@message_handler` decorator interface must not change — users should not need to modify their handler code
- **Pool type**: Must work with eventlet/gevent pool (Celery's `-P eventlet` or `-P gevent`)
- **Broker**: RabbitMQ only (via AMQP protocol through Kombu)
- **Ack safety**: Messages must not be acked before handler completes — at-least-once delivery guarantee
- **Dependencies**: Celery 3.x/4.x and Kombu 3.x/4.x compatibility where feasible

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Eventlet/gevent pool over prefork | User's existing infrastructure; green threads handle I/O-bound AMQP work well | — Pending |
| Keep existing decorator API | Backward compatibility for existing users of the library | — Pending |
| At-least-once delivery (ack after processing) | Zero message loss is a hard requirement; duplicate processing is acceptable | — Pending |

---
*Last updated: 2026-03-11 after initialization*
