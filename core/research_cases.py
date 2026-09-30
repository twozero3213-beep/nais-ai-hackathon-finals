# 작성: case95 등록사례·MCP 담당 | 2026-09-29 | 목적: 고정 공개사례와 N3 회귀를 기존 검증기로 연결
# 입력: 고정 case_id | 검증: tests/test_case95_cases_mcp.py; 등록/source/data snapshot 전후 일치
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from core.paths import PROJECT_ROOT
from core.activity_privacy import activity_view
from tools.case_registry import audit_registry, load_registry
from tools.change_impact import (_digest, _relative, snapshot_registry,
                                 snapshot_registry_with_preprocessing, snapshot_author_models)

PUBLIC_MANIFEST = PROJECT_ROOT / "data/evaluation/public_reproduction_cases.json"
WHEAT_MANIFEST = PROJECT_ROOT / "data/evaluation/second_domain/registered_cases.json"
WHEAT_MANIFEST_SHA256 = "77b53d0bc13fd32578722bfcf3485f6cfbe35241153796a10a0bde020643ce02"
# 작성: case105 통계·계보 담당 | 2026-09-29 | 외부 재실행의 집계·출처만 연결, 원자료·승인 제외
FOLLOWUP_EVIDENCE = PROJECT_ROOT / "data/evaluation/n3_followup_evidence.json"
FOLLOWUP_EVIDENCE_SHA256 = "96405eb54dbf7583db55d070a3a47fb1c4d7c830cb4b3cc080fe6da4acc7cddb"
CATALOG = {
    "n3_11814": {
        "label": "탐욕과 사회경제적 지위 4개 반복연구 계수 검산",
        "doi": "10.1038/sdata.2016.120",
        "scope": "4개 반복연구의 원래·정정 회귀계수 8개씩 산술 대조; 원자료 행 선택·변수 의미·모형 가정은 미확인.",
        "claim_ids": (),
        "paper_url": None,
    },
    "public_penguins": {
        "label": "팔머 펭귄 원자료 행 수",
        "doi": "10.32614/RJ-2022-020",
        "scope": "등록된 원자료 행 수 주장 1건의 산술 확인.",
        "claim_ids": ("PENG-RAW-ROWS",),
        "paper_url": "https://journal.r-project.org/articles/RJ-2022-020/",
    },
    "public_bat": {
        "label": "갈색지방(BAT) 양성 기록 수와 평균 연령",
        "doi": "10.1371/journal.pone.0149458",
        "scope": "논문에 기록된 갈색지방 양성 하위집단 주장 2건의 산술 확인.",
        "claim_ids": ("BAT-POSITIVE-N", "BAT-POSITIVE-MEAN-AGE"),
        "paper_url": "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0149458",
    },
    "public_covid_fair": {
        "label": "COVID FAIR URL 수와 평균 점수",
        "doi": "10.1371/journal.pone.0313991",
        "scope": "등록된 FAIR 필터 하위집단 주장 2건의 산술 확인; 저자 코드는 실행하지 않음.",
        "claim_ids": ("COVID-FAIR-URL-COUNT", "COVID-FAIR-MEAN"),
        "paper_url": "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0313991",
    },
}
EXTENSION_CATALOG = {
    "public_wheat": {
        "label": "밀 재배 실험의 개화기·성숙기 반복 단위 수",
        "doi": "10.1371/journal.pone.0198928",
        "scope": "대기 CO2·DW 수분처리의 실험 칼럼 수 3개·4개만 대조. 식물 수·ANOVA·수확량 효과·논문 전체 재현은 미확인.",
        "claim_ids": ("AGR2-ANTHESIS-AC02-DW-N", "AGR2-MATURITY-AC02-DW-N"),
        "paper_url": "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0198928",
    },
    "public_forest": {
        "label": "산불 공개자료 517행 부분 검산",
        "doi": "10.4996/fireecology.1101106",
        "scope": "등록 논문의 517건과 공개자료 행 수만 산술 대조. 예측모형·성능·논문 전체 재현은 미확인.",
        "claim_ids": ("FOREST-2015-N",),
        "paper_url": "https://doi.org/10.4996/fireecology.1101106",
    },
}

