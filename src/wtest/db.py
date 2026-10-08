"""coverage.db 연결.

여러 MCP 프로세스가 같은 파일을 쓰므로 WAL + busy_timeout을 켠다.
isolation_level=None(autocommit)으로 열어 트랜잭션은 호출자가 BEGIN IMMEDIATE로 직접 연다.
파이썬 sqlite3의 암묵적 트랜잭션에 맡기면 '조회 → INSERT'가 원자적이지 않아
두 worker가 같은 시나리오를 동시에 선점할 수 있다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from .catalog import Catalog


def connect(path: str | Path, busy_timeout_ms: int = 30000) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # MCP SDK는 동기 도구를 워커 스레드에서 실행한다. 세션 쪽에서 락으로 직렬화하므로 스레드 검사는 끈다
    conn = sqlite3.connect(path, isolation_level=None, timeout=busy_timeout_ms / 1000, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Generator[sqlite3.Connection]:
    """BEGIN IMMEDIATE: 시작 시점에 쓰기 잠금을 잡아 조회와 쓰기를 한 단위로 만든다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(conn: sqlite3.Connection, catalog: Catalog) -> None:
    schema = resources.files("wtest").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    with write_tx(conn):
        for spec in catalog.actions.values():
            conn.execute(
                """INSERT INTO action (name, kind, category, params_schema, description)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, category=excluded.category,
                       params_schema=excluded.params_schema, description=excluded.description""",
                (spec.name, spec.kind, spec.category,
                 json.dumps(spec.params_schema(), ensure_ascii=False), spec.description),
            )


def create_run(conn: sqlite3.Connection, run_id: str, agent_version: str,
               profile_version: str | None = None) -> None:
    conn.execute(
        "INSERT INTO run (run_id, agent_version, profile_version) VALUES (?, ?, ?)",
        (run_id, agent_version, profile_version),
    )


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM run WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise LookupError(f"run '{run_id}' 없음. 먼저 'wtest new-run'으로 생성해야 함")
    return row
