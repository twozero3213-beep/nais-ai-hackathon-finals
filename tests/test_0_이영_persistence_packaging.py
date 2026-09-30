"""정규 저장 서비스의 공개 배포 DDL 누락 회귀. 사용자 DB는 사용하지 않는다.

# [작성: 0 이영 · Codex] 2026-10-01 03:08 KST — 코드만 편입되고 기본 SQL은 빠져 두 재사용 서비스가 빈 DB 생성에도 실패했다. 동일 제품의 검토된 DDL을 다시 연결한다.
"""
from pathlib import Path
import sqlite3

import pytest

from core.canonical_service import CanonicalService
from core.relational_store import RelationalStore


@pytest.mark.parametrize("service", [CanonicalService, RelationalStore])
def test_default_persistence_schema_is_packaged_and_enforces_integrity(tmp_path, service):
    store = service(tmp_path / "synthetic.sqlite")
    try:
        assert store.con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert store.con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {row[0] for row in store.con.execute("SELECT role_code FROM roles")} == {
            "VIEWER", "ANALYST", "REVIEWER", "APPROVER", "ADMIN"}
        triggers = {row[0] for row in store.con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {"approval_separation", "execution_invalidates_approval", "audit_chain_prev",
                "audit_events_no_update", "audit_events_no_delete"} <= triggers
        with pytest.raises(sqlite3.IntegrityError):
            store.con.execute("INSERT INTO user_roles(user_id,role_code) VALUES('synthetic-missing','VIEWER')")
    finally:
        store.con.close()


@pytest.mark.parametrize("service", [CanonicalService, RelationalStore])
@pytest.mark.parametrize("missing", [True, False])
def test_failed_initialization_closes_connection_and_releases_database_file(tmp_path, monkeypatch, service, missing):
    # [수정: 0 이영 · Codex] 2026-10-01 03:12 KST — 생성 실패의 실제 열린 연결과 Windows 파일 잠금 회귀를 확인한다. Linux의 열린 파일 unlink 허용에도 의존하지 않는다.
    schema = tmp_path / "schema.sql"
    if not missing:
        schema.write_text("INVALID SQL;", encoding="utf-8")
    db_path = tmp_path / "synthetic.sqlite"
    connections = []
    connect = sqlite3.connect

    def observed_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    expected_error = FileNotFoundError if missing else sqlite3.OperationalError
    with pytest.raises(expected_error):
        service(db_path, schema_path=schema)
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
    db_path.unlink()
    assert not db_path.exists()
