# [수정: 3 조지현] 2026-10-01T01:21:00+09:00 — 정상 재정렬 승인의 자료·기준 지문을 명시해 강화된 계약 확인.
"""P1 최소 실행 경로 시험. 펭귄 행 수는 공개 원자료, 나머지 보고값은 시험용 합성값이다."""

import copy
import hashlib
import io
import json
import math
import statistics
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from evidence_gate import evaluate
from evidence_gate.align import reference_ids_sha256
from evidence_gate.__main__ import main
from evidence_gate.record import append_record, read_records, reusable_result
from evidence_gate.spec import empty_spec, spec_sha256

ROOT = Path(__file__).resolve().parents[1]
PENGUINS = (ROOT / "evidence_gate" / "fixtures" / "penguins_raw.csv").read_bytes()
EXAMPLE = ROOT / "evidence_gate" / "examples" / "penguins_raw_rows.spec.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def spec_for(data, method, **fields):
    spec = empty_spec(f"T-{method}")
    spec.update(method=method, data_fingerprint=sha(data), tolerance=1e-9, filters=[],
                source_location={"source_id": "SYN", "locator": "p. 1", "quote": "시험용 합성 문장"})
    spec.update(fields)
    return spec


class PenguinRowCountTest(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_fixture_is_pinned_bytes(self):
        self.assertEqual(sha(PENGUINS), "144f623143c9360fd77322a4f86acb06dc198814dbd2669724c63e6457b907bd")

    def test_c01_344_rows_match(self):
        result = evaluate(self.spec, PENGUINS)
        self.assertEqual((result["verdict"], result["computed"]), ("MATCH", 344))

    def test_changed_reported_value_mismatch(self):
        result = evaluate(dict(self.spec, reported_value=345), PENGUINS)
        self.assertEqual((result["verdict"], result["computed"]), ("MISMATCH", 344))

    def test_c05_removed_source_location_blocks(self):
        result = evaluate(dict(self.spec, source_location=None), PENGUINS)
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "SPEC_NOT_READY"))
        self.assertIn("source_location", result["validation"]["missing"])

    def test_c07_c08_changed_bytes_block_and_prior_result_not_reused(self):
        first_row_removed = PENGUINS.replace(PENGUINS.split(b"\n")[1] + b"\n", b"", 1)
        crlf = PENGUINS.replace(b"\n", b"\r\n")
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "runs.jsonl"
            ok = append_record(log, evaluate(self.spec, PENGUINS))
            for changed in (first_row_removed, crlf):
                with self.subTest(size=len(changed)):
                    result = evaluate(self.spec, changed)
                    self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "STALE_DATA"))
                    self.assertIsNone(reusable_result(log, result["spec_sha256"], result["data_sha256"]))
            self.assertEqual(reusable_result(log, ok["spec_sha256"], sha(PENGUINS))["run_id"], ok["run_id"])

    def test_mean_with_na_tokens_matches_independent_mean(self):
        rows = PENGUINS.decode().splitlines()
        header = rows[0].split(",")
        # 이 열 앞에는 따옴표 안 쉼표가 있는 Stage 열이 있어 csv 모듈로 독립 계산한다.
        import csv
        values = [r["Body Mass (g)"] for r in csv.DictReader(io.StringIO(PENGUINS.decode()))]
        expected = statistics.fmean(float(v) for v in values if v != "NA")
        self.assertIn("Body Mass (g)", header)
        spec = spec_for(PENGUINS, "mean", variable="Body Mass (g)", missing_policy="complete_case",
                        missing_tokens=["NA"], reported_value=expected)
        result = evaluate(spec, PENGUINS)
        self.assertEqual(result["verdict"], "MATCH")
        self.assertEqual(result["details"]["rows_dropped_missing"], values.count("NA"))
        blocked = evaluate(dict(spec, missing_policy="error"), PENGUINS)
        self.assertEqual((blocked["verdict"], blocked["reason_code"]), ("BLOCK", "MISSING_VALUES"))
        self.assertEqual(blocked["details"]["count"], values.count("NA"))


