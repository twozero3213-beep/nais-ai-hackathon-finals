"""경계 입력에서도 예외로 죽지 않고 판정을 남기며, 큰 오프셋 자료에서도 회귀가 정확한지 확인한다.

# [작성: 0 이영 · Claude] 2026-09-30 KST — 1 이채우 경계 검증(1_이채우_경계검증_실행결과.json)에서 재현된 결함의 회귀 시험.
# 각 시험은 수정 전 코드에서 실패한다(예외 또는 틀린 값). 판정 규칙·허용오차는 바꾸지 않는다.
"""
import copy
import hashlib
import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from evidence_gate.__main__ import main
from evidence_gate.align import reference_ids_sha256
from evidence_gate.compute import GateError, mean, ols
from evidence_gate.gate import evaluate
from evidence_gate.spec import empty_spec, validate, spec_sha256


def spec_for(data, method, **fields):
    spec = empty_spec("BOUNDARY")
    spec.update(method=method, filters=[], tolerance=1e-9, missing_policy="error", missing_tokens=[""],
                data_fingerprint=hashlib.sha256(data).hexdigest(),
                source_location={"source_id": "S", "locator": "L", "quote": "q"})
    spec.update(fields)
    return spec


class MalformedSpecTest(unittest.TestCase):
    def test_method_array_is_blocked_not_raised(self):
        data = b"a\n1\n"
        result = evaluate(spec_for(data, ["row_count"], reported_value=1), data)
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "SPEC_NOT_READY"))

    def test_nonfinite_reported_value_is_blocked_not_raised(self):
        data = b"a\n1\n"
        result = evaluate(spec_for(data, "row_count", reported_value=float("nan")), data)
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "SPEC_NOT_READY"))
        self.assertIsNone(result["spec_sha256"])

    def test_huge_integer_is_not_a_number_and_does_not_overflow(self):
        data = b"a\n1\n"
        check = validate(spec_for(data, "row_count", reported_value=10 ** 400))
        self.assertFalse(check["ready"])
        result = evaluate(spec_for(data, "row_count", reported_value=10 ** 400), data)
        self.assertEqual(result["reason_code"], "SPEC_NOT_READY")


class NumericBoundaryTest(unittest.TestCase):
    def test_finite_mean_near_float_limit_does_not_overflow(self):
        self.assertEqual(mean([1e308, 1e308]), 1e308)

    def test_gate_reports_mean_of_huge_values(self):
        data = b"v\n1e308\n1e308\n"
        spec = spec_for(data, "mean", variable="v", reported_value=1e308, tolerance=1e295)
        self.assertEqual(evaluate(spec, data)["verdict"], "MATCH")

    def _fit(self, offset):
        xs = [offset + i for i in range(1, 6)]
        ys = [float(i) for i in range(1, 6)]          # y = x - offset  → 기울기 1, 절편 -offset
        return ols([[y, x] for x, y in zip(xs, ys)], ["x"])

    def test_ols_is_accurate_for_large_predictor_offset(self):
        for offset in (1e6, 1e8, 1e10):
            fit = self._fit(offset)
            self.assertAlmostEqual(fit["terms"]["x"]["b"], 1.0, delta=1e-9, msg=offset)
            self.assertAlmostEqual(fit["terms"]["(Intercept)"]["b"], -offset, delta=1e-6 * max(1, offset / 1e6), msg=offset)

    def test_ols_matches_hand_computation(self):
        # 표준오차까지 독립 계산과 대조: y = 2.1, 3.9, 6.2, 7.8, 10.1 (x = 1..5)
        xs, ys = [1, 2, 3, 4, 5], [2.1, 3.9, 6.2, 7.8, 10.1]
        fit = ols([[y, x] for x, y in zip(xs, ys)], ["x"])
        mx, my = 3.0, sum(ys) / 5
        sxx = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        intercept = my - slope * mx
        rss = sum((y - intercept - slope * x) ** 2 for x, y in zip(xs, ys))
        s2 = rss / 3
        self.assertAlmostEqual(fit["terms"]["x"]["b"], slope, places=12)
        self.assertAlmostEqual(fit["terms"]["(Intercept)"]["b"], intercept, places=12)
        self.assertAlmostEqual(fit["terms"]["x"]["se"], math.sqrt(s2 / sxx), places=12)
        self.assertAlmostEqual(fit["terms"]["(Intercept)"]["se"], math.sqrt(s2 * (1 / 5 + mx ** 2 / sxx)), places=12)

    def test_badly_scaled_but_independent_predictors_are_not_called_singular(self):
        rows = [[3 * a + 1e-6 * b, a, b] for a, b in [(1, 1e6), (2, 3e6), (3, 2e6), (4, 5e6), (5, 4e6), (6, 8e6)]]
        fit = ols(rows, ["a", "b"])
        self.assertAlmostEqual(fit["terms"]["a"]["b"], 3.0, places=6)
        self.assertAlmostEqual(fit["terms"]["b"]["b"], 1e-6, places=12)

    def test_true_collinearity_and_constant_predictor_still_block(self):
        with self.assertRaises(GateError) as dup:
            ols([[1.0, a, a] for a in (1, 2, 3, 4, 5)], ["a", "a2"])
        self.assertEqual(dup.exception.code, "SINGULAR_DESIGN")
        with self.assertRaises(GateError) as const:
            ols([[float(i), 7.0] for i in range(5)], ["c"])
        self.assertEqual(const.exception.code, "SINGULAR_DESIGN")


