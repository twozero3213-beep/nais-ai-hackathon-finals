"""Stable filesystem paths for Evidence Gate.

case30 AUDIT SAFETY
FAILURE: case29 audit paths depended on the process current working directory.
RISK: launching from another directory could silently create a second audit ledger.
WHY: audit storage must resolve to one deterministic location.
CHANGE: persistent paths are anchored to PROJECT_ROOT, with optional environment overrides.
"""
import os
from pathlib import Path
PROJECT_ROOT=Path(__file__).resolve().parents[1]
DATA_DIR=Path(os.environ.get("EVIDENCE_GATE_DATA_DIR",PROJECT_ROOT/"data")).resolve()
LOG_DIR=Path(os.environ.get("EVIDENCE_GATE_LOG_DIR",PROJECT_ROOT/"logs")).resolve()
DATA_DIR.mkdir(parents=True,exist_ok=True); LOG_DIR.mkdir(parents=True,exist_ok=True)
AUDIT_DB_PATH=DATA_DIR/"audit.db"
CHANGE_DB_PATH=DATA_DIR/"changes.db"
AUDIT_JSONL_PATH=LOG_DIR/"audit.jsonl"
RUNTIME_LOG_PATH=LOG_DIR/"runtime.log"
