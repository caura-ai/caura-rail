"""Turn orchestration and bounded, explicit write replay."""

import inspect
import re
from collections import deque
from dataclasses import dataclass, field
from threading import Lock

from .models import MemoryScope, RecallContext, StoreError, WriteResult


def rule_extract(user_msg: str, reply: str) -> list[str]:
    """A deliberately small heuristic over user statements, not assistant output."""
    pattern = re.compile(r"^(remember:\s*|we (use|deploy)\b|our (plan|contract)\b)", re.I)
    return list(
        dict.fromkeys(
            re.sub(r"^remember:\s*", "", line.strip(), flags=re.I)
            for line in user_msg.splitlines()
            if pattern.search(line.strip())
        )
    )


@dataclass
class Telemetry:
    turns_total: int = 0
    degraded_turns: int = 0
    writes_deferred: int = 0
    writes_rejected: int = 0
    extraction_failures: int = 0


@dataclass
class _Pending:
    fact: str
    scope: MemoryScope
    attempts: int = 0


class Outbox:
    """In-memory queue. Every capacity eviction is counted; nothing is persisted."""

    def __init__(self, capacity: int = 1000):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self._total_dropped = 0
        self._queue: deque[_Pending] = deque()
        self._lock = Lock()

    def _push(self, item: _Pending):
        with self._lock:
            if len(self._queue) == self.capacity:
                self._queue.popleft()
                self._total_dropped += 1
            self._queue.append(item)

    def _take(self):
        with self._lock:
            batch = list(self._queue)
            self._queue.clear()
            return batch

    def __len__(self):
        with self._lock:
            return len(self._queue)

    @property
    def total_dropped(self):
        with self._lock:
            return self._total_dropped

    def _drop(self):
        with self._lock:
            self._total_dropped += 1


