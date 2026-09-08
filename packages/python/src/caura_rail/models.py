"""Shared identity, context, and result types."""

from dataclasses import dataclass, field, replace
from enum import Enum


class Visibility(str, Enum):
    AGENT = "scope_agent"
    TEAM = "scope_team"
    ORG = "scope_org"


@dataclass(frozen=True)
class MemoryScope:
    agent_id: str
    tenant_id: str | None = None
    fleet_id: str | None = None
    visibility: Visibility = Visibility.AGENT

    def __post_init__(self):
        for value in (self.agent_id, self.tenant_id, self.fleet_id):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("Scope identifiers must be nonempty strings")
        if not isinstance(self.agent_id, str):
            raise ValueError("agent_id is required")
        if not isinstance(self.visibility, Visibility):
            raise ValueError("visibility must be a Visibility value")
        if self.visibility == Visibility.TEAM and self.fleet_id is None:
            raise ValueError("TEAM visibility requires fleet_id")

    def for_agent(self, agent_id: str):
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
    facts: list[Fact] = field(default_factory=list)
    keystones: list[KeystoneRule] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        return bool(self.errors)

    @property
    def text(self) -> str:
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
    status: str
    id: str | None = None
    error: str | None = None


class StoreError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