class SyntheticMethodsTest(unittest.TestCase):
    def test_bad_values_stop_with_row_numbers(self):
        data = "g,x\na,10\na,20\na,\"1,000\"\na,N/A\na,30\n".encode()
        spec = spec_for(data, "mean", variable="x", missing_policy="complete_case", missing_tokens=[""], reported_value=20)
        result = evaluate(spec, data)
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "BAD_VALUE"))
        self.assertEqual([r["data_row"] for r in result["details"]["rows"]], [3, 4])

    def test_filter_selects_rows(self):
        data = b"g,x\na,1\nb,5\na,3\n"
        spec = spec_for(data, "mean", variable="x", missing_policy="error", missing_tokens=[""], reported_value=2,
                        filters=[{"column": "g", "operator": "eq", "value": "a"}])
        self.assertEqual(evaluate(spec, data)["verdict"], "MATCH")

    def ols_data(self):
        xs, ys = [1, 2, 3, 4, 5], [2.1, 3.9, 6.2, 7.8, 10.1]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        intercept = my - slope * mx
        rss = sum((y - intercept - slope * x) ** 2 for x, y in zip(xs, ys))
        se = math.sqrt(rss / (n - 2) / sxx)
        data = ("y,x\n" + "".join(f"{y},{x}\n" for x, y in zip(xs, ys))).encode()
        return data, intercept, slope, se

    def test_ols_match_needs_review_mismatch(self):
        data, intercept, slope, se = self.ols_data()
        spec = spec_for(data, "ols_regression", outcome="y", predictors=["x"], missing_policy="error",
                        missing_tokens=[""], reported_df=3,
                        reported={"(Intercept)": {"b": intercept, "se": None, "t": None},
                                  "x": {"b": slope, "se": se, "t": slope / se}})
        self.assertEqual(evaluate(spec, data)["verdict"], "MATCH")
        review = evaluate(dict(spec, reported_df=4), data)
        self.assertEqual((review["verdict"], review["df"]["computed"]), ("NEEDS_REVIEW", 3))
        wrong = copy.deepcopy(spec)
        wrong["reported"]["x"]["b"] = slope + 0.5
        self.assertEqual(evaluate(wrong, data)["reason_code"], "COEFFICIENT_MISMATCH")

    def test_row_alignment_order_membership_and_approval(self):
        data = b"Species,v\nB,1\nA,2\nC,3\n"
        spec = spec_for(data, "row_alignment", data_id_column="Species", reference_ids_source="tree labels")
        self.assertEqual(evaluate(spec, data, reference_ids=["B", "A", "C"])["verdict"], "MATCH")
        blocked = evaluate(spec, data, reference_ids=["A", "B", "C"])
        self.assertEqual(blocked["reason_code"], "ROW_ORDER_REORDER_REQUIRED")
        self.assertEqual(blocked["details"]["order_differences"][0], {"position": 1, "data_id": "B", "reference_id": "A"})
        half = evaluate(spec, data, reference_ids=["A", "B", "C"], approvals={"reorder": {"approver": "연구자"}})
        self.assertEqual(half["verdict"], "BLOCK")
        approved = evaluate(spec, data, reference_ids=["A", "B", "C"],
                            approvals={"reorder": {"approver": "연구자", "basis": "종 이름 기준",
                                       "data_sha256": sha(data), "spec_sha256": spec_sha256(spec),
                                       "reference_sha256": reference_ids_sha256(["A", "B", "C"])}})
        self.assertEqual((approved["verdict"], approved["reorder_indices"]), ("MATCH", [1, 0, 2]))
        membership = evaluate(spec, data, reference_ids=["A", "B", "D"])
        self.assertEqual(membership["reason_code"], "ROW_MEMBERSHIP_MISMATCH")
        self.assertEqual((membership["details"]["missing_in_data"], membership["details"]["missing_in_reference"]), (["D"], ["C"]))


class RecordAndCliTest(unittest.TestCase):
    def test_append_only_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "runs.jsonl"
            data = Path(tmp) / "penguins.csv"
            data.write_bytes(PENGUINS)
            with redirect_stdout(io.StringIO()):
                code1 = main(["check", "--spec", str(EXAMPLE), "--data", str(data), "--record", str(log)])
            first_line = log.read_text(encoding="utf-8").splitlines()[0]
            with redirect_stdout(io.StringIO()) as out:
                code2 = main(["check", "--spec", str(EXAMPLE), "--data", str(data), "--record", str(log)])
            self.assertEqual((code1, code2), (0, 0))
            records = read_records(log)
            self.assertEqual(len(records), 2)
            self.assertEqual(log.read_text(encoding="utf-8").splitlines()[0], first_line)
            self.assertEqual(json.loads(out.getvalue())["prior_run_same_inputs"], records[0]["run_id"])
            self.assertTrue(records[1]["executed_at_kst"].endswith("+09:00"))


if __name__ == "__main__":
    unittest.main()
