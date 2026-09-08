import asyncio

import pytest

from caura_rail import (
    AsyncRail,
    Fact,
    KeystoneRule,
    MemoryScope,
    Outbox,
    Rail,
    StoreError,
    WriteResult,
)

SCOPE = MemoryScope(agent_id="agent")


class Store:
    def __init__(self):
        self.facts = []
        self.fail = False
        self.retryable = True
        self.hook = None

    def keystones(self, scope):
        if self.fail:
            raise StoreError("outage", retryable=True)
        return []

    def recall(self, query, scope, top_k):
        return [Fact(str(i), f) for i, f in enumerate(self.facts)]

    def write(self, fact, scope):
        if self.hook:
            self.hook()
        if self.fail:
            raise StoreError("write failed", retryable=self.retryable)
        self.facts.append(fact)
        return WriteResult("written", id=str(len(self.facts)))


class AsyncStore(Store):
    async def keystones(self, scope):
        return super().keystones(scope)

    async def recall(self, query, scope, top_k):
        return super().recall(query, scope, top_k)

    async def write(self, fact, scope):
        return super().write(fact, scope)


def test_sync_failed_agent_never_commits():
    store = Store()
    rail = Rail(store, SCOPE)
    with pytest.raises(RuntimeError):
        with rail.turn("Remember: fact") as turn:
            turn.reply = "partial"
            raise RuntimeError("agent failed")
    assert store.facts == []


async def test_async_round_trip_and_failed_agent():
    store = AsyncStore()
    rail = AsyncRail(store, SCOPE)
    assert await rail.run("Remember: durable fact", lambda *_: "OK") == "OK"
    ctx = await rail.recall("what did we learn?")
    assert ctx.facts[0].content == "durable fact"
    with pytest.raises(asyncio.CancelledError):
        async with rail.turn("Remember: partial fact") as turn:
            turn.reply = "partial"
            raise asyncio.CancelledError()
    assert store.facts == ["durable fact"]


async def test_outage_and_permanent_failure():
    store = AsyncStore()
    store.fail = True
    rail = AsyncRail(store, SCOPE)
    async with rail.turn("Remember: fact") as turn:
        turn.reply = "answer"
    assert turn.degraded and turn.writes[0].status == "deferred"
    assert rail.telemetry.degraded_turns == 1
    assert len(rail.outbox) == 1
    store.fail = False
    assert (await rail.flush_outbox())[0].status == "written"
    assert len(rail.outbox) == 0
    store.fail, store.retryable = True, False
    assert await rail.run("Remember: rejected", lambda *_: "answer") == "answer"
    assert len(rail.outbox) == 0
    assert rail.telemetry.writes_rejected == 1


@pytest.mark.parametrize("value", [None, "not a list", [None], ["x" * 4001]])
async def test_bad_extractor_does_not_break_agent(value):
    store = AsyncStore()
    rail = AsyncRail(store, SCOPE, extractor=lambda *_: value)
    assert await rail.run("message", lambda *_: "answer") == "answer"
    assert rail.telemetry.extraction_failures == 1
    assert store.facts == []


async def test_governance_required_stops_before_agent():
    store = AsyncStore()
    store.fail = True
    rail = AsyncRail(store, SCOPE, require_keystones=True)
    called = []
    with pytest.raises(StoreError):
        await rail.run("message", lambda *_: called.append(True))
    assert called == []
    assert rail.telemetry.degraded_turns == 1


def test_replay_collision_is_counted_and_attempts_bounded():
    store = Store()
    store.fail = True
    rail = Rail(store, SCOPE, outbox=Outbox(1))
    rail.run("Remember: old", lambda *_: "OK")

    def enqueue_during_write():
        store.hook = None
        rail.run("Remember: new", lambda *_: "OK")

    store.hook = enqueue_during_write
    assert rail.flush_outbox()[0].status == "deferred"
    assert rail.outbox.total_dropped == 1
    assert len(rail.outbox) == 1
    assert rail.flush_outbox(max_attempts=2)[0].status == "dropped"
    assert rail.outbox.total_dropped == 2
    assert len(rail.outbox) == 0


async def test_cancelled_flush_restores_unprocessed_items():
    store = AsyncStore()
    store.fail = True
    rail = AsyncRail(store, SCOPE)
    await rail.run("Remember: first\nRemember: second", lambda *_: "OK")

    async def cancelled(*_):
        raise asyncio.CancelledError()

    store.write = cancelled
    with pytest.raises(asyncio.CancelledError):
        await rail.flush_outbox()
    assert len(rail.outbox) == 2


def test_budget_preserves_rules_and_reports_omitted_facts():
    store = Store()
    store.keystones = lambda _: [KeystoneRule("rule", "Policy", "Preserve me", 100)]
    store.facts = ["x" * 100]
    rail = Rail(store, SCOPE, max_context_chars=80)
    ctx = rail.recall("query")
    assert ctx.keystones and not ctx.facts
    assert ctx.errors == ["facts_context_truncated"]
    assert len(ctx.text) <= 80
