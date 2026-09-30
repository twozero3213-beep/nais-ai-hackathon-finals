"""P2 정규 명세 v2·변환기 시험. 실행: python -m unittest discover -s tests"""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from evidence_gate import convert
from evidence_gate.spec import FIELDS, METHODS, MISSING_POLICIES, empty_spec, from_extraction_v1, spec_sha256, validate

ROOT = Path(__file__).resolve().parents[1]
SHA = hashlib.sha256(b"example").hexdigest()


def base(method, **fields):
    spec = empty_spec(f"T-{method}")
    spec.update(method=method, data_fingerprint=SHA, tolerance=0, filters=[],
                source_location={"source_id": "S1", "locator": "p. 3", "quote": "보고 문장"})
    spec.update(fields)
    return spec


VALID = {
    "row_count": base("row_count", reported_value=10, missing_policy="not_applicable"),
    "mean": base("mean", reported_value=2.5, variable="x", missing_policy="complete_case", missing_tokens=[""]),
    "ols_regression": base("ols_regression", outcome="y", predictors=["x"], missing_policy="error", missing_tokens=["NA"],
                           reported={"x": {"b": 1.0, "se": None, "t": None}}, reported_df=3),
    "row_alignment": base("row_alignment", data_id_column="Species", reference_ids_source="treeall.nex TAXLABELS"),
}
REQUIRED_BY_METHOD = {"row_count": "reported_value", "mean": "variable", "ols_regression": "predictors",
                      "row_alignment": "data_id_column"}