@dataclass
class TurnResult:
    context: RecallContext = field(default_factory=RecallContext)
    reply: str | None = None
    writes: list[WriteResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def degraded(self):
        return self.context.degraded or bool(self.errors)


class _Core:
    def __init__(
        self,
        store,
        scope: MemoryScope,
        *,
        extractor=rule_extract,
        outbox: Outbox | None = None,
        top_k: int = 8,
        require_keystones: bool = False,
        max_context_chars: int = 16000,
        max_facts: int = 16,
        max_fact_chars: int = 4000,
    ):
        for value in (top_k, max_context_chars, max_facts, max_fact_chars):
            if type(value) is not int or value < 1:
                raise ValueError("Limits must be positive integers")
        if not isinstance(scope, MemoryScope):
            raise ValueError("scope must be a MemoryScope")
        self.store, self.scope = store, scope
        self.extractor = extractor
        self.outbox = outbox if outbox is not None else Outbox()
        self.top_k = top_k
        self.require_keystones = require_keystones
        self.max_context_chars, self.max_facts = max_context_chars, max_facts
        self.max_fact_chars = max_fact_chars
        self.telemetry = Telemetry()

    def _limit_context(self, ctx):
        facts, ctx.facts = ctx.facts, []
        if len(ctx.text) > self.max_context_chars:
            if self.require_keystones:
                raise StoreError("Governance rules exceed the context budget")
            ctx.keystones = []
            ctx.errors.append("governance_context_overflow")
        for fact in facts:
            ctx.facts.append(fact)
            if len(ctx.text) > self.max_context_chars:
                ctx.facts.pop()
                ctx.errors.append("facts_context_truncated")
                break
        return ctx

    def _validate_facts(self, facts):
        if not isinstance(facts, list) or len(facts) > self.max_facts:
            raise ValueError("Extractor must return a bounded list of strings")
        if any(not isinstance(f, str) or len(f) > self.max_fact_chars for f in facts):
            raise ValueError("Extractor returned an invalid fact")
        return list(dict.fromkeys(f.strip() for f in facts if f.strip()))

    def _write_failed(self, fact, exc):
        if exc.retryable:
            self.outbox._push(_Pending(fact, self.scope))
            self.telemetry.writes_deferred += 1
            return WriteResult("deferred", error=str(exc))
        self.telemetry.writes_rejected += 1
        return WriteResult("rejected", error=str(exc))

    def _finish(self, turn):
        if turn.degraded:
            self.telemetry.degraded_turns += 1

    @staticmethod
    def _validate_message(message):
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a nonempty string")


class Rail(_Core):
    def recall(self, query: str) -> RecallContext:
        self._validate_message(query)
        ctx = RecallContext()
        try:
            ctx.keystones = self.store.keystones(self.scope)
        except StoreError as exc:
            if self.require_keystones:
                raise
            ctx.errors.append("keystones: " + str(exc))
        try:
            ctx.facts = self.store.recall(query, self.scope, self.top_k)
        except StoreError as exc:
            ctx.errors.append("recall: " + str(exc))
        return self._limit_context(ctx)

    def turn(self, message: str):
        self._validate_message(message)
        return _Turn(self, message)

    def run(self, message: str, agent) -> str:
        with self.turn(message) as turn:
            turn.reply = agent(message, turn.context)
        return turn.reply

    def _commit(self, message, turn):
        try:
            raw = self.extractor(message, turn.reply)
            if inspect.iscoroutine(raw):
                raw.close()
                raise ValueError("Use AsyncRail for asynchronous extractors")
            facts = self._validate_facts(raw)
        except Exception:
            self.telemetry.extraction_failures += 1
            turn.errors.append("extraction_failed")
            return
        for fact in facts:
            try:
                result = self.store.write(fact, self.scope)
            except StoreError as exc:
                result = self._write_failed(fact, exc)
                turn.errors.append(result.status)
            turn.writes.append(result)

    def flush_outbox(self, max_attempts: int = 3) -> list[WriteResult]:
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        batch, results = self.outbox._take(), []
        for i, item in enumerate(batch):
            item.attempts += 1
            try:
                results.append(self.store.write(item.fact, item.scope))
            except StoreError as exc:
                if exc.retryable and item.attempts < max_attempts:
                    self.outbox._push(item)
                    results.append(WriteResult("deferred", error=str(exc)))
                else:
                    self.outbox._drop()
                    results.append(WriteResult("dropped", error=str(exc)))
            except BaseException:
                for pending in batch[i:]:
                    self.outbox._push(pending)
                raise
        return results


class _Turn(TurnResult):
    def __init__(self, rail, message):
        super().__init__()
        self._rail, self._message = rail, message

    def __enter__(self):
        self._rail.telemetry.turns_total += 1
        try:
            self.context = self._rail.recall(self._message)
        except StoreError:
            self._rail.telemetry.degraded_turns += 1
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None and self.reply is not None:
                if not isinstance(self.reply, str):
                    if inspect.iscoroutine(self.reply):
                        self.reply.close()
                    raise TypeError("Agent reply must be a string; use AsyncRail for async agents")
                self._rail._commit(self._message, self)
        finally:
            self._rail._finish(self)


class AsyncRail(_Core):
    async def recall(self, query: str) -> RecallContext:
        self._validate_message(query)
        ctx = RecallContext()
        try:
            ctx.keystones = await self.store.keystones(self.scope)
        except StoreError as exc:
            if self.require_keystones:
                raise
            ctx.errors.append("keystones: " + str(exc))
        try:
            ctx.facts = await self.store.recall(query, self.scope, self.top_k)
        except StoreError as exc:
            ctx.errors.append("recall: " + str(exc))
        return self._limit_context(ctx)

    def turn(self, message: str):
        self._validate_message(message)
        return _AsyncTurn(self, message)

    async def run(self, message: str, agent) -> str:
        async with self.turn(message) as turn:
            reply = agent(message, turn.context)
            turn.reply = await reply if inspect.isawaitable(reply) else reply
        return turn.reply

    async def _commit(self, message, turn):
        try:
            raw = self.extractor(message, turn.reply)
            facts = self._validate_facts(await raw if inspect.isawaitable(raw) else raw)
        except Exception:
            self.telemetry.extraction_failures += 1
            turn.errors.append("extraction_failed")
            return
        for fact in facts:
            try:
                result = await self.store.write(fact, self.scope)
            except StoreError as exc:
                result = self._write_failed(fact, exc)
                turn.errors.append(result.status)
            turn.writes.append(result)

    async def flush_outbox(self, max_attempts: int = 3) -> list[WriteResult]:
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        batch, results = self.outbox._take(), []
        for i, item in enumerate(batch):
            item.attempts += 1
            try:
                results.append(await self.store.write(item.fact, item.scope))
            except StoreError as exc:
                if exc.retryable and item.attempts < max_attempts:
                    self.outbox._push(item)
                    results.append(WriteResult("deferred", error=str(exc)))
                else:
                    self.outbox._drop()
                    results.append(WriteResult("dropped", error=str(exc)))
            except BaseException:
                for pending in batch[i:]:
                    self.outbox._push(pending)
                raise
        return results


class _AsyncTurn(TurnResult):
    def __init__(self, rail, message):
        super().__init__()
        self._rail, self._message = rail, message

    async def __aenter__(self):
        self._rail.telemetry.turns_total += 1
        try:
            self.context = await self._rail.recall(self._message)
        except StoreError:
            self._rail.telemetry.degraded_turns += 1
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type is None and self.reply is not None:
                if not isinstance(self.reply, str):
                    raise TypeError("Agent reply must be a string")
                await self._rail._commit(self._message, self)
        finally:
            self._rail._finish(self)