SCOPE_NOTES_KO = {
    "BAT-POSITIVE-N": "53행은 양성 스캔 기록 수입니다. 등록 원문은 양성 환자 한 명이 활성 스캔을 둘 이상 갖지 않았다고 설명합니다.",
    "BAT-POSITIVE-MEAN-AGE": "양성 하위집단 53행에서 Age.y 결측은 없고, 소수 둘째 자리 보고값에 허용오차 0.005를 적용합니다.",
    "COVID-FAIR-URL-COUNT": "원자료 6,180행에서 FAIR != 1 조건으로 5,700행을 선택한 등록 전처리 계약을 확인했습니다. 저자 코드는 실행하지 않았습니다.",
    "COVID-FAIR-MEAN": "평균은 등록된 FAIR 선택 CSV에서 계산했습니다. 저자 코드는 실행하지 않았습니다.",
    "PENG-RAW-ROWS": "이 검산은 펭귄 원자료의 행 수만 확인하며 결측 셀 수나 논문의 다른 주장은 포함하지 않습니다.",
}

N3_NEXT_ACTIONS = {
    "DF_DISAGREEMENT": "저자 방법과 구문에서 보고 자유도와 잔차 자유도 정의를 확인합니다.",
    "RAW_SELECTION_UNVERIFIED": "공개 선택 규칙으로 원자료 포함·제외 행과 공변량 재코딩을 대조합니다.",
    "SEMANTIC_UNVERIFIED": "원문 변수·대상과 계산 열의 대응을 근거 위치와 함께 검토합니다.",
    "ASSUMPTIONS_UNVERIFIED": "연구 설계와 저자 방법에 근거해 모형 가정을 확인합니다.",
    "INPUT_BLOCKED": "자료와 명세 지문을 확인한 뒤 같은 등록 모형을 다시 실행합니다.",
    "STATISTIC_DISAGREEMENT": "보고값, 단위, 반올림, 대상 열과 전처리 조건을 대조합니다.",
}


def supplemental_reproduction_evidence():
    """Return archived independently checked aggregates; never run an unsupported method."""
    raw = FOLLOWUP_EVIDENCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FOLLOWUP_EVIDENCE_SHA256:
        raise ValueError("Supplemental reproduction evidence fingerprint changed")
    evidence = json.loads(raw)
    evidence["n3_49665"]["case_id"] = "n3_49665"
    evidence["n3_49665"]["doi"] = "10.1111/evo.14483"
    evidence["n3_49665"]["notice_doi"] = "10.1093/evolut/qpad182"
    evidence["n3_49665"]["replacement_doi"] = "10.1093/evolut/qpad181"
    evidence["n3_49665"]["fresh_product_execution"] = False
    return evidence


def n3_followup_context(report):
    """Bind partial row evidence to current inputs; calculate df observations afresh."""
    evidence = supplemental_reproduction_evidence()
    context = []
    for index, run in enumerate(report["reports"]):
        raw = evidence["n3_11814"][index]
        current = run.get("data_sha256") == raw["registered_csv_sha256"]
        patterns = []
        for row in run["results"]:
            if not row["model_id"].endswith("/corrected"):
                continue
            n, df = row.get("n"), row.get("reported_df")
            pattern = "n-1" if isinstance(n, int) and df == n-1 else "n-2" if isinstance(n, int) and df == n-2 else "none"
            patterns.append({"model_id":row["model_id"], "n":n, "reported_df":df,
                             "residual_df":row.get("residual_df"), "observed_pattern":pattern,
                             "df_definition_verified":False})
        context.append({"replication":index+1, "input_binding":"MATCH" if current else "STALE",
                        "row_evidence":raw if current else None, "df_observations":patterns,
                        "raw_selection_verified":False, "completed":False,
                        "note":"응답열 다중집합 대응은 공개 제외 규칙·응답자 식별·재코딩 완료가 아닙니다. df 패턴은 정의 근거가 아닙니다."})
    return context


