"""Reproduce the pinned synthetic evidence-boundary audit without model calls.

[작성: 0 이영 · Codex] 2026-10-01T05:23:45+09:00 — 공개 검증 자료를
개인 경로 없이 재실행하고 원문 의미/제품 승인/모델 성능의 범위를 구분한다.
The output directory must be empty. Product functions are never rewritten.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

REVISION = "d8d952b43eff8ab416421da8f0f431a64e8b9241"
MODULES = Path(__file__).resolve().parent / "evidence_boundary_audit"
KST = timezone(timedelta(hours=9))


def now():
    return datetime.now(KST).isoformat(timespec="seconds")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def write(path, value):
    path.write_bytes(canonical(value))


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, MODULES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_bytes(repo, path):
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{REVISION}:{path}"])


def exact_functions(raw, functions, constants=(), namespace=None):
    nodes = []
    for node in ast.parse(raw.decode("utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in functions:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constants for target in node.targets
        ):
            nodes.append(node)
    found = {node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    if found != set(functions):
        raise ValueError("PINNED_FUNCTION_SET_MISMATCH")
    namespace = {} if namespace is None else namespace
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 f"{REVISION}:unmodified-product-functions", "exec"), namespace)
    return namespace


def run_context(repo, output):
    raw = git_bytes(repo, "core/research_agent.py")
    common = "Target analysis: mean score. The analysis population is defined in the appendix. "
    padding = "Background material without a population definition. " * 110
    meta = {"id": "synthetic-context", "doi": "10.0000/synthetic-context", "locator": "Synthetic analysis"}
    pairs = []
    for name, style, expected_equal, expected_truncated in (
        ("late_definition_lost", "late", True, True),
        ("short_definition_kept", "short", False, False),
        ("early_definition_kept_despite_truncation", "early", False, True),
    ):
        texts = []
        for group in ("A", "B"):
            definition = f"The target analysis uses group {group} only. "
            texts.append(common + padding + definition if style == "late" else
                         definition + padding if style == "early" else common + definition)
        pairs.append({"id": name, "inputs": [[dict(meta, text=text)] for text in texts],
                      "expected_equal": expected_equal, "expected_truncated": expected_truncated})
    protocol = {"_change_note": "Freeze context-loss and preservation controls before execution.",
                "contributor_version": 0, "recorded_at_kst": now(), "git_revision": REVISION,
                "source_sha256": sha(raw), "pairs": pairs, "scope": "INPUT_INFORMATION_NOT_MODEL_BEHAVIOR"}
    write(output / "protocol.json", protocol)
    ns = exact_functions(raw, {"AgentError", "_bounded_text", "prepare_evidence"},
                         {"MAX_EVIDENCE", "MAX_EVIDENCE_BYTES", "MAX_EXCERPT_BYTES"})
    results = []
    for pair in pairs:
        a, at = ns["prepare_evidence"](pair["inputs"][0])
        b, bt = ns["prepare_evidence"](pair["inputs"][1])
        results.append({"id": pair["id"], "same_sendable_input": a == b,
                        "truncated": [at, bt], "sendable_sha256": [sha(a), sha(b)],
                        "full_input_sha256": [sha(item) for item in pair["inputs"]],
                        "group_definitions_visible": ["group A" in a[0]["text"], "group B" in b[0]["text"]],
                        "observation_matches": (a == b) == pair["expected_equal"]
                        and at == bt == pair["expected_truncated"]})
    receipt = {"_change_note": "Actual unchanged prepare_evidence output; no model or approval invoked.",
               "contributor_version": 0, "recorded_at_kst": now(), "git_revision": REVISION,
               "protocol_sha256": sha((output / "protocol.json").read_bytes()), "results": results}
    write(output / "results.json", receipt)
    return results


def run_binding(repo, output):
    raw = git_bytes(repo, "finals/finals_pipeline.py")
    dictionaries = [{"observation_unit": "individual"}, {"observation_unit": "visit"}]
    shared = {"input_sha256": sha(b"same CSV bytes"), "source_sha256": sha(b"same paper bytes")}
    cases = [dict(shared, codebook_sha256=sha(item)) for item in dictionaries]
    proposal = {"method": "mean", "column": "score", "filters": [{"column": "group", "value": "A"}]}
    protocol = {"_change_note": "Test future codebook integration; field is not supported by current binding API.",
                "contributor_version": 0, "recorded_at_kst": now(), "git_revision": REVISION,
                "source_sha256": sha(raw), "cases": cases, "dictionaries": dictionaries,
                "proposal": proposal, "expected_equal": True,
                "scope": "EXTENSION_DEPENDENCY_NOT_CURRENT_UI_BYPASS"}
    write(output / "protocol.json", protocol)
    ns = exact_functions(raw, {"_canonical", "_sha", "_input_bindings"}, namespace={"json": json, "hashlib": hashlib})
    values = [ns["_input_bindings"](case, proposal) for case in cases]
    receipt = {"_change_note": "Actual binding function output; no approval invoked.",
               "contributor_version": 0, "recorded_at_kst": now(), "git_revision": REVISION,
               "protocol_sha256": sha((output / "protocol.json").read_bytes()),
               "bindings": values, "bindings_equal": values[0] == values[1], "approval_calls": 0}
    write(output / "results.json", receipt)
    return receipt["bindings_equal"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Output must be a new or empty directory; prior evidence is not overwritten.")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("semantic", "source_gate", "context", "binding"):
        (output / name).mkdir()

    semantic = load_helper("semantic_probe")
    semantic.seal(args.repo.resolve(), output / "semantic")
    semantic_summary = semantic.run(args.repo.resolve(), output / "semantic")["summary"]

    source_gate = load_helper("source_gate_probe")
    source_gate.ROOT = output / "source_gate"
    source_gate.FIXTURE = source_gate.ROOT / "synthetic_fixture"
    snapshot = {"_change_note": "Pinned public Git blobs; saved paths are relative to the audit output.",
                "version": 0, "git_revision": REVISION, "snapshot_at_kst": now(),
                "code_source": "git object", "network_calls": 0, "paid_calls": 0, "files": []}
    for path in ("finals/finals_cases.py", "core/normalization.py", "finals/finals_pipeline.py"):
        raw = git_bytes(args.repo.resolve(), path)
        relative = Path("code_snapshot") / path
        target = source_gate.ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        snapshot["files"].append({"git_path": path, "sha256": sha(raw), "bytes": len(raw),
                                  "saved_path": relative.as_posix()})
    write(source_gate.ROOT / "0_이영_code_snapshot.json", snapshot)
    previous_directory = Path.cwd()
    try:
        # Relative snapshot paths keep private filesystem locations out of receipts.
        os.chdir(source_gate.ROOT)
        source_gate.prepare()
        source_gate.run()
    finally:
        os.chdir(previous_directory)
    context = run_context(args.repo.resolve(), output / "context")
    binding = run_binding(args.repo.resolve(), output / "binding")
    receipt = {"_change_note": "Public portable replay, separate from the original local experiments.",
               "contributor_version": 0, "recorded_at_kst": now(), "git_revision": REVISION,
               "runner_sha256": sha(Path(__file__).read_bytes()), "semantic_summary": semantic_summary,
               "context_pairs": context, "extension_binding_equal": binding,
               "model_calls": 0, "human_approvals": 0, "product_source_modified": False,
               "scope": "SYNTHETIC_COMPONENT_AUDIT_NOT_PERFORMANCE_OR_END_TO_END_APPROVAL"}
    write(output / "summary.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    assert semantic_summary["accepted"] == 10 and semantic_summary["rejected"] == 3
    assert all(item["observation_matches"] for item in context) and binding


if __name__ == "__main__":
    main()
