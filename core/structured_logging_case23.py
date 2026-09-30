"""Structured JSONL event logging for reproducible case24 debugging/audit support."""
from __future__ import annotations
from datetime import datetime,timezone
import json, logging
from pathlib import Path

class JsonLineFormatter(logging.Formatter):
    def format(self,record):
        payload={
            "at":datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level":record.levelname,
            "logger":record.name,
            "event":getattr(record,"event","LOG"),
            "message":record.getMessage(),
        }
        for key in ("claim_id","contract_type","dataset_hash","state","rows_used","engine"):
            val=getattr(record,key,None)
            if val not in (None,""):payload[key]=val
        if record.exc_info:payload["exception"]=self.formatException(record.exc_info)
        return json.dumps(payload,ensure_ascii=False,default=str)

def get_event_logger(path="logs/evidence_gate_case24.jsonl"):
    # case24 CHANGE — WHY: free-text logs were hard for four team members to search consistently.
    # JSONL gives every failure/execution the same searchable fields while remaining human-readable.
    logger=logging.getLogger("evidence_gate_case24.events")
    if logger.handlers:return logger
    Path(path).parent.mkdir(parents=True,exist_ok=True);logger.setLevel(logging.INFO)
    h=logging.FileHandler(path,encoding="utf-8");h.setFormatter(JsonLineFormatter());logger.addHandler(h)
    return logger

def event(logger,name,message="",**fields):
    logger.info(message or name,extra={"event":name,**fields})