def _public_cases(case_id):
    entry = (CATALOG | EXTENSION_CATALOG)[case_id]
    if not entry["claim_ids"]:
        return []
    manifest = PUBLIC_MANIFEST
    if case_id == "public_wheat":
        manifest = WHEAT_MANIFEST
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != WHEAT_MANIFEST_SHA256:
            raise ValueError("Fixed wheat manifest fingerprint changed")
    if case_id == "public_forest":
        from core.team_case_intake import MANIFEST, MANIFEST_SHA256
        manifest = PROJECT_ROOT / MANIFEST
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST_SHA256:
            raise ValueError("Fixed forest manifest fingerprint changed")
    _, cases = load_registry(manifest)
    indexed = {case["claim_id"]: case for case in cases}
    selected = [indexed[cid] for cid in entry["claim_ids"] if cid in indexed]
    if len(selected) != len(entry["claim_ids"]) or any(case.get("paper_url") != entry["paper_url"] for case in selected):
        raise ValueError("Fixed case catalog does not match its registered DOI")
    return selected


def list_cases(include_extensions=False) -> list[dict[str, str]]:
    """Preserve the legacy four IDs; explicitly opt into partial extension cases."""
    return [
        {"id": case_id, "label": item["label"], "doi": item["doi"], "scope": item["scope"]}
        for case_id, item in (CATALOG | (EXTENSION_CATALOG if include_extensions else {})).items()
        if case_id == "n3_11814" or _public_cases(case_id)
    ]


