"""Shared identity, context, and result types."""

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol


class Visibility(str, Enum):
    """Who may recall a written fact. The server enforces the actual access."""

    AGENT = "scope_agent"
    TEAM = "scope_team"
    ORG = "scope_org"


@dataclass(frozen=True)
class MemoryScope:
    """Identity attached to every recall and write."""

    agent_id: str
    tenant_id: str | None = None
    fleet_id: str | None = None
    visibility: Visibility = Visibility.AGENT

    def __post_init__(self) -> None:
        for value in (self.agent_id, self.tenant_id, self.fleet_id):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("Scope identifiers must be nonempty strings")
        if not isinstance(self.agent_id, str):
            raise ValueError("agent_id is required")
        if not isinstance(self.visibility, Visibility):
            raise ValueError("visibility must be a Visibility value")
        if self.visibility == Visibility.TEAM and self.fleet_id is None:
            raise ValueError("TEAM visibility requires fleet_id")

    def for_agent(self, agent_id: str) -> "MemoryScope":
        """Return the same scope for another agent in the same tenant and fleet."""
        return replace(self, agent_id=agent_id)


@dataclass(frozen=True)
class Fact:
    id: str
    content: str
    agent_id: str | None = None


@dataclass(frozen=True)
class KeystoneRule:
    doc_id: str
    title: str
    content: str
    weight: int


@dataclass
class RecallContext:
    """Rules and facts fetched before the agent runs, plus recall diagnostics."""

    facts: list[Fact] = field(default_factory=list)
    keystones: list[KeystoneRule] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return bool(self.errors)

    @property
    def text(self) -> str:
        """Prompt-ready text. Rules come first; an empty context is an empty string."""
        sections = []
        if self.keystones:
            sections.append(
                "### GOVERNANCE RULES\n"
                + "\n".join(f"- {r.title}: {r.content}" for r in self.keystones)
            )
        if self.facts:
            sections.append(
                "### RECALLED MEMORY\n" + "\n".join(f"- {f.content}" for f in self.facts)
            )
        return "\n\n".join(sections)


@dataclass(frozen=True)
class WriteResult:
    """Outcome of one fact write.

    status is one of written, deduplicated, deferred, rejected, or dropped.
    """

    status: str
    id: str | None = None
    error: str | None = None


class StoreError(RuntimeError):
    """A memory backend failure. retryable=True means the outbox may replay it."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class MemoryStore(Protocol):
    """Synchronous backend used by Rail. Implementations raise StoreError on failure."""

    def recall(self, query: str, scope: MemoryScope, top_k: int = 8) -> list[Fact]: ...

    def keystones(self, scope: MemoryScope) -> list[KeystoneRule]: ...

    def write(self, fact: str, scope: MemoryScope) -> WriteResult: ...


class AsyncMemoryStore(Protocol):
    """Asynchronous backend used by AsyncRail. Implementations raise StoreError on failure."""

    async def recall(self, query: str, scope: MemoryScope, top_k: int = 8) -> list[Fact]: ...

    async def keystones(self, scope: MemoryScope) -> list[KeystoneRule]: ...

    async def write(self, fact: str, scope: MemoryScope) -> WriteResult: ...
