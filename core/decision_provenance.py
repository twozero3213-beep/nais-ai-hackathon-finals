"""Canonical decision provenance API.
PROPOSED != SELECTED != CONFIRMED != EXECUTED.
Versioned provenance modules remain legacy compatibility only.
"""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
def _now():return datetime.now(timezone.utc).isoformat(timespec="seconds")
@dataclass
class DecisionProvenance:
    value:str="";source:str="system_candidate";source_location:str="";proposed_by:str="SYSTEM";selected_by:str="";selected_at:str="";confirmed_by:str="";confirmed_at:str="";score:float|None=None
    @property
    def selected(self):return bool(self.selected_by and self.selected_at)
    @property
    def confirmed(self):return bool(self.confirmed_by and self.confirmed_at)
    def select(self,actor="HUMAN"):self.selected_by=actor;self.selected_at=_now();return self
    def confirm(self,actor="HUMAN"):
        if not self.selected:self.select(actor)
        self.confirmed_by=actor;self.confirmed_at=_now();return self
    def to_dict(self):return asdict(self)
def proposed(value,*,source="system_candidate",source_location="",score=None):return DecisionProvenance(value=str(value or ""),source=source,source_location=source_location,score=score)
def is_confirmed(record):return bool(record and record.get("confirmed_by") and record.get("confirmed_at"))
