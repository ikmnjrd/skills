from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SourceRef:
    source_id: str
    source_kind: str
    line: int


@dataclass
class ProjectRef:
    project_id: str
    name: str
    display_path: str


@dataclass
class OperationEvent:
    event_id: str
    product: str
    timestamp: str | None
    category: str
    support_level: str
    tool: str
    project: ProjectRef
    source: SourceRef
    outcome: str = "requested-only"
    command: str | None = None
    executable: str | None = None
    normalized_shape: str | None = None
    parse_status: str | None = None
    targets: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    call_id: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("call_id", None)
        return {key: value for key, value in result.items() if value not in (None, [], {})}