class ApprovalRecordTest(unittest.TestCase):
    DATA = b"Species,v\nB,1\nA,2\nC,3\n"

    def spec(self):
        return spec_for(self.DATA, "row_alignment", data_id_column="Species", reference_ids_source="tree labels")

    def test_unbound_approval_is_blocked_without_granting_approval(self):
        # [1 이채우] 2026-10-01T01:21:52+09:00 — 세 지문 필수 정책에 맞춰 미결속 승인의 기대값을 차단으로 갱신한다.
        result = evaluate(self.spec(), self.DATA, reference_ids=["A", "B", "C"],
                          approvals={"reorder": {"approver": "연구자", "basis": "종 이름 기준"}})
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_UNBOUND"))
        self.assertNotIn("approvals", result)
        self.assertEqual(sorted(result["details"]["missing"]), ["data_sha256", "reference_sha256", "spec_sha256"])

    def test_partially_bound_approval_is_blocked(self):
        ref = ["A", "B", "C"]
        hashes = {"data_sha256": hashlib.sha256(self.DATA).hexdigest(),
                  "reference_sha256": reference_ids_sha256(ref), "spec_sha256": spec_sha256(self.spec())}
        for missing in hashes:
            approval = dict(approver="연구자", basis="종 이름 기준", **hashes)
            approval.pop(missing)
            result = evaluate(self.spec(), self.DATA, reference_ids=ref, approvals={"reorder": approval})
            self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_UNBOUND"))

    def test_bound_approval_is_recorded_with_its_own_hashes_and_expires_when_reference_changes(self):
        data_sha = hashlib.sha256(self.DATA).hexdigest()
        ref = ["A", "B", "C"]
        ref_sha = reference_ids_sha256(ref)
        approval = {"approver": "연구자", "basis": "종 이름 기준", "data_sha256": data_sha,
                    "reference_sha256": ref_sha, "spec_sha256": spec_sha256(self.spec())}
        ok = evaluate(self.spec(), self.DATA, reference_ids=ref, approvals={"reorder": approval})
        self.assertEqual((ok["verdict"], ok["approvals"][0]["bound_reference_sha256"], ok["approvals"][0]["unbound_fields"]),
                         ("MATCH", ref_sha, []))
        changed = evaluate(self.spec(), self.DATA, reference_ids=["C", "B", "A"], approvals={"reorder": approval})
        self.assertEqual((changed["verdict"], changed["reason_code"]), ("BLOCK", "APPROVAL_STALE"))

    def test_cli_binds_the_approval_it_creates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "d.csv").write_bytes(self.DATA)
            (tmp / "s.json").write_text(json.dumps(self.spec()), encoding="utf-8")
            (tmp / "r.txt").write_text("A\nB\nC\n", encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["check", "--spec", str(tmp / "s.json"), "--data", str(tmp / "d.csv"), "--reference-ids",
                             str(tmp / "r.txt"), "--approve-reorder", "--approver", "연구자", "--approval-basis", "종 이름"])
            record = json.loads(out.getvalue())["approvals"][0]
            self.assertEqual(code, 0)
            self.assertEqual(record["unbound_fields"], [])
            self.assertEqual(record["bound_data_sha256"], hashlib.sha256(self.DATA).hexdigest())


class CliInputTest(unittest.TestCase):
    def run_cli(self, spec_text, data=b"a\n1\n"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "d.csv").write_bytes(data)
            (tmp / "s.json").write_text(spec_text, encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["check", "--spec", str(tmp / "s.json"), "--data", str(tmp / "d.csv")])
            return code, json.loads(out.getvalue())

    def test_duplicate_keys_in_spec_are_refused(self):
        data = b"a\n1\n"
        spec = spec_for(data, "row_count", reported_value=1)
        text = json.dumps(spec)[:-1] + ', "tolerance": 100}'
        code, result = self.run_cli(text, data)
        self.assertEqual((code, result["reason_code"]), (3, "SPEC_JSON_INVALID"))

    def test_nan_literal_in_spec_is_refused(self):
        code, result = self.run_cli('{"spec_version": 2, "reported_value": NaN}')
        self.assertEqual((code, result["reason_code"]), (3, "SPEC_JSON_INVALID"))

    def test_malformed_method_returns_block_exit_code(self):
        data = b"a\n1\n"
        code, result = self.run_cli(json.dumps(spec_for(data, ["row_count"], reported_value=1)), data)
        self.assertEqual((code, result["reason_code"]), (3, "SPEC_NOT_READY"))


if __name__ == "__main__":
    unittest.main()
