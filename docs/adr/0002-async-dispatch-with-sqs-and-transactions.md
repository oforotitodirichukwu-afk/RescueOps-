# ADR-0002: Asynchronous dispatch with SQS and DynamoDB transactions

**Status:** Accepted

## Context
Emergency calls arrive in bursts. A single accident can generate many calls at once. Matching an incident to an ambulance reads fleet state and must never assign one ambulance to two incidents, even when several workers run in parallel.

## Decision
- The API persists the incident as `PENDING` and enqueues a dispatch request, returning `202 Accepted`. Matching happens in a separately scaled worker.
- The worker claims an ambulance with `TransactWriteItems`. The transaction has two conditional updates: ambulance `AVAILABLE → DISPATCHED` and incident `PENDING → DISPATCHED`. Both succeed or neither does.
- SQS delivers at least once, so the worker checks the incident is still `PENDING` before working and after any failed claim. This makes processing idempotent.
- When no ambulance is free, the message's visibility timeout is shortened to retry in 15s. After 10 receives it moves to a dead-letter queue, which represents an unserved incident and is alerted on.

## Consequences
- The API stays fast and available even if matching slows down. Queue depth becomes a natural autoscaling signal for workers.
- Correctness under concurrency comes from the database, not from locks in application code.
- Known trade-offs, accepted at this scale and noted for future work:
  - The incident write and the enqueue are not atomic. A crash between them leaves a `PENDING` incident with no message. A transactional outbox or DynamoDB Streams would close this gap.
  - Finding available ambulances is a table scan. A geospatial index (geohash GSI) would replace it at fleet sizes beyond a few thousand.
  - Retries are FIFO-agnostic. Severity-based priority queues are a future improvement.
