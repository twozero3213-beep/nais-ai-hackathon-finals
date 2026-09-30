"""Parameterized DML for the normalized Evidence Gate schema.

The repository deliberately exposes domain operations instead of arbitrary SQL.
Every multi-row write is transactional; foreign keys/check constraints remain the
last line of defence if application validation is bypassed.
"""
import json, uuid
from datetime import datetime, timezone

def _now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds')
def _id(prefix): return prefix+'-'+uuid.uuid4().hex[:20]

class EvidenceRepository:
    def __init__(self, store): self.store=store; self.con=store.con
    def add_user(self,user_id,name,role='VIEWER'):
        with self.con:
            self.con.execute('INSERT INTO users(user_id,display_name) VALUES(?,?)',(user_id,name))
            self.con.execute('INSERT INTO user_roles(user_id,role_code) VALUES(?,?)',(user_id,role))
    def add_document(self,document_id,sha256,name):
        with self.con:self.con.execute('INSERT INTO documents VALUES(?,?,?,?)',(document_id,sha256,name,_now()))
    def add_dataset(self,dataset_id,sha256,name):
        with self.con:self.con.execute('INSERT INTO datasets VALUES(?,?,?,?)',(dataset_id,sha256,name,_now()))
    def add_claim(self,claim_pk,document_id,local_claim_id,text,reported_value=None,status='REVIEW'):
        with self.con:self.con.execute('INSERT INTO claims VALUES(?,?,?,?,?,?)',(claim_pk,document_id,local_claim_id,text,reported_value,status))
    def add_contract(self,contract_id,claim_pk,version,contract_type,payload,created_by=None):
        with self.con:self.con.execute('INSERT INTO verification_contracts VALUES(?,?,?,?,?,?,?)',(contract_id,claim_pk,version,contract_type,json.dumps(payload,ensure_ascii=False,sort_keys=True),created_by,_now()))
    def review_and_approve(self,*,claim_pk,attempt_id,reviewer_id,decision,note,approver_id=None,approval_note=None):
        review_id=_id('RV')
        with self.con:
            self.con.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(review_id,claim_pk,attempt_id,reviewer_id,decision,note,_now()))
            approval_id=None
            if approver_id:
                if approver_id==reviewer_id: raise ValueError('reviewer and approver must be different users')
                approval_id=_id('AP')
                self.con.execute('INSERT INTO approvals VALUES(?,?,?,?,?)',(approval_id,review_id,approver_id,approval_note or '',_now()))
        return review_id,approval_id
