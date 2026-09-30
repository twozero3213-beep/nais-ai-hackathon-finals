import sqlite3
class AuditDB:
 def __init__(self,path='evidence_gate_case14.db'):
  self.con=sqlite3.connect(path,check_same_thread=False); self.con.execute('CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT DEFAULT CURRENT_TIMESTAMP,claim_id TEXT,actor TEXT,action TEXT,before_status TEXT,after_status TEXT,before_value REAL,after_value REAL,evidence_value REAL,reason TEXT)'); self.con.execute("CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END"); self.con.execute("CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END"); self.con.commit()
 def add(self,claim_id,actor,action,before_status,after_status,reason,before_value=None,after_value=None,evidence_value=None):
  self.con.execute('INSERT INTO audit(claim_id,actor,action,before_status,after_status,before_value,after_value,evidence_value,reason) VALUES(?,?,?,?,?,?,?,?,?)',(claim_id,actor,action,before_status,after_status,before_value,after_value,evidence_value,reason)); self.con.commit()
 def rows(self):return self.con.execute('SELECT at,claim_id,actor,action,before_status,after_status,before_value,after_value,evidence_value,reason FROM audit ORDER BY id DESC').fetchall()
 def clear(self):raise PermissionError('audit history is append-only; use a disposable test database')
