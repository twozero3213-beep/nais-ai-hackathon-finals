import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("metadata_guard", Path(__file__).with_name("check_finals_metadata.py"))
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


def token(number):
    return "v" + str(number)


class ProductMetadataGuardTests(unittest.TestCase):
    def test_product_labels_and_identifiers(self):
        for value in (token(4), token(105).upper(), "test_" + token(36) + "_ui.py", "APP_VERSION=" + token(67) + ".0.0"):
            self.assertTrue(GUARD.has_product_version(value), value)
        for value in (token(0), token(1), token(2), token(3), "case105", "folder threshold", "CV44"):
            self.assertFalse(GUARD.has_product_version(value), value)

    def test_science_urls_doi_and_action_refs_are_protected(self):
        for value in ("V600E", "actions/setup-python@" + token(4), "https://example.org/" + token(44), "10.1234/" + token(44)):
            self.assertFalse(GUARD.has_product_version(value), value)
        self.assertTrue(GUARD.has_product_version("https://example.org/path label " + token(44)))

    def test_verified_external_api_label_does_not_mask_product_labels(self):
        self.assertFalse(GUARD.has_product_version("미국 Data.gov " + token(4)))
        self.assertFalse(GUARD.has_product_version("Data.gov 공식 API " + token(4)))
        self.assertFalse(GUARD.has_product_version("/technology/datagov/" + token(4) + "/search?q=example"))
        self.assertTrue(GUARD.has_product_version("/technology/datagov/" + token(4) + "/search 제품 " + token(44)))
        self.assertTrue(GUARD.has_product_version("Data.gov " + token(4) + " 제품 " + token(44)))
        self.assertTrue(GUARD.has_product_version("Data.gov " + token(105)))

    def test_source_corpus_protected_intake_and_code_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("data/corpus.json", "finals/evidence/inputs/source.txt", "finals/evidence/packets/case.json", "docs/intake/import.json", "core/engine.py"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(token(105), encoding="utf-8")
            failures = GUARD.product_version_failures(root)
            self.assertEqual(len(failures), 2, failures)
            self.assertFalse(any("data" in item for item in failures), failures)

    def test_filenames_detected_binary_and_ignored_paths_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ("test_" + token(67) + ".py")).write_text("pass", encoding="utf-8")
            (root / "binary.dat").write_bytes(b"\xff" + token(44).encode())
            ignored = root / ".git"
            ignored.mkdir()
            (ignored / "history.txt").write_text(token(44), encoding="utf-8")
            failures = GUARD.product_version_failures(root)
            self.assertEqual(len(failures), 1, failures)
            self.assertIn("파일명", failures[0])

    def test_team_and_document_contracts_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            now = datetime.fromisoformat("2026-09-30T20:00:00+09:00")
            team = {"contributors": [{"name": name, "version": number} for name, number in GUARD.EXPECTED.items()],
                    "this_chat": {"name": "이영", "version": 0, "commit_prefix": "[0 이영]"},
                    "finals_started_at_kst": "2026-09-30T17:55:37+09:00",
                    "upload_not_before_kst": "2026-09-30T17:00:00+09:00"}
            (root / "TEAM_VERSIONS.json").write_text(json.dumps(team, ensure_ascii=False), encoding="utf-8")
            (root / "VERSION").write_text("0", encoding="utf-8")
            (root / "README.md").write_text("# 본선", encoding="utf-8")
            (root / "AGENTS.md").write_text("# 본선", encoding="utf-8")
            with patch.object(GUARD, "ROOT", root), patch.object(GUARD, "datetime") as clock, patch.dict("os.environ", {"GITHUB_ACTIONS": "false"}):
                clock.fromisoformat = datetime.fromisoformat
                clock.now.return_value = now
                self.assertEqual(GUARD.check()["status"], "PASS")
                (root / "VERSION").write_text("0.1.0", encoding="utf-8")
                self.assertEqual(GUARD.check()["status"], "FAIL")
                (root / "VERSION").write_text("0", encoding="utf-8")
                (root / "docs/receipt.json").write_text(json.dumps({"recorded_at_kst": "2026-09-30T16:00:00+09:00"}), encoding="utf-8")
                self.assertEqual(GUARD.check()["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()


def test_current_label_and_numeric_release_are_detected():
    assert GUARD.has_product_version("".join(chr(c) for c in (0xC900, 0xBE44, 0xBCF8)))
    assert GUARD.has_product_version(f"{105}.0.0")
    assert not GUARD.has_product_version("담당 0 / 1 / 2 / 3")