def _manifest_hashes(manifests):
    try:
        return [{"path": Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix(),
                 "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()} for path in manifests]
    except (OSError, ValueError, RuntimeError) as error:
        raise ValueError("Registered manifest is unreadable or outside project") from error


# case105 재현성 담당: raw bytes 지문과 정규 JSON 적용조건 지문을 분리한다.
# 기존 snapshot의 실제 참조검증을 사용하며 제출된 과거 결과는 계산에 사용하지 않는다.
def _provenance(case_id, snapshot, manifests):
    inputs = []
    for row in snapshot["claims"]:
        metadata = row["metadata"]
        if "manifest_spec" in metadata:
            spec = metadata["manifest_spec"]
            model = next(m for m in spec["models"] if m["model_id"] == metadata["model_id"])
            conditions = {"scope": spec["scope"], "model": model, "derivations": spec.get("derivations", [])}
        else:
            conditions = {k: v for k, v in metadata.items() if k not in
                          {"source_file", "source_sha256", "data_file", "data_sha256"}}
        refs = {kind: dict(ref, path=ref["path"] if _relative(ref["path"]) else None)
                for kind, ref in row["references"].items()}
        inputs.append({"claim_id": row["claim_id"], **refs,
                       "registration_sha256": row["metadata_sha256"],
                       "contract_sha256": _digest(conditions), "conditions": conditions,
                       "status": row["status"],
                       "preprocessing": row.get("preprocessing")})
    return {"schema": "NAIS_CASE_PROVENANCE_1", "case_id": case_id,
            "fresh_execution": True, "binding_status": "BLOCKED_INPUT" if any(
                row["status"] == "BLOCKED_INPUT" for row in snapshot["claims"]) else "CONSISTENT",
            "snapshot_sha256": snapshot["content_sha256"], "manifest_hashes": manifests,
            "inputs": inputs, "execution_identity": snapshot["registry_metadata"].get("provenance"),
            "limitations": "SHA는 입력 내용결속이며 작성자·출처 진위 인증이 아닙니다. 계약 SHA는 정규 JSON 적용조건, source/data SHA와 manifest SHA는 각각 원시 bytes입니다. 산술 결과·의미·사람 승인을 대체하지 않습니다."}


def shared_provenance(provenance):
    """Date-free replay view, bound to the exact original provenance digest."""
    return dict(activity_view(provenance), provenance_view='NAIS_ACTIVITY_PROJECTION_1',
                original_provenance_sha256=_digest(provenance))


def _check_expected(expected, current):
    # case105 round 2: canonical JSON distinguishes bool/int/float; object key order is irrelevant.
    # Keep 1 and 1.0 distinct in this exact replay contract; arithmetic tolerance belongs to the audit.
    if expected is not None and _digest(expected) != _digest(
            shared_provenance(current) if isinstance(expected, dict) and
            expected.get('provenance_view') == 'NAIS_ACTIVITY_PROJECTION_1' else current):
        raise ValueError("Previous input binding differs; re-register current conditions")


def _public_run(case_id, entry, expected_provenance=None):
    from core.team_case_intake import MANIFEST as FOREST_MANIFEST, run_forest_intake
    selected = _public_cases(case_id)
    # 공개사례의 실행명세는 선택 subset이다. 다른 연구의 변경을 의존성으로 만들지 않는다.
    # 임시 경로는 반환하지 않고 실제 전달한 bytes의 종류와 SHA만 기록한다.
    selected_raw = json.dumps({"schema": 1, "cases": selected}, ensure_ascii=False).encode("utf-8")
    registered = (PROJECT_ROOT / FOREST_MANIFEST if case_id == "public_forest" else
                  WHEAT_MANIFEST if case_id == "public_wheat" else None)
    manifest_hashes = _manifest_hashes([registered]) if registered is not None else [
        {"kind": "executed_selected_registry", "sha256": hashlib.sha256(selected_raw).hexdigest()}]
    with TemporaryDirectory(prefix=".mcp-case-", dir=PROJECT_ROOT) as directory:
        manifest = Path(directory) / "selected.json"
        manifest.write_bytes(selected_raw)
        snapshot = snapshot_registry_with_preprocessing if any("preprocessing_contract" in c for c in selected) else snapshot_registry
        before = snapshot(manifest, root=PROJECT_ROOT)
        if expected_provenance is not None:
            _check_expected(expected_provenance, _provenance(case_id, before, manifest_hashes))
        if case_id == "public_forest":
            intake = run_forest_intake()
            report = intake.get("audit", {"results": [{"claim_id": "FOREST-2015-N", "action": "BLOCK"}]})
        else:
            report = audit_registry(manifest, root=PROJECT_ROOT)
        after = snapshot(manifest, root=PROJECT_ROOT)
        executed_manifest_stable = manifest.read_bytes() == selected_raw
    if (before != after or selected != _public_cases(case_id)
            or not executed_manifest_stable
            or registered is not None and manifest_hashes != _manifest_hashes([registered])):
        raise ValueError("Registered inputs changed during case run")
    if registered is None and report.get("manifest_sha256") != manifest_hashes[0]["sha256"]:
        raise ValueError("Executed manifest binding differs from current inputs")
    binding = _provenance(case_id, before, manifest_hashes)
    results = {row["claim_id"]: row for row in report["results"]}
    rows = []
    for case in selected:
        result = results[case["claim_id"]]
        calculated = result.get("value")
        reported = case.get("reported_value")
        rows.append({
            "claim_id": case["claim_id"],
            "reported_value": reported,
            "calculated_value": calculated,
            "difference": calculated - reported if calculated is not None and reported is not None else None,
            "tolerance": case.get("tolerance"),
            "unit": case.get("unit"),
            "status": result["action"],
        })
    counts = Counter(row["status"] for row in rows)
    known, unknown = [], []
    for case, row in zip(selected, rows):
        known.append(f"원문 등록 인용: {case['source_quote']} (위치: {case['source_location']}).")
        if case.get("license"):
            known.append(f"등록된 데이터 이용허락: {case['license']}.")
        if row["status"] == "ARITHMETIC_MATCH":
            # case105 round 2: fixed completed-scope notes require this claim's successful audit.
            if case["claim_id"] in SCOPE_NOTES_KO:
                known.append(SCOPE_NOTES_KO[case["claim_id"]])
            known.append(f"{case['claim_id']}: 제품 계산과 독립 계산이 등록 보고값에 산술 일치합니다.")
        else:
            unknown.append(f"{case['claim_id']}: 상태 {row['status']}; 등록 근거와 입력 지문을 확인해야 합니다.")
            if results[case["claim_id"]].get("reason"):
                unknown.append("차단 사유: 기존 등록 검증기의 세부 사유를 확인하세요.")
    unknown.append("주장의 의미와 모집단에 대한 사람 검토 기록은 없습니다. 산술 일치는 승인이나 논문 전체 재현이 아닙니다.")
    if case_id == "public_covid_fair":
        unknown.append("저자 코드는 실행하지 않았으며, 등록 FAIR 전처리 계약만 확인했습니다.")
    if case_id == "public_forest":
        unknown.append("517행 부분 검산입니다. CODE_MISSING·강우 UNIT_CONFLICT 유지; 예측모형·성능 재현은 미확인입니다.")
    if case_id == "public_wheat":
        known.append("두 CSV에서 CO2=a[CO2], WT=DW 조건만 선택했습니다. 한 행은 식물 한 개가 아니라 식물 3개가 든 실험 칼럼입니다.")
        unknown.append("두 처리 셀의 반복 단위 수만 검산했습니다. 식물 수·ANOVA·수확량 효과·논문 전체 재현은 확인하지 않았습니다.")
    return {
        "case_id": case_id,
        "label": entry["label"],
        "doi": entry["doi"],
        "scope": entry["scope"],
        "summary": {
            "claims": len(rows),
            "arithmetic_matches": counts["ARITHMETIC_MATCH"],
            "arithmetic_mismatches": counts["ARITHMETIC_MISMATCH"],
            "blocked": counts["BLOCK"],
        },
        "rows": rows,
        "known": list(dict.fromkeys(known)),
        "unknown": list(dict.fromkeys(unknown)),
        "next_actions": ["산술 결과를 해석하기 전에 원문 표현, 선택 모집단, 단위를 검토합니다."],
        "approved": False,
        "unresolved_reason_counts": {key: value for key, value in counts.items() if key != "ARITHMETIC_MATCH"},
        "provenance": binding,
    }


def _n3_run(entry, expected_provenance=None):
    from core.portfolio_workspace import AUTHOR_MODEL_MANIFESTS, model_followup_tasks, registered_model_comparison

    manifests = [PROJECT_ROOT / name for name in AUTHOR_MODEL_MANIFESTS]
    hashes = _manifest_hashes(manifests)
    before = snapshot_author_models(AUTHOR_MODEL_MANIFESTS, root=PROJECT_ROOT)
    binding = _provenance("n3_11814", before, hashes)
    _check_expected(expected_provenance, binding)
    report = registered_model_comparison()
    if before != snapshot_author_models(AUTHOR_MODEL_MANIFESTS, root=PROJECT_ROOT) or hashes != _manifest_hashes(manifests):
        raise ValueError("Registered inputs changed during case run")
    tasks = model_followup_tasks(report)
    reason_counts = Counter(task["reason_code"] for task in tasks)
    rows = []
    for run in report["reports"]:
        for model in run["results"]:
            for term, detail in (model.get("terms") or {"blocked": {}}).items():
                calculated, reported = detail.get("product"), detail.get("reported")
                rows.append({
                    "claim_id": model["model_id"] + "/" + term,
                    "reported_value": reported,
                    "calculated_value": calculated,
                    "difference": calculated - reported if calculated is not None and reported is not None else None,
                    "tolerance": detail.get("tolerance"),
                    "unit": None,
                    "status": model["action"],
                })
    return {
        "case_id": "n3_11814",
        "label": entry["label"],
        "doi": entry["doi"],
        "scope": entry["scope"],
        "summary": report["summary"],
        "rows": rows,
        "known": [
            f"이번 실행의 원래 모형 산술 일치 {report['summary']['original_matches']}개, 정정 모형 산술 일치 {report['summary']['corrected_matches']}개, 등록 모형 쌍 {report['summary']['model_pairs']}개입니다. 차단·불일치는 일치에 포함하지 않습니다.",
            "등록 provenance는 논문 DOI 10.1038/sdata.2016.120 및 정정 DOI 10.1038/sdata.2017.119를 기록합니다.",
            "등록 입력 지문 상태: " + binding["binding_status"] + ". 이용허락 등록은 CC BY 4.0이며 입력 차단은 수치 재현 성공이 아닙니다.",
            "저자 코드는 실행하지 않았습니다.",
        ],
        "unknown": [f"미해결 사유 {reason}: 관련 후속 작업 {count}건." for reason, count in sorted(reason_counts.items())]
                   + ["계수 산술만으로 원자료 행 선택, 변수 의미, 모형 가정을 확인하지 못합니다."],
        "next_actions": list(dict.fromkeys(N3_NEXT_ACTIONS[reason] for reason in sorted(reason_counts))),
        "approved": False,
        "unresolved_reason_counts": dict(reason_counts),
        "followup_evidence": n3_followup_context(report),
        "provenance": binding,
    }


def run_case(case_id: str, *, expected_provenance=None) -> dict[str, object]:
    """Run only an exact catalog ID through its existing guarded verification path."""
    if case_id not in CATALOG | EXTENSION_CATALOG:
        raise ValueError("Unknown registered case")
    entry = (CATALOG | EXTENSION_CATALOG)[case_id]
    if case_id == "n3_11814":
        return _n3_run(entry, expected_provenance)
    return _public_run(case_id, entry, expected_provenance)
