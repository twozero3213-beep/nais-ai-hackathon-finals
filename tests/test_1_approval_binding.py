"""[1 이채우] 2026-10-01T01:03:10+09:00 — 합성 입력의 저장 승인 재사용 경계 회귀 시험."""

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from evidence_gate import evaluate
from evidence_gate.align import reference_ids_sha256
from evidence_gate.__main__ import main
from evidence_gate.spec import empty_spec, spec_sha256


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ApprovalBindingTest(unittest.TestCase):
    def setUp(self):
        self.data = b"Species,value\nB,1\nA,2\n"
        self.reference = ["A", "B"]
        self.spec = empty_spec("SYN-APPROVAL-1")
        self.spec.update(method="row_alignment", data_id_column="Species", reference_ids_source="synthetic labels",
                         filters=[], tolerance=0, data_fingerprint=sha(self.data),
                         source_location={"source_id": "SYN", "locator": "test fixture", "quote": "Synthetic rows"})
        self.approval = {"approver": "시험 검토자", "basis": "합성 식별자 순서 확인",
                         "data_sha256": sha(self.data), "spec_sha256": spec_sha256(self.spec),
                         "reference_sha256": reference_ids_sha256(self.reference)}

    def run_approval(self, approval, *, spec=None, data=None, reference=None, kind="reorder"):
        return evaluate(self.spec if spec is None else spec, self.data if data is None else data,
                        reference_ids=self.reference if reference is None else reference,
                        approvals={kind: approval})

    def test_bound_approval_matches_and_preserves_bindings_for_replay(self):
        result = self.run_approval(self.approval)
        self.assertEqual((result["verdict"], result["reason_code"]), ("MATCH", "ROWS_REORDERED_WITH_APPROVAL"))
        saved = result["approvals"][0]
        for key in ("data_sha256", "reference_sha256", "spec_sha256"):
            self.assertEqual(saved[key], self.approval[key])
            self.assertEqual(saved["bound_" + key], self.approval[key])
        self.assertEqual(self.run_approval(saved)["verdict"], "MATCH")

    def test_each_missing_null_or_empty_binding_blocks(self):
        for key in ("data_sha256", "reference_sha256", "spec_sha256"):
            for value in (None, "", "absent"):
                with self.subTest(field=key, value=value):
                    approval = dict(self.approval)
                    if value == "absent":
                        del approval[key]
                    else:
                        approval[key] = value
                    result = self.run_approval(approval)
                    self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_UNBOUND"))
                    self.assertIn(key, result["details"]["missing"])

    def test_data_change_with_updated_registration_expires_approval(self):
        changed = self.data.replace(b"B,1", b"B,9")
        spec = dict(self.spec, data_fingerprint=sha(changed))
        result = self.run_approval(self.approval, spec=spec, data=changed)
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_STALE"))
        self.assertEqual(result["details"]["field"], "data_sha256")

    def test_spec_change_expires_approval_with_same_data_and_reference(self):
        spec = copy.deepcopy(self.spec)
        spec["source_location"]["locator"] = "changed test position"
        result = self.run_approval(self.approval, spec=spec)
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_STALE"))
        self.assertEqual(result["details"]["field"], "spec_sha256")

    def test_reference_change_expires_approval_even_when_rows_are_aligned(self):
        result = self.run_approval(self.approval, reference=["B", "A"])
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_STALE"))
        self.assertEqual(result["details"]["field"], "reference_sha256")

    def test_embedded_newline_cannot_collide_with_identifier_boundary(self):
        before, after = ["A", "A\nA"], ["A\nA", "A"]
        self.assertEqual("\n".join(before), "\n".join(after))
        self.assertNotEqual(reference_ids_sha256(before), reference_ids_sha256(after))
        self.assertEqual(reference_ids_sha256(before), sha(b'["A","A\\nA"]'))
        data = b'Species,value\n"A\nA",1\nA,2\n'
        spec = dict(self.spec, data_fingerprint=sha(data))
        approval = dict(self.approval, data_sha256=sha(data), spec_sha256=spec_sha256(spec),
                        reference_sha256=reference_ids_sha256(before))
        initial = evaluate(spec, data, reference_ids=before, approvals={"reorder": approval})
        self.assertEqual(initial["reason_code"], "ROWS_REORDERED_WITH_APPROVAL")
        changed = evaluate(spec, data, reference_ids=after, approvals={"reorder": initial["approvals"][0]})
        self.assertEqual((changed["verdict"], changed["reason_code"]), ("BLOCK", "APPROVAL_STALE"))
        self.assertEqual(changed["details"]["field"], "reference_sha256")

    def test_no_approval_remains_pending(self):
        result = evaluate(self.spec, self.data, reference_ids=self.reference)
        self.assertEqual(result["reason_code"], "ROW_ORDER_REORDER_REQUIRED")
        self.assertNotIn("approvals", result)

    def test_normalization_requires_same_three_bindings(self):
        approval = {"approver": "시험 검토자", "basis": "표기 확인", "pairs": [{"from": "B", "to": "A"}]}
        result = self.run_approval(approval, kind="normalize")
        self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_UNBOUND"))

    def test_invalid_approval_blocks(self):
        for value in (None, "yes", {}, dict(self.approval, approver=" ")):
            with self.subTest(approval=value):
                result = self.run_approval(value)
                self.assertEqual((result["verdict"], result["reason_code"]), ("BLOCK", "APPROVAL_INVALID"))

    def test_cli_direct_consent_binds_all_three_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "spec.json").write_text(json.dumps(self.spec), encoding="utf-8")
            (root / "data.csv").write_bytes(self.data)
            (root / "ids.txt").write_bytes(b"A\nB\n")
            args = ["check", "--spec", str(root / "spec.json"), "--data", str(root / "data.csv"),
                    "--reference-ids", str(root / "ids.txt")]
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 3)
            self.assertNotIn("approvals", json.loads(output.getvalue()))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args + ["--approve-reorder", "--approver", "시험 검토자",
                                              "--approval-basis", "합성 순서 확인"]), 0)
            approval = json.loads(output.getvalue())["approvals"][0]
            for key in ("data_sha256", "reference_sha256", "spec_sha256"):
                self.assertEqual(approval[key], self.approval[key])

    def test_demo_requires_explicit_consent_and_approver(self):
        from evidence_gate import demo_a2
        tree = b"#NEXUS\nBEGIN TAXA;\nTAXLABELS A B;\nEND;\n"
        blobs = {"S5-primdfall.csv": self.data, "treeall.nex": tree}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "examples").mkdir()
            (root / "examples" / "a2_primate_alignment.spec.json").write_text(json.dumps(self.spec), encoding="utf-8")
            with patch.object(demo_a2, "ROOT", root):
                states = demo_a2.run(blobs, "시험 검토자")
                self.assertEqual(states[1]["reason_code"], "ROW_ORDER_REORDER_REQUIRED")
                self.assertNotIn("approvals", states[1])
                with self.assertRaises(ValueError):
                    demo_a2.run(blobs, approve_reorder=True)
                approved = demo_a2.run(blobs, "시험 검토자", approve_reorder=True)
                self.assertEqual(approved[1]["reason_code"], "ROWS_REORDERED_WITH_APPROVAL")


if __name__ == "__main__":
    unittest.main()
