"""P5 행 대응 진단·표기 변환 승인, NEXUS 입력기, P3 A2 시연 시험.

A2 저자 파일 시험은 EVIDENCE_GATE_A2_DIR에 두 파일이 있을 때만 돈다(자료는 저장소에 없음).
"""

import hashlib
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from evidence_gate import evaluate
from evidence_gate.__main__ import main
from evidence_gate.align import diagnose
from evidence_gate.nexus import NexusError, tip_labels
from evidence_gate.spec import empty_spec

APPROVE = {"approver": "연구자", "basis": "원자료 표기 확인"}
NEXUS = """#NEXUS
[주석]
BEGIN TREES;
translate
1 Homo_sapiens,
2 Pan_paniscus,
3 'Pan troglodytes';
tree t = ((1:1.0,2:0.5):0.2,3:0.7);
END;<br />trailing html
"""


def spec_for(data):
    spec = empty_spec("T-align")
    spec.update(method="row_alignment", data_fingerprint=hashlib.sha256(data).hexdigest(), tolerance=0, filters=[],
                data_id_column="Species", reference_ids_source="tree",
                source_location={"source_id": "SYN", "locator": "p. 1", "quote": "시험용 합성 문장"})
    return spec


class DiagnoseTest(unittest.TestCase):
    def test_missing(self):
        d = diagnose(["A", "B"], ["A", "B", "C"])
        self.assertEqual((d["status"], d["missing_in_data"]), ("MEMBERSHIP_MISMATCH", ["C"]))

    def test_duplicate(self):
        d = diagnose(["A", "B", "A"], ["A", "B"])
        self.assertEqual((d["status"], d["duplicates_data"]), ("MEMBERSHIP_MISMATCH", ["A"]))

    def test_order(self):
        d = diagnose(["B", "A"], ["A", "B"])
        self.assertEqual((d["status"], d["order_differs"], d["order_differences_count"]), ("ORDER_DIFFERS", True, 2))

    def test_notation_candidates_are_only_proposed(self):
        d = diagnose(["Homo sapiens", "pan_paniscus"], ["Homo_sapiens", "Pan_paniscus"])
        self.assertEqual(d["status"], "MEMBERSHIP_MISMATCH")
        self.assertEqual(d["normalization_candidates"], [
            {"from": "Homo sapiens", "to": "Homo_sapiens", "rule": "space_to_underscore"},
            {"from": "pan_paniscus", "to": "Pan_paniscus", "rule": "casefold"}])

    def test_ambiguous_notation_is_not_proposed(self):
        d = diagnose(["homo_sapiens"], ["Homo_sapiens", "HOMO_SAPIENS"])
        self.assertEqual(d["normalization_candidates"], [])


class NormalizeApprovalTest(unittest.TestCase):
    data = b"Species,v\nHomo sapiens,1\nPan_paniscus,2\n"
    reference = ["Homo_sapiens", "Pan_paniscus"]

    def test_blocked_until_approved(self):
        result = evaluate(spec_for(self.data), self.data, reference_ids=self.reference)
        self.assertEqual(result["reason_code"], "ROW_MEMBERSHIP_MISMATCH")
        self.assertIn("표기 차이 후보", result["next_action"])

    def test_approved_pair_applies(self):
        approvals = {"normalize": dict(APPROVE, pairs=[{"from": "Homo sapiens", "to": "Homo_sapiens"}])}
        result = evaluate(spec_for(self.data), self.data, reference_ids=self.reference, approvals=approvals)
        self.assertEqual((result["verdict"], result["reason_code"]), ("MATCH", "ROWS_ALIGNED"))
        self.assertEqual(result["approvals"][0]["pairs"][0]["rule"], "space_to_underscore")
        self.assertEqual(result["details"]["before_normalization"]["status"], "MEMBERSHIP_MISMATCH")

    def test_unoffered_pair_is_rejected(self):
        approvals = {"normalize": dict(APPROVE, pairs=[{"from": "Homo sapiens", "to": "Pan_paniscus"}])}
        result = evaluate(spec_for(self.data), self.data, reference_ids=self.reference, approvals=approvals)
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_NOT_APPLICABLE"))

    def test_approval_bound_to_other_inputs_is_stale(self):
        data = b"Species,v\nB,1\nA,2\n"
        approvals = {"reorder": dict(APPROVE, data_sha256="0" * 64)}
        result = evaluate(spec_for(data), data, reference_ids=["A", "B"], approvals=approvals)
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_STALE"))
        ok = evaluate(spec_for(data), data, reference_ids=["A", "B"],
                      approvals={"reorder": dict(APPROVE, data_sha256=hashlib.sha256(data).hexdigest())})
        self.assertEqual(ok["verdict"], "MATCH")
        self.assertEqual([r["data_row"] for r in ok["alignment_table"]], [2, 1])


class NexusTest(unittest.TestCase):
    def test_translate_order_quotes_and_trailing_text(self):
        self.assertEqual(tip_labels(NEXUS), ["Homo_sapiens", "Pan_paniscus", "Pan troglodytes"])

    def test_tree_tips_must_match_translate(self):
        with self.assertRaises(NexusError):
            tip_labels(NEXUS.replace("3:0.7", "4:0.7"))

    def test_taxlabels_fallback_and_bad_header(self):
        self.assertEqual(tip_labels("#NEXUS\nBEGIN TAXA;\nTAXLABELS A 'B c';\nEND;"), ["A", "B c"])
        with self.assertRaises(NexusError):
            tip_labels("BEGIN TREES;")

    def test_cli_with_nexus_and_approval(self):
        data = b"Species,v\nPan_paniscus,1\nHomo_sapiens,2\nPan troglodytes,3\n"
        with tempfile.TemporaryDirectory() as tmp:
            paths = {name: Path(tmp) / name for name in ("spec.json", "d.csv", "t.nex")}
            import json
            paths["spec.json"].write_text(json.dumps(spec_for(data)), encoding="utf-8")
            paths["d.csv"].write_bytes(data)
            paths["t.nex"].write_text(NEXUS, encoding="utf-8")
            base = ["check", "--spec", str(paths["spec.json"]), "--data", str(paths["d.csv"]),
                    "--reference-nexus", str(paths["t.nex"])]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(base), 3)
                self.assertEqual(main(base + ["--approve-reorder", "--approver", "연구자",
                                              "--approval-basis", "종 이름 기준"]), 0)
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
                main(base + ["--approve-reorder"])


A2_DIR = os.environ.get("EVIDENCE_GATE_A2_DIR")


@unittest.skipUnless(A2_DIR, "EVIDENCE_GATE_A2_DIR 미설정: A2 저자 파일 시험 건너뜀")
class A2AuthorFilesTest(unittest.TestCase):
    def test_five_states(self):
        from evidence_gate import demo_a2
        states = demo_a2.run(demo_a2.fetch(A2_DIR, download=False), "시험")
        self.assertEqual([(s["verdict"], s["reason_code"]) for s in states], [
            ("BLOCK", "ROW_ORDER_REORDER_REQUIRED"), ("MATCH", "ROWS_REORDERED_WITH_APPROVAL"),
            ("BLOCK", "ROW_MEMBERSHIP_MISMATCH"), ("BLOCK", "ROW_MEMBERSHIP_MISMATCH"), ("BLOCK", "STALE_DATA")])
        self.assertEqual((states[0]["details"]["data_count"], states[0]["details"]["order_differences_count"]), (26, 25))
        self.assertEqual(len(states[1]["alignment_table"]), 26)


if __name__ == "__main__":
    unittest.main()
