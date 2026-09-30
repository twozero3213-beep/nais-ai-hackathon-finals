"""Benchmark provenance: raw bytes + canonical semantic fingerprint."""
from __future__ import annotations
import hashlib,json

def sha256_bytes(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def canonical_json_sha256(data:bytes)->str:
    obj=json.loads(data.decode('utf-8-sig'))
    canonical=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
def provenance(data:bytes,*,source,adapter_version,engine_version):
    return {'raw_sha256':sha256_bytes(data),'canonical_sha256':canonical_json_sha256(data),'source':source,'adapter_version':adapter_version,'engine_version':engine_version}
def official_match(report,registry):
    key=(report.get('source'),report.get('canonical_sha256'))
    return key in {(x.get('source'),x.get('canonical_sha256')) for x in registry}
