"""Memory operations around Python agent invocations."""

from importlib.metadata import version

from .models import (
    Fact,
    KeystoneRule,
    MemoryScope,
    RecallContext,
    StoreError,
    Visibility,
    WriteResult,
)
from .rail import AsyncRail, Outbox, Rail, Telemetry, TurnResult, rule_extract
from .store import AsyncRestMemoryStore, RestMemoryStore

__version__ = version("caura-rail")
__all__ = [
    "AsyncRail",
    "AsyncRestMemoryStore",
    "Fact",
    "KeystoneRule",
    "MemoryScope",
    "Outbox",
    "Rail",
    "RecallContext",
    "RestMemoryStore",
    "StoreError",
    "Telemetry",
    "TurnResult",
    "Visibility",
    "WriteResult",
    "rule_extract",
]
