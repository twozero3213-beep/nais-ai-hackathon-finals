"""Reusable candidate/confirmed provenance records for Evidence Gate case28."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

@dataclass
class ProvenanceRecord:
    value: str = ""
    source: str = "system_candidate"
    source_location: str = ""
    proposed_by: str = "SYSTEM"
    confirmed_by: str = ""
    confirmed_at: str = ""
    score: float | None = None

    @property
    def confirmed(self) -> bool:
        return bool(self.confirmed_by and self.confirmed_at)

    def confirm(self, actor: str = "HUMAN") -> "ProvenanceRecord":
        self.confirmed_by = actor
        self.confirmed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return self

    def to_dict(self):
        return asdict(self)


def candidate(value:str, *, source="system_candidate", source_location="", score=None) -> ProvenanceRecord:
    return ProvenanceRecord(value=value, source=source, source_location=source_location, score=score)