class CanonicalSpecTest(unittest.TestCase):
    def test_each_method_valid(self):
        for method, spec in VALID.items():
            with self.subTest(method=method):
                self.assertEqual(validate(spec), {"ready": True, "errors": [], "missing": [], "unresolved": []})

    def test_each_method_missing_field_is_reported(self):
        for method, field in REQUIRED_BY_METHOD.items():
            with self.subTest(method=method):
                spec = copy.deepcopy(VALID[method])
                spec[field] = None
                check = validate(spec)
                self.assertFalse(check["ready"])
                self.assertIn(field, check["missing"])

    def test_unresolved_blocks_ready(self):
        spec = copy.deepcopy(VALID["mean"])
        spec["unresolved"] = ["분모가 원문에 없음"]
        self.assertFalse(validate(spec)["ready"])

    def test_structural_errors(self):
        spec = copy.deepcopy(VALID["mean"])
        spec["extra"] = 1
        spec["tolerance"] = -1
        spec["filters"] = [{"column": "g", "value": "a"}]
        spec["missing_policy"] = "not_applicable"
        errors = validate(spec)["errors"]
        self.assertIn("알 수 없는 필드: extra", errors)
        self.assertIn("tolerance: 0 이상", errors)
        self.assertIn("filters[0]: column·operator·value만 허용", errors)
        self.assertTrue(any(e.startswith("missing_policy") for e in errors))
        self.assertTrue(validate(dict(VALID["ols_regression"], reported={"z": {"b": 1, "se": None, "t": None}}))["errors"])

    def test_bool_is_not_a_number(self):
        self.assertIn("reported_value: 유한 숫자 또는 null", validate(dict(VALID["row_count"], reported_value=True))["errors"])

    def test_spec_hash_ignores_key_order(self):
        spec = VALID["mean"]
        self.assertEqual(spec_sha256(spec), spec_sha256(dict(reversed(list(spec.items())))))

    def test_schema_file_matches_validator_constants(self):
        schema = json.loads((ROOT / "evidence_gate" / "canonical_spec_v2.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["required"], list(FIELDS))
        self.assertEqual(schema["properties"]["method"]["enum"][:-1], list(METHODS))
        self.assertEqual(schema["properties"]["missing_policy"]["enum"][:-1], list(MISSING_POLICIES))

    def test_extraction_v1_upgrade_keeps_unknowns_open(self):
        v1 = {"claim_id": "C1", "reported_value": 344, "variable": None, "filters": [], "missing_policy": "not_applicable",
              "missing_tokens": None, "denominator": None, "method": "count_rows", "unit": None,
              "source_location": {"source_id": "S", "locator": "p. 1", "quote": "q"},
              "field_evidence": {"method": ["표 1"]}, "unresolved": []}
        spec = from_extraction_v1(v1)
        self.assertEqual(spec["method"], "row_count")
        check = validate(spec)
        self.assertEqual(check["errors"], [])
        self.assertEqual(set(check["missing"]), {"tolerance", "data_fingerprint"})


class ConverterTest(unittest.TestCase):
    CONTEXT = {"paper_url": "https://example.org/p", "source_file": "src.html", "source_sha256": SHA,
               "source_kind": "article_extract", "claim_text": "주장", "data_file": "data.csv",
               "scope_status": "EVALUATION_MAPPING"}

    def semantic(self, spec):
        keys = ("claim_id", "method", "reported_value", "variable", "filters", "missing_policy",
                "data_fingerprint", "tolerance", "source_location")
        return {k: spec[k] for k in keys}

    def test_proposal_round_trip_mean(self):
        spec = dict(VALID["mean"], denominator="전체 표본", unit="kg",
                    filters=[{"column": "g", "operator": "eq", "value": "A"}])
        out = convert.to_proposal_intake(spec)
        self.assertTrue(out["convertible"], out["unresolved"])
        self.assertEqual(out["target"]["evidence"], {"source_page": 3, "source_quote": "보고 문장"})
        self.assertEqual(out["target"]["filters"], [{"column": "g", "value": "A"}])
        self.assertIn("source_location.source_id", out["not_carried"])
        back = convert.from_proposal_intake(out["target"], source_id="S1", missing_tokens=[""])
        self.assertEqual(self.semantic(back), self.semantic(spec))
        self.assertEqual(validate(back)["errors"], [])

    def test_proposal_lossy_fields_become_unresolved(self):
        out = convert.to_proposal_intake(VALID["ols_regression"])
        self.assertFalse(out["convertible"])
        self.assertIsNone(out["target"])
        joined = " ".join(out["unresolved"])
        self.assertIn("ols_regression", joined)
        self.assertIn("missing_policy error", joined)
        self.assertIn("denominator", joined)
        section = dict(VALID["row_count"], source_location={"source_id": "S", "locator": "Main text", "quote": "q"})
        self.assertIn("source_location.locator: 자료 제안 형식은 정수 쪽 번호만 받음",
                      convert.to_proposal_intake(section)["unresolved"])

    def test_registry_round_trip_row_count_and_mean(self):
        for spec in (VALID["row_count"],
                     dict(VALID["mean"], filters=[{"column": "Island", "operator": "eq", "value": "Biscoe"}])):
            with self.subTest(method=spec["method"]):
                out = convert.to_case_registry(spec, self.CONTEXT)
                self.assertTrue(out["convertible"], out["unresolved"])
                target = out["target"]
                self.assertEqual(target["method"], {"row_count": "count_rows", "mean": "mean"}[spec["method"]])
                self.assertIsInstance(target["filters"], dict)
                back = convert.from_case_registry(target, source_id="S1")
                self.assertEqual(self.semantic(back), self.semantic(spec))

    def test_registry_lossy_fields_become_unresolved(self):
        spec = dict(VALID["mean"], missing_tokens=["NA"], filters=[{"column": "year", "operator": "eq", "value": 2007}])
        out = convert.to_case_registry(spec, {})
        self.assertFalse(out["convertible"])
        joined = " ".join(out["unresolved"])
        self.assertIn("context.paper_url", joined)
        self.assertIn("filters.year", joined)
        self.assertIn("빈 칸만 결측", joined)
        self.assertFalse(convert.to_case_registry(VALID["row_alignment"], self.CONTEXT)["convertible"])


if __name__ == "__main__":
    unittest.main()
