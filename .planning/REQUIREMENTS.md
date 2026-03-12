# Requirements: celery-message-consumer Thread-Safe Pool Dispatch

**Defined:** 2026-03-11
**Core Value:** Messages from RabbitMQ dispatched to Celery's eventlet/gevent pool, keeping listener thread free for heartbeats — zero disconnects, zero message loss.

## v1 Requirements

### Pool Dispatch

- [x] **POOL-01**: Message handler execution dispatched to Celery's eventlet/gevent pool via correct `apply_async(target, args)` signature
- [x] **POOL-02**: `AMQPRetryHandler` receives pool reference from `AMQPRetryConsumerStep`
- [x] **POOL-03**: Listener thread returns to `drain_events()` immediately after dispatching — does not block on handler execution
- [x] **POOL-04**: Prefork pool detected and falls back to inline execution with warning log
- [x] **POOL-05**: Existing `@message_handler` decorator API unchanged — no breaking changes for library users

### Acknowledgment Safety

- [x] **ACK-01**: Messages acked only after successful handler completion in pool (at-least-once delivery)
- [x] **ACK-02**: Failed messages trigger retry or archive via pool callbacks — same retry/archive semantics as current behavior
- [x] **ACK-03**: Unacknowledged messages requeued on handler crash or connection loss
- [x] **ACK-04**: Lambda captures in callbacks use default-argument binding to avoid late-binding bugs
- [x] **ACK-05**: `retry_count` captured from message headers before pool dispatch

### Backpressure

- [x] **BACK-01**: `PREFETCH_COUNT` configurable and aligned with pool concurrency
- [x] **BACK-02**: RabbitMQ stops delivering messages when all prefetch slots occupied
- [x] **BACK-03**: Consumer does not accumulate unbounded in-memory messages during pool saturation

### Reconnect

- [x] **CONN-01**: `_close()` clears `self.handlers = []` to prevent stale handler references after reconnect
- [x] **CONN-02**: Channel operations in pool callbacks guarded with error handling for closed connections
- [x] **CONN-03**: Celery's existing blueprint restart correctly rebuilds handlers on fresh connection

### Heartbeat

- [x] **BEAT-01**: AMQP heartbeats maintained during long-running handler execution
- [x] **BEAT-02**: Dedicated heartbeat greenlet spawned in `start()` as safety net (conditional on connection heartbeat being set)

### Validation

- [ ] **TEST-01**: Integration test confirms messages processed by pool greenlet, not listener thread
- [ ] **TEST-02**: Integration test confirms connection stays alive during long-running handler
- [ ] **TEST-03**: Unit tests for `_on_pool_success` and `_on_pool_error` callback paths
- [ ] **TEST-04**: Celery version compatibility verified (3.x and 4.x `error_callback` signature)

## v2 Requirements

### Advanced Concurrency

- **CONC-01**: `eventlet.Semaphore` as app-level backpressure safety net
- **CONC-02**: Per-handler prefetch_count configuration (different concurrency per queue)
- **CONC-03**: Dynamic prefetch_count adjustment based on pool utilization

### Observability

- **OBS-01**: Metrics for pool dispatch latency and queue depth
- **OBS-02**: Health check endpoint for connection and pool status

### CPU-Bound Support

- **CPU-01**: `tpool.execute()` fallback for CPU-bound handlers with safe ack bridging

## Out of Scope

| Feature | Reason |
|---------|--------|
| Celery task protocol support | Library handles vanilla AMQP messages, not Celery tasks |
| Prefork pool optimization | Focusing on eventlet/gevent; prefork gets inline fallback |
| Python 2.7 support | Modernizing to Python 3.x only |
| Broker migration | RabbitMQ is the only supported broker |
| New serialization formats | Using existing Kombu serialization |
| Real-time pool scaling | Out of scope for this fix; Celery manages pool size |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| POOL-01 | Phase 1 | Complete |
| POOL-02 | Phase 1 | Complete |
| POOL-03 | Phase 1 | Complete |
| POOL-04 | Phase 3 | Complete |
| POOL-05 | Phase 1 | Complete |
| ACK-01 | Phase 1 | Complete |
| ACK-02 | Phase 1 | Complete |
| ACK-03 | Phase 1 | Complete |
| ACK-04 | Phase 1 | Complete |
| ACK-05 | Phase 1 | Complete |
| BACK-01 | Phase 2 | Complete |
| BACK-02 | Phase 2 | Complete |
| BACK-03 | Phase 2 | Complete |
| CONN-01 | Phase 3 | Complete |
| CONN-02 | Phase 3 | Complete |
| CONN-03 | Phase 3 | Complete |
| BEAT-01 | Phase 4 | Complete |
| BEAT-02 | Phase 4 | Complete |
| TEST-01 | Phase 5 | Pending |
| TEST-02 | Phase 5 | Pending |
| TEST-03 | Phase 5 | Pending |
| TEST-04 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0

---
*Requirements defined: 2026-03-11*
*Last updated: 2026-03-11 after initial definition*
