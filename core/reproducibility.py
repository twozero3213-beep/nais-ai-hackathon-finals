"""Deterministic reproduction identities and runtime snapshots.

case31 REPRODUCIBILITY CHANGE
FAILURE: case30 execution_id included the result, so two different results from the same
scientific inputs appeared to be unrelated executions instead of a determinism failure.
RISK: non-deterministic output could be hidden by different execution IDs.
WHY: scientific inputs identify a reproduction target; attempts and outputs are separate facts.
CHANGE: Reproduction Key = canonical scientific inputs; Attempt ID = individual run;
Result Hash = canonical output. Runtime package versions are snapshotted for traceability.
REGRESSION: tests/test_case31.py
"""
from __future__ import annotations
import hashlib, json, platform, sys, os, locale, time, io, contextlib
from importlib.metadata import version, PackageNotFoundError
from .source_revision import source_revision

_UNORDERED_LIST_KEYS={"filters","predictors","subgroup_dimensions","timepoints","reference_levels","interactions"}

def _normalise(value, key=""):
    if isinstance(value, dict):
        return {str(k):_normalise(v,str(k)) for k,v in sorted(value.items(),key=lambda kv:str(kv[0]))}
    if isinstance(value, (list,tuple)):
        vals=[_normalise(v,key) for v in value]
        if key in _UNORDERED_LIST_KEYS:
            vals=sorted(vals,key=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str))
        return vals
    if isinstance(value, float):
        if value == 0: return 0.0
        return float(format(value,'.15g'))
    return value

def canonicalise(value): return _normalise(value)
def canonical_json(value): return json.dumps(canonicalise(value),ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
def hash_json(value): return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()

def runtime_environment(random_seed=None):
    """Capture the execution environment that can materially affect numerical reproduction.

    case32 REPRODUCIBILITY CHANGE
    FAILURE: case31 captured package versions but not source revision, BLAS/LAPACK configuration,
    thread controls, locale, or timezone.
    RISK: numerically different environments could be grouped under the same reproduction target.
    CHANGE: add an environment manifest and source revision to the reproduction identity.
    """
    packages={}
    for p in ("pandas","numpy","scipy","statsmodels"):
        try: packages[p]=version(p)
        except PackageNotFoundError: packages[p]="not-installed"
    numpy_config="unavailable"
    try:
        import numpy as np
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf): np.show_config()
        numpy_config=buf.getvalue().strip()
    except Exception:
        pass
    thread_env={k:os.environ.get(k,"") for k in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS")}
    try: loc=locale.setlocale(locale.LC_ALL,None)
    except Exception: loc="unknown"
    return {"python":platform.python_version(),"implementation":platform.python_implementation(),"platform":platform.platform(),"machine":platform.machine(),"packages":packages,"numpy_config":numpy_config,"thread_env":thread_env,"locale":loc,"timezone":os.environ.get("TZ") or (time.tzname[0] if time.tzname else "unknown"),"source_revision":source_revision(),"random_seed":random_seed}

def reproduction_key(*,claim_snapshot,contract_snapshot,analysis_spec_snapshot,dataset_hash,engine_version,runtime_snapshot):
    # Result is intentionally excluded. Same inputs must map to the same reproduction target.
    payload={"claim":claim_snapshot,"contract":contract_snapshot,"analysis_spec":analysis_spec_snapshot,"dataset_hash":dataset_hash,"engine_version":engine_version,"runtime":runtime_snapshot}
    return 'RK-'+hash_json(payload)[:20]
