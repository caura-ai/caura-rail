"""Memory operations around Python agent invocations."""

from importlib.metadata import version

from .models import (
    AsyncMemoryStore,
    Fact,
    KeystoneRule,
    MemoryScope,
    MemoryStore,
    RecallContext,
    StoreError,
    Visibility,
    WriteResult,
)
from .rail import (
    Agent,
    AsyncAgent,
    AsyncExtractor,
    AsyncRail,
    AsyncTurn,
    Extractor,
    Outbox,
    Rail,
    Telemetry,
    Turn,
    TurnResult,
    rule_extract,
)
from .store import AsyncRestMemoryStore, RestMemoryStore

__version__ = version("caura-rail")
__all__ = [
    "Agent",
    "AsyncAgent",
    "AsyncExtractor",
    "AsyncMemoryStore",
    "AsyncRail",
    "AsyncRestMemoryStore",
    "AsyncTurn",
    "Extractor",
    "Fact",
    "KeystoneRule",
    "MemoryScope",
    "MemoryStore",
    "Outbox",
    "Rail",
    "RecallContext",
    "RestMemoryStore",
    "StoreError",
    "Telemetry",
    "Turn",
    "TurnResult",
    "Visibility",
    "WriteResult",
    "__version__",
    "rule_extract",
]
