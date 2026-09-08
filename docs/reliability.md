# Reliability

Each completed turn exposes its recall context, write results, and diagnostic
errors. A turn is degraded when recall, extraction, or a write failed, or when
context had to be truncated. No fact content or backend response body is logged
by Rail. Application logging should follow the application's own retention policy.

The turn counter counts started turns. The degraded-turn counter counts each
degraded turn once, including a turn stopped by required-governance failure.
Agent failures propagate; a failed agent does not itself count as a memory failure.
Low-level recall calls do not increment turn counters.

Write results are written, deduplicated, deferred, rejected, or (during replay)
dropped. Structured DUPLICATE_MEMORY responses with a known duplicate reason and
existing memory ID are recognized. Unknown HTTP 409 conflicts remain errors.
A duplicate of an older or archived memory does not promise that it will appear
in ordinary recall.

Temporary transport errors, HTTP 408/429/5xx, and a duplicate race whose winner is
no longer live are retryable. Other errors are rejected without filling the queue.
Application-provided stores should raise StoreError and explicitly classify
retryable failures; unexpected programming errors propagate.

Call rail.flush_outbox() in Python or await rail.flushOutbox() in TypeScript
after connectivity recovers. The default limit is three replay attempts per item.
Results report each attempt. An expired or permanently rejected replay is dropped
and counted. Queue overflow drops the oldest queued item and increments total_dropped
(Python) or totalDropped (TypeScript). New enqueues during replay use the same
capacity accounting. These counters are process-local.

Replay can repeat a request whose original response was lost. Backend duplicate
handling helps reconcile this; Rail does not provide exactly-once delivery.
There is no persistent spool, automatic backoff, or background replay worker.
Python task cancellation propagates; cancellation during replay restores the
unprocessed batch to the bounded queue, with normal eviction accounting.

Python closes HTTP clients it creates. A supplied httpx client remains owned by
the caller. Async clients use await store.aclose() or an async context manager.
Native Node fetch owns its connection lifecycle.

Configuration names use snake_case in Python and camelCase in TypeScript.
Both support top_k/topK, require_keystones/requireKeystones, max_context_chars/
maxContextChars, max_facts/maxFacts, and max_fact_chars/maxFactChars. Pass a custom
Outbox to choose capacity. Store timeout is seconds in Python and milliseconds in
TypeScript. UTF-8 text limits count Unicode code points, not tokens.
