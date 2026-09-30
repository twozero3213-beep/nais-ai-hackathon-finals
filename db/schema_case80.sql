-- Evidence Gate case80 normalized relational schema (SQLite).
-- DDL principle: provenance relationships are enforced by PK/FK/CHECK/UNIQUE,
-- not only by Python. Audit events are append-only via triggers.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)));
CREATE TABLE IF NOT EXISTS roles(role_code TEXT PRIMARY KEY CHECK(role_code IN('VIEWER','ANALYST','REVIEWER','APPROVER','ADMIN')));
CREATE TABLE IF NOT EXISTS user_roles(user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, role_code TEXT NOT NULL REFERENCES roles(role_code) ON DELETE RESTRICT, PRIMARY KEY(user_id,role_code));
CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS datasets(dataset_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claims(claim_pk TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT, local_claim_id TEXT NOT NULL, claim_text TEXT NOT NULL, reported_value REAL, status TEXT NOT NULL CHECK(status IN('REVIEW','SUPPORTED','CONFLICT','VALIDATED')), UNIQUE(document_id,local_claim_id));
CREATE TABLE IF NOT EXISTS evidence(evidence_id TEXT PRIMARY KEY, claim_pk TEXT NOT NULL REFERENCES claims(claim_pk) ON DELETE CASCADE, dataset_id TEXT REFERENCES datasets(dataset_id) ON DELETE RESTRICT, locator TEXT NOT NULL, evidence_json TEXT NOT NULL, confirmed_by TEXT REFERENCES users(user_id) ON DELETE RESTRICT, confirmed_at TEXT);
CREATE TABLE IF NOT EXISTS verification_contracts(contract_id TEXT PRIMARY KEY, claim_pk TEXT NOT NULL REFERENCES claims(claim_pk) ON DELETE RESTRICT, version INTEGER NOT NULL CHECK(version>0), contract_type TEXT NOT NULL CHECK(contract_type IN('DESCRIPTIVE','COMPARATIVE','ASSOCIATION','REGRESSION','SCOPE')), contract_json TEXT NOT NULL, created_by TEXT REFERENCES users(user_id) ON DELETE RESTRICT, created_at TEXT NOT NULL, UNIQUE(claim_pk,version));
CREATE TABLE IF NOT EXISTS execution_attempts(attempt_id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES verification_contracts(contract_id) ON DELETE RESTRICT, dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE RESTRICT, reproduction_key TEXT NOT NULL, result_hash TEXT NOT NULL, result_json TEXT NOT NULL, app_version TEXT NOT NULL, engine_version TEXT NOT NULL, created_at TEXT NOT NULL, nondeterministic INTEGER NOT NULL DEFAULT 0 CHECK(nondeterministic IN(0,1)));
CREATE TABLE IF NOT EXISTS reviews(review_id TEXT PRIMARY KEY, claim_pk TEXT NOT NULL REFERENCES claims(claim_pk) ON DELETE RESTRICT, attempt_id TEXT REFERENCES execution_attempts(attempt_id) ON DELETE RESTRICT, reviewer_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT, decision TEXT NOT NULL CHECK(decision IN('ACCEPT','REJECT','REVISE')), note TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY, review_id TEXT NOT NULL UNIQUE REFERENCES reviews(review_id) ON DELETE RESTRICT, approver_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT, note TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN('ACTIVE','INVALIDATED','SUPERSEDED')), invalidated_at TEXT, superseded_by TEXT REFERENCES approvals(approval_id) ON DELETE RESTRICT);
CREATE TABLE IF NOT EXISTS audit_events(audit_id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL CHECK(length(trim(entity_type))>0), entity_id TEXT NOT NULL CHECK(length(trim(entity_id))>0), event_type TEXT NOT NULL CHECK(length(trim(event_type))>0), actor_id TEXT REFERENCES users(user_id) ON DELETE RESTRICT, payload_json TEXT NOT NULL CHECK(length(trim(payload_json))>0), app_version TEXT NOT NULL, engine_version TEXT NOT NULL, created_at TEXT NOT NULL, prev_hash TEXT NOT NULL DEFAULT '', event_hash TEXT NOT NULL CHECK(length(event_hash)=64));
CREATE INDEX IF NOT EXISTS idx_claim_document ON claims(document_id);
CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence(claim_pk);
CREATE INDEX IF NOT EXISTS idx_contract_claim ON verification_contracts(claim_pk,version);
CREATE INDEX IF NOT EXISTS idx_execution_contract ON execution_attempts(contract_id,created_at);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type,entity_id,created_at);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'audit_events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit_events are append-only'); END;
INSERT OR IGNORE INTO roles(role_code) VALUES('VIEWER'),('ANALYST'),('REVIEWER'),('APPROVER'),('ADMIN');
-- Separation of duties and least privilege are also enforced at the persistence boundary.
CREATE TRIGGER IF NOT EXISTS approval_separation BEFORE INSERT ON approvals
BEGIN
  SELECT CASE WHEN (SELECT reviewer_id FROM reviews WHERE review_id=NEW.review_id)=NEW.approver_id
    THEN RAISE(ABORT,'reviewer cannot approve own review') END;
  SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM users u JOIN user_roles ur ON ur.user_id=u.user_id WHERE u.user_id=NEW.approver_id AND u.active=1 AND ur.role_code IN('APPROVER','ADMIN'))
    THEN RAISE(ABORT,'approver must be active APPROVER/ADMIN') END;
  SELECT CASE WHEN (SELECT attempt_id FROM reviews WHERE review_id=NEW.review_id) IS NULL THEN RAISE(ABORT,'review must bind execution') END;
  SELECT CASE WHEN (SELECT attempt_id FROM reviews WHERE review_id=NEW.review_id) != (SELECT ea.attempt_id FROM execution_attempts ea JOIN verification_contracts vc ON vc.contract_id=ea.contract_id WHERE vc.claim_pk=(SELECT claim_pk FROM reviews WHERE review_id=NEW.review_id) ORDER BY ea.created_at DESC, ea.rowid DESC LIMIT 1) THEN RAISE(ABORT,'stale review cannot be approved') END;
END;
-- Reproducibility: any new execution changes the evidence state, so prior approval is no longer current.
CREATE TRIGGER IF NOT EXISTS execution_invalidates_approval AFTER INSERT ON execution_attempts
BEGIN
  UPDATE approvals SET status='INVALIDATED', invalidated_at=CURRENT_TIMESTAMP WHERE status='ACTIVE' AND review_id IN (SELECT r.review_id FROM reviews r JOIN verification_contracts vc ON vc.claim_pk=r.claim_pk WHERE vc.contract_id=NEW.contract_id);
END;
-- Chain continuity is enforced at DB boundary; event_hash content is reverified in Python.
CREATE TRIGGER IF NOT EXISTS audit_chain_prev BEFORE INSERT ON audit_events
BEGIN
  SELECT CASE WHEN NEW.prev_hash != COALESCE((SELECT event_hash FROM audit_events ORDER BY audit_id DESC LIMIT 1),'') THEN RAISE(ABORT,'audit prev_hash mismatch') END;

  SELECT CASE WHEN NEW.event_hash != eg_audit_hash(NEW.prev_hash,NEW.entity_type,NEW.entity_id,NEW.event_type,NEW.actor_id,NEW.payload_json,NEW.app_version,NEW.engine_version,NEW.created_at) THEN RAISE(ABORT,'audit event_hash mismatch') END;
END;
-- case74 hardening: audit identity prevents accidental duplicate logical events.
CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_event_identity ON audit_events(entity_type,entity_id,event_type,created_at);
