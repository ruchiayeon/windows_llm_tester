"""MCP 세션 하나(= Claude 세션 하나)의 상태와 도구 동작. 전송 계층(MCP)과 분리해 테스트에서 직접 쓴다.

세션은 실행 환경(env)이 고정한 worker · VM · run에 묶인다.
CHK는 고정 모드면 WTEST_CHK로 시작부터 정해지고, 탐색 모드면 propose_test 승인 시점에 정해진다
(§7의 'WTEST_CHK에 고정'을 탐색 모드까지 넓힌 것). 승인 전에는 record_step을 쓸 수 없다.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import propose
from .catalog import Catalog
from .config import Config
from .db import get_run, write_tx
from .vm import VMGuard

VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE")
SEVERITIES = ("info", "low", "medium", "high", "critical")


class SessionError(ValueError):
    """도구 호출 규칙 위반. Claude에게 그대로 돌려줄 메시지."""


class Session:
    def __init__(self, cfg: Config, catalog: Catalog, conn: sqlite3.Connection, vm: VMGuard, *,
                 run_id: str, worker_id: str, chk_id: str | None = None):
        self.cfg = cfg
        self.catalog = catalog
        self.conn = conn
        self.vm = vm
        self.run_id = run_id
        self.worker_id = worker_id
        self.agent_version = get_run(conn, run_id)["agent_version"]
        self.mode = "fixed" if chk_id else "explore"
        self.chk_id = chk_id
        self.rejections = 0
        self.finished = False
        if chk_id:
            row = self._test()
            if row["status"] not in ("claimed", "running"):
                raise SessionError(f"{chk_id}는 이미 {row['status']} 상태라 실행할 수 없음")
        # new_findings 커서: 세션 시작 이후 다른 worker가 올린 발견만 편승시킨다
        self._finding_cursor = conn.execute("SELECT COALESCE(MAX(finding_id), 0) FROM finding").fetchone()[0]

    # ---- 편승 ------------------------------------------------------------------
    def new_findings(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT finding_id, chk_id, worker_id, severity, summary FROM finding
               WHERE finding_id > ? AND worker_id != ? ORDER BY finding_id""",
            (self._finding_cursor, self.worker_id),
        ).fetchall()
        mx = self.conn.execute("SELECT COALESCE(MAX(finding_id), 0) FROM finding").fetchone()[0]
        self._finding_cursor = max(self._finding_cursor, mx)
        return [dict(r) for r in rows]

    # ---- 지식 조회 (RAG) ---------------------------------------------------------
    def list_actions(self, kind: str | None = None) -> list[dict[str, Any]]:
        return [
            {"name": s.name, "kind": s.kind, "category": s.category, "description": s.description}
            for s in self.catalog.actions.values() if kind is None or s.kind == kind
        ]

    def describe_action(self, name: str) -> dict[str, Any]:
        s = self.catalog.get(name)
        return {"name": s.name, "kind": s.kind, "category": s.category, "description": s.description,
                "params": s.params_schema(), "signature_params": list(s.signature_params)}

    def get_profile(self, section: str | None = None) -> dict[str, Any]:
        if section is None:
            rows = self.conn.execute("SELECT section, profile_version FROM profile_section ORDER BY section")
            return {"sections": [dict(r) for r in rows], "note": "section 이름을 넘기면 내용을 반환함"}
        row = self.conn.execute("SELECT * FROM profile_section WHERE section = ?", (section,)).fetchone()
        if row is None:
            raise SessionError(f"프로파일 섹션 '{section}' 없음")
        return dict(row)

    def search_docs(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        # M5 전까지는 벡터 대신 부분 문자열 검색
        rows = self.conn.execute(
            "SELECT chunk_id, source, content FROM doc_chunk WHERE content LIKE ? LIMIT ?",
            (f"%{query}%", limit),
        )
        return [dict(r) for r in rows]

    # ---- 협업 ------------------------------------------------------------------
    def propose_test(self, scenario: dict[str, Any]) -> dict[str, Any]:
        if self.chk_id:
            raise SessionError(f"이미 {self.chk_id}가 배정됨. 실행 후 finish로 끝내야 함")
        if self.rejections >= self.cfg.policy.saturate_after_rejections:
            raise SessionError("거절 한도 도달(탐색 포화). finish(verdict='SATURATED')로 종료해야 함")
        result = propose.propose_test(self.conn, self.cfg, self.catalog, run_id=self.run_id,
                                      worker_id=self.worker_id, scenario=scenario,
                                      mode=self.mode, vm_name=self.vm.backend.name)
        if result["decision"] == "approved":
            self.chk_id = result["chk_id"]
            return result
        self.rejections += 1
        result["attempt"] = self.rejections
        result["guidance"] = self._rejection_guidance()
        return result

    def _rejection_guidance(self) -> str:
        p = self.cfg.policy
        if self.rejections >= p.saturate_after_rejections:
            return "거절 한도 도달. 더 제안하지 말고 finish(verdict='SATURATED', summary=시도한 방향)로 종료"
        if self.rejections >= p.hint_after_rejections:
            return "uncovered_hints 중 하나를 골라 그 빈 칸을 채우는 시나리오로 재제안"
        return "diff를 보고 단계 구성·순서·사전조건·판정기준을 구조적으로 바꿔 재제안 (값만 바꾸면 같은 테스트로 본다)"

    def list_coverage(self, area: str | None = None) -> dict[str, Any]:
        sql = "SELECT * FROM coverage WHERE agent_version = ?"
        args: list[Any] = [self.agent_version]
        if area:
            sql += " AND area = ?"
            args.append(area)
        rows = [dict(r) for r in self.conn.execute(sql + " ORDER BY area, action", args)]
        return {"agent_version": self.agent_version, "coverage": rows,
                "uncovered_hints": propose.uncovered_hints(self.conn, self.catalog, self.agent_version,
                                                           self.cfg.policy.hint_limit)}

    def post_finding(self, severity: str, summary: str, evidence_ref: str | None = None) -> dict[str, Any]:
        if severity not in SEVERITIES:
            raise SessionError(f"severity는 {list(SEVERITIES)} 중 하나")
        cur = self.conn.execute(
            "INSERT INTO finding (chk_id, worker_id, severity, summary, evidence_ref) VALUES (?, ?, ?, ?, ?)",
            (self.chk_id, self.worker_id, severity, summary, evidence_ref),
        )
        return {"finding_id": cur.lastrowid}

    def read_findings(self, since_id: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM finding WHERE finding_id > ? ORDER BY finding_id DESC LIMIT ?", (since_id, limit)
        )
        return [dict(r) for r in rows]

    def search_findings(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM finding WHERE summary LIKE ? ORDER BY finding_id DESC LIMIT ?", (f"%{query}%", limit)
        )
        return [dict(r) for r in rows]

    def search_logs(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM log_signature WHERE normalized_message LIKE ? LIMIT ?", (f"%{query}%", limit)
        )
        return [dict(r) for r in rows]

    # ---- 기록 ------------------------------------------------------------------
    def _test(self) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM test WHERE chk_id = ?", (self.chk_id,)).fetchone()
        if row is None:
            raise SessionError(f"{self.chk_id} 없음")
        return row

    def _require_chk(self) -> str:
        if not self.chk_id:
            raise SessionError("배정된 CHK가 없음. propose_test 승인 후에 기록할 수 있음")
        if self.finished:
            raise SessionError(f"{self.chk_id}는 이미 finish됨")
        return self.chk_id

    def record_step(self, action: str, params: dict[str, Any] | None, observed: str,
                    result: str) -> dict[str, Any]:
        chk = self._require_chk()
        if result not in ("ok", "fail", "skip"):
            raise SessionError("result는 ok | fail | skip 중 하나")
        self.catalog.get(action)
        with write_tx(self.conn):
            seq = self.conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM step WHERE chk_id = ?",
                                    (chk,)).fetchone()[0]
            self.conn.execute(
                "INSERT INTO step (chk_id, seq, action, params_json, observed, result) VALUES (?, ?, ?, ?, ?, ?)",
                (chk, seq, action, json.dumps(params or {}, ensure_ascii=False), observed, result),
            )
            self.conn.execute("UPDATE test SET status = 'running' WHERE chk_id = ? AND status = 'claimed'", (chk,))
        return {"chk_id": chk, "seq": seq}

    def finish(self, verdict: str, summary: str) -> dict[str, Any]:
        if verdict == "SATURATED":
            if self.chk_id:
                raise SessionError("CHK가 배정된 세션은 PASS | FAIL | INCONCLUSIVE로 끝내야 함")
            self._event("saturated", summary)
            self.finished = True
            return {"ok": True, "verdict": "SATURATED"}
        if verdict not in VERDICTS:
            raise SessionError(f"verdict는 {list(VERDICTS)} 또는 SATURATED")
        chk = self._require_chk()
        with write_tx(self.conn):
            cur = self.conn.execute(
                """UPDATE test SET status = ?, summary = ?, finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                   WHERE chk_id = ? AND status IN ('claimed', 'running')""",
                (verdict, summary, chk),
            )
            if cur.rowcount != 1:
                raise SessionError(f"{chk}는 이미 확정된 상태")
            self._event("finished", json.dumps({"chk_id": chk, "verdict": verdict}))
        self.finished = True
        return {"ok": True, "chk_id": chk, "verdict": verdict}

    def _event(self, kind: str, detail: str | None) -> None:
        self.conn.execute("INSERT INTO worker_event (run_id, worker_id, kind, detail) VALUES (?, ?, ?, ?)",
                          (self.run_id, self.worker_id, kind, detail))
