"""Normalized case73 persistence layer.

All writes use explicit transactions so one logical verification action is atomic.
Foreign keys are enabled on every connection; callers cannot create orphan claims,
contracts, executions, reviews, or approvals.
"""
import sqlite3
from .canonical_service import _sql_audit_hash
from pathlib import Path

class RelationalStore:
    def __init__(self,path,schema_path=None):
        self.path=str(Path(path).resolve()); Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        self.con=sqlite3.connect(self.path,check_same_thread=False); self.con.create_function('eg_audit_hash',9,_sql_audit_hash,deterministic=True)
        self.con.execute('PRAGMA foreign_keys=ON'); self.con.execute('PRAGMA busy_timeout=5000'); self.con.execute('PRAGMA journal_mode=WAL')
        schema=Path(schema_path or Path(__file__).resolve().parents[1]/'db'/'schema_case80.sql').read_text(encoding='utf-8')
        self.con.executescript(schema); self.con.commit()
    def transaction(self): return self.con
    def integrity(self): return self.con.execute('PRAGMA integrity_check').fetchone()[0]
    def foreign_key_violations(self): return self.con.execute('PRAGMA foreign_key_check').fetchall()
