"""저장소 위생 검사기(tools/repo_hygiene.py)가 실제로 사고가 났던 유형을 잡는지 합성 폴더로 확인한다.

# [작성: 0 이영 · Claude] 2026-10-01 00:30 KST — 실제 저장소가 아니라 임시 폴더를 검사한다. 위험한 문자열은 조립해서 이 파일 자체가 검사에 걸리지 않게 한다.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("repo_hygiene", Path(__file__).resolve().parents[1] / "tools" / "repo_hygiene.py")
HYGIENE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HYGIENE)

BACKSLASH = chr(92)


def scan(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, content in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return HYGIENE.check(root)


class RepoHygieneTest(unittest.TestCase):
    def test_clean_tree_passes(self):
        self.assertEqual(scan({"a.py": "print(1)\n", "docs/n.md": "안녕\n", "d.json": json.dumps({"a": 1})}), [])

    def test_only_mixed_line_endings_in_one_code_file_are_flagged(self):
        # 파일 전체가 CRLF인 것은 Windows 도구가 만든 정상 상태로 보고 통일을 강제하지 않는다(모두의 다음 병합이 충돌한다).
        findings = scan({"mixed.py": b"x = 1\r\ny = 2\n", "allcrlf.py": b"x = 1\r\ny = 2\r\n", "alllf.py": b"x = 1\n",
                         "docs/n.md": b"doc\r\nmore\n", "r.json": b"{}\r\n"})
        self.assertEqual([f.split(":")[0] for f in findings], ["mixed.py"])

    def test_secret_shaped_strings_are_flagged_except_obvious_test_fixtures(self):
        findings = scan({"a.py": 'KEY = "' + "sk-" + "a" * 30 + '"\n'})
        self.assertTrue(any("비밀값" in f for f in findings))
        self.assertEqual(scan({"t.py": 'FAKE = "' + "sk-" + "testFixtureValue" + "1" * 12 + '"\n'}), [])

    def test_local_absolute_paths_are_flagged_unless_marked(self):
        path = "C:" + BACKSLASH + "Users" + BACKSLASH + "someone" + BACKSLASH + "file.txt"
        self.assertTrue(any("로컬 절대경로" in f for f in scan({"a.md": path + "\n"})))
        self.assertEqual(scan({"a.py": "p = '" + path + "'  # hygiene: allow-local-path\n"}), [])

    def test_version_marker_replacement_inside_an_api_path_is_flagged(self):
        polluted = "https://api.example.org/" + "case" + "4" + "/search"
        self.assertTrue(any("case숫자" in f for f in scan({"a.py": "URL = '" + polluted + "'\n"})))
        self.assertEqual(scan({"a.md": "이 사례는 case4 시험이다\n"}), [])

    def test_emails_are_flagged_except_placeholders(self):
        self.assertTrue(any("이메일" in f for f in scan({"a.md": "문의: person" + "@" + "univ.ac.kr\n"})))
        self.assertEqual(scan({"a.md": "name" + "@" + "example.com\n"}), [])
        self.assertEqual(scan({"a.py": "fake = 'private-contact" + "@" + "example.test'\n"}), [])   # 예약 도메인(RFC 2606)

    def test_broken_and_duplicate_key_json_is_flagged(self):
        findings = scan({"a.json": '{"a": 1, "a": 2}', "b.json": "{not json"})
        self.assertEqual(sorted(f.split(":")[0] for f in findings), ["a.json", "b.json"])

    def test_config_drift_is_flagged(self):
        findings = scan({"requirements.txt": "a==1\n", "finals/requirements.txt": "a==2\n", "finals/.streamlit/config.toml": "[server]\n"})
        self.assertTrue(any("requirements" in f for f in findings))
        self.assertTrue(any("루트 .streamlit" in f for f in findings))

    def test_protected_data_and_sealed_inputs_are_not_touched(self):
        self.assertEqual(scan({"data/raw.csv": b"a\r\nb\r\n", "finals/evidence/inputs/x.txt": b"a@" + b"univ.ac.kr\r\n"}), [])


if __name__ == "__main__":
    unittest.main()
