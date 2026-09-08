# Reliability

This page states what Rail guarantees when memory operations fail, and what it
does not. The [guide](guide.md#degraded-turns-and-replay) shows the same behavior
with runnable examples.

## Turn outcomes

Each completed turn exposes its recall context, write results, and diagnostic
errors. A turn is degraded when recall, extraction, or a write failed, or when
context had to be truncated. Rail never logs fact content or backend response
bodies; application logging follows the application's own retention policy.

The turn counter counts started turns. The degraded-turn counter counts each
degraded turn once, including a turn stopped by a required-governance failure.
Agent failures propagate; a failed agent does not itself count as a memory
failure. `recall()` calls do not touch turn counters.

## Write classification

Write results are `written`, `deduplicated`, `deferred`, `rejected`, or, during
replay, `dropped`. Structured `DUPLICATE_MEMORY` responses with reason
`exact_content_hash` or `semantic_similarity` and an existing memory id are
`deduplicated`. Unknown HTTP 409 conflicts remain errors and are rejected. A
duplicate of an older or archived memory does not promise that it will appear in
ordinary recall.

Temporary transport errors, HTTP 408, 429, and 5xx, and a duplicate race whose
winner is no longer live are retryable and become `deferred`. Everything else,
including authentication (401), permission (403), validation (422), and unknown
conflicts, is `rejected` without filling the queue. Application-provided stores
should raise `StoreError` and set `retryable` explicitly; unexpected programming
errors propagate.

## Outbox and replay

Call `rail.flush_outbox()` in Python or `await rail.flushOutbox()` in TypeScript
after connectivity recovers. The default limit is three replay attempts per item,
counted across flushes. Results report each attempt. An item that exhausts its
attempts or fails permanently is dropped and counted. Queue overflow drops the
oldest queued item and increments `total_dropped` (Python) or `totalDropped`
(TypeScript). New enqueues during replay use the same capacity accounting. These
counters are process-local.

Replay can repeat a request whose original response was lost. The server's
duplicate handling reconciles this case by answering `deduplicated`; Rail does
not provide exactly-once delivery. There is no persistent spool, automatic
backoff, or background replay worker, and pending facts are lost when the
process exits. Python task cancellation propagates; cancellation during replay
restores the unprocessed batch to the bounded queue with normal eviction
accounting.

## Governance rules

Rules are fetched on every recall and formatted ahead of facts. A rule fetch
failure degrades the turn but lets the agent run, unless `require_keystones` /
`requireKeystones` is set, in which case the turn raises `StoreError` before the
agent runs. An empty successful rules response is valid. A response the server
marks `X-Truncated: true` (more than 50 matching rules) is treated as a failure
because the agent would be missing rules it should follow.

Formatting rules ahead of facts does not guarantee model compliance,
prompt-injection resistance, or safe retention of arbitrary user content. The
default extractor stores user statements without verifying them.

## Context budget

`max_context_chars` / `maxContextChars` (default 16,000) caps `context.text`.
Rules are kept and facts are dropped from the end until the text fits, with
`facts_context_truncated` recorded. If rules alone exceed the budget they are
dropped with `governance_context_overflow`, or the turn raises when rules are
required. Limits count Unicode code points, not tokens.

## Server limits Rail applies

| Limit | Value | Behavior |
|---|---|---|
| Search `top_k` | 1 to 20 | Larger values raise `ValueError` / `TypeError` before any request. |
| Search query | 5,000 characters | Longer queries are truncated before sending. |
| Memory content | 10 to 10,000 characters | Enforced by the server; violations come back `rejected` with HTTP 422. |
| Rules per response | 50 | Beyond this the server flags truncation and Rail reports a failure. |

## Timeouts and connections

Store timeout is seconds in Python and milliseconds in TypeScript, default 15
seconds, applied per HTTP operation including reading the body, not to the whole
turn. Redirects are
not followed. Python closes HTTP clients it creates; a supplied httpx client
remains owned by the caller. Async clients use `await store.aclose()` or an
async context manager. Node's native fetch owns its connection lifecycle.

## Concurrency

Use one `Rail` and one store per worker, thread, or event loop. The outbox
protects its own queue operations with a lock; the rest of a `Rail`, including
telemetry counters and cached tenant discovery, is not advertised as thread-safe.

## Naming

Configuration names use `snake_case` in Python and `camelCase` in TypeScript:
`top_k`/`topK`, `require_keystones`/`requireKeystones`,
`max_context_chars`/`maxContextChars`, `max_facts`/`maxFacts`,
`max_fact_chars`/`maxFactChars`. Pass a custom `Outbox` to choose capacity.
