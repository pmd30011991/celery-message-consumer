# Roadmap: celery-message-consumer — Thread-Safe Pool Dispatch

## Overview

The library has a single root-cause bug: `apply_async(self.func(body))` executes the handler inline on the AMQP listener thread, blocking heartbeats and defeating the pool entirely. This roadmap fixes that bug and then addresses the four downstream problems it exposes in sequence: ack deferral into callbacks (Phase 1), broker-enforced backpressure (Phase 2), reconnect safety and prefork guard (Phase 3), heartbeat safety net (Phase 4), and validation across supported Celery versions (Phase 5). Each phase can be reviewed and merged independently.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Root Cause Fix** - Fix `apply_async` call signature and defer ack/retry/archive into pool callbacks (completed 2026-03-11)
- [x] **Phase 2: Backpressure** - Align `PREFETCH_COUNT` with pool concurrency so broker stops delivery when pool is full (completed 2026-03-11)
- [x] **Phase 3: Reconnect Hardening** - Clear stale handlers on close, guard in-flight callbacks, add prefork fallback (completed 2026-03-11)
- [ ] **Phase 4: Heartbeat Safety Net** - Spawn dedicated heartbeat greenlet in `start()` as defense-in-depth
- [ ] **Phase 5: Validation** - Integration tests confirm thread safety, connection stability, and Celery version compat

## Phase Details

### Phase 1: Root Cause Fix
**Goal**: Message handlers execute in the Celery pool greenlet, not on the listener thread, and all post-execution side effects (ack, retry, archive, Django cleanup) run in pool callbacks.
**Depends on**: Nothing (first phase)
**Requirements**: POOL-01, POOL-02, POOL-03, POOL-05, ACK-01, ACK-02, ACK-03, ACK-04, ACK-05
**Success Criteria** (what must be TRUE):
  1. A message sent to RabbitMQ is processed by a pool greenlet — the listener thread returns to `drain_events()` without waiting for handler completion.
  2. `message.ack()` is called only after the handler function completes successfully inside the pool greenlet.
  3. A handler that raises `PermanentFailure` causes the message to be archived via `_on_pool_error` callback, not inline code.
  4. A handler that raises a transient exception causes the message to be retried (or archived when retries exhausted) via the error callback — same retry/archive semantics as the current inline path.
  5. Existing `@message_handler` decorator and `AMQPRetryConsumerStep` registration interface work without any changes to user code.
**Plans:** 2/2 plans complete
Plans:
- [x] 01-01-PLAN.md — Test infrastructure and failing tests for all Phase 1 requirements
- [x] 01-02-PLAN.md — Fix apply_async dispatch and implement pool callbacks

### Phase 2: Backpressure
**Goal**: RabbitMQ stops delivering new messages once the pool is at capacity, preventing unbounded in-memory message accumulation.
**Depends on**: Phase 1
**Requirements**: BACK-01, BACK-02, BACK-03
**Success Criteria** (what must be TRUE):
  1. `PREFETCH_COUNT` defaults to pool concurrency (not `1`) and is documented as the intended configuration.
  2. When all pool greenlets are busy, RabbitMQ holds additional messages at the broker — no new messages arrive at the listener until a slot frees up.
  3. Under sustained load equal to pool size, unacknowledged message count in RabbitMQ stays bounded at `PREFETCH_COUNT`; no runaway growth in consumer memory.
**Plans:** 1/1 plans complete
Plans:
- [x] 02-01-PLAN.md — Pool-derived prefetch_count with TDD tests

### Phase 3: Reconnect Hardening
**Goal**: A RabbitMQ reconnect produces a clean handler set with no stale references, in-flight callbacks are safe to execute against a closed channel, and prefork pool deployments get a warning and inline fallback.
**Depends on**: Phase 1
**Requirements**: POOL-04, CONN-01, CONN-02, CONN-03
**Success Criteria** (what must be TRUE):
  1. After a connection drop and reconnect, exactly the expected set of handlers is active — no duplicate or stale handlers from the previous connection.
  2. A pool callback that fires after a reconnect does not raise an unhandled exception when it attempts to ack or retry on the now-closed channel.
  3. Starting the worker with `-P prefork` logs a warning and falls back to inline execution rather than silently misbehaving.
  4. Celery's `blueprint.restart()` correctly rebuilds all handlers on the fresh connection without requiring a full worker restart.
**Plans:** 1/1 plans complete
Plans:
- [ ] 03-01-PLAN.md — TDD reconnect hardening: stale handler reset, callback guards, prefork fallback

### Phase 4: Heartbeat Safety Net
**Goal**: AMQP heartbeats are maintained even during sustained periods of high pool dispatch load, through a dedicated heartbeat greenlet independent of the listener loop.
**Depends on**: Phase 1
**Requirements**: BEAT-01, BEAT-02
**Success Criteria** (what must be TRUE):
  1. With a heartbeat interval configured on the connection, a dedicated greenlet calls `connection.heartbeat_tick()` on the correct interval without interfering with the listener's own heartbeat calls.
  2. Under a sustained burst where the listener thread is continuously dispatching messages, the RabbitMQ connection does not drop due to a missed heartbeat.
  3. The heartbeat greenlet is only spawned when `c.connection.heartbeat` is set (non-zero); no greenlet is created for connections without a heartbeat configured.
**Plans**: TBD

### Phase 5: Validation
**Goal**: Integration and unit tests confirm correct pool dispatch behavior, connection stability, and callback correctness across supported Celery versions — regressions are caught before they ship.
**Depends on**: Phase 4 (all prior phases complete)
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04
**Success Criteria** (what must be TRUE):
  1. An integration test with a real eventlet pool and real RabbitMQ confirms the handler runs in a pool greenlet (not the listener thread) by asserting thread/greenlet identity.
  2. An integration test confirms the RabbitMQ connection stays alive (no heartbeat drop) during a handler that sleeps for longer than the heartbeat interval.
  3. Unit tests for `_on_pool_success` and `_on_pool_error` assert the correct ack/retry/archive call is made for each path without requiring a live broker.
  4. The `error_callback` signature is verified against the installed Celery version (3.x and 4.x/5.x differ); a compatibility shim or test guard prevents silent failures.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

Note: Phase 2 and Phase 3 are independent of each other (both depend only on Phase 1) and can be planned and executed in parallel if desired.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Root Cause Fix | 2/2 | Complete   | 2026-03-11 |
| 2. Backpressure | 1/1 | Complete   | 2026-03-11 |
| 3. Reconnect Hardening | 1/1 | Complete   | 2026-03-11 |
| 4. Heartbeat Safety Net | 0/TBD | Not started | - |
| 5. Validation | 0/TBD | Not started | - |
