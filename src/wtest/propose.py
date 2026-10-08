"""propose_test 판정 (§6).

시그니처 추출 → [BEGIN IMMEDIATE] 후보 축소 → 유사도 → 정책 → INSERT 또는 거절 기록 → COMMIT.
문서 그림과 달리 후보 축소도 잠금 안에서 한다. 잠금 밖에서 후보를 고르면
그 사이 다른 worker가 넣은 시나리오를 놓쳐 중복 승인이 생길 수 있다.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import similarity
from .catalog import Catalog
from .config import Config
from .db import get_run, write_tx
from .signature import Signature, extract_signature


def propose_test(
    conn: sqlite3.Connection,
    cfg: Config,
    catalog: Catalog,
    *,
    run_id: str,
    worker_id: str,
    scenario: dict[str, Any],
    mode: str = "explore",
    vm_name: str | None = None,
) -> dict[str, Any]:
    sig = extract_signature(scenario, catalog, cfg.similarity.value_classes)
    agent_version = get_run(conn, run_id)["agent_version"]

    with write_tx(conn):
        scored = _score_candidates(conn, cfg, sig, agent_version)
        matches = [(s, row) for s, row in scored if s >= cfg.similarity.threshold]
        best_score, best = scored[0] if scored else (0.0, None)

        blocking = [(s, row) for s, row in matches if _retry_reason(conn, cfg, row) is None]
        if not blocking:
            retry_of = matches[0][1] if matches else None
            chk_id = _insert_test(conn, run_id, agent_version, worker_id, vm_name, mode,
                                  scenario, sig, retry_of)
            _log_proposal(conn, run_id, worker_id, sig, best, best_score, "approved", chk_id)
            result: dict[str, Any] = {
                "decision": "approved",
                "chk_id": chk_id,
                "score": round(best_score, 3),
                "best_match": best["chk_id"] if best else None,
            }
            if retry_of is not None:
                result["retry_of"] = retry_of["chk_id"]
                result["retry_reason"] = _retry_reason(conn, cfg, retry_of)
            return result

        if best is None:  # blocking이 있으면 후보도 있다. 깨졌다면 판정 로직 버그
            raise RuntimeError("거절 판정인데 비교 후보가 없음")
        _log_proposal(conn, run_id, worker_id, sig, best, best_score, "rejected", None)
        top = scored[: cfg.policy.similar_top_k]
        return {
            "decision": "rejected",
            "score": round(best_score, 3),
            "threshold": cfg.similarity.threshold,
            "best_match": best["chk_id"],
            "similar": [
                {
                    "chk_id": row["chk_id"],
                    "title": row["title"],
                    "status": row["status"],
                    "score": round(s, 3),
                    "diff": similarity.diff(sig, Signature.from_json(json.loads(row["signature_json"]))),
                }
                for s, row in top
            ],
            "uncovered_hints": uncovered_hints(conn, catalog, agent_version, cfg.policy.hint_limit),
        }


def _score_candidates(conn: sqlite3.Connection, cfg: Config, sig: Signature,
                      agent_version: str) -> list[tuple[float, sqlite3.Row]]:
    actions = sorted(sig.actions)
    marks = ",".join("?" * len(actions))
    rows = conn.execute(
        f"""SELECT * FROM test
            WHERE agent_version = ? AND superseded_by IS NULL
              AND chk_id IN (SELECT chk_id FROM test_action WHERE action IN ({marks}))""",
        (agent_version, *actions),
    ).fetchall()
    scored = [
        (similarity.score(sig, Signature.from_json(json.loads(r["signature_json"])), cfg.similarity), r)
        for r in rows
    ]
    scored.sort(key=lambda x: (-x[0], x[1]["chk_id"]))
    return scored


def _retry_reason(conn: sqlite3.Connection, cfg: Config, row: sqlite3.Row) -> str | None:
    """유사 시나리오가 있어도 다시 승인할 수 있는 경우 그 이유를, 아니면 None."""
    if row["retry_count"] >= cfg.policy.max_retries:
        return None
    if row["status"] == "INCONCLUSIVE":
        return "inconclusive_retry"
    if row["status"] == "FAIL":
        parent = None
        if row["retry_of"]:
            parent = conn.execute("SELECT status FROM test WHERE chk_id = ?", (row["retry_of"],)).fetchone()
        if parent is None or parent["status"] != "FAIL":  # FAIL → FAIL이면 재현 확인 완료
            return "fail_reproduction"
    return None


def _next_chk_id(conn: sqlite3.Connection) -> str:
    n = conn.execute(
        "SELECT COALESCE(MAX(CAST(substr(chk_id, 5) AS INTEGER)), 0) + 1 FROM test"
    ).fetchone()[0]
    return f"CHK-{n:03d}"


def _insert_test(conn: sqlite3.Connection, run_id: str, agent_version: str, worker_id: str,
                 vm_name: str | None, mode: str, scenario: dict[str, Any], sig: Signature,
                 retry_of: sqlite3.Row | None) -> str:
    chk_id = _next_chk_id(conn)
    conn.execute(
        """INSERT INTO test (chk_id, run_id, agent_version, worker_id, vm_name, mode, title, area,
                             scenario_json, signature_json, signature_hash, retry_count, retry_of)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (chk_id, run_id, agent_version, worker_id, vm_name, mode,
         scenario.get("title"), scenario.get("area"),
         json.dumps(scenario, ensure_ascii=False), json.dumps(sig.to_json(), ensure_ascii=False),
         sig.hash,
         retry_of["retry_count"] + 1 if retry_of else 0,
         retry_of["chk_id"] if retry_of else None),
    )
    conn.executemany("INSERT INTO test_action (chk_id, action) VALUES (?, ?)",
                     [(chk_id, a) for a in sorted(sig.actions)])
    if retry_of is not None:
        conn.execute("UPDATE test SET superseded_by = ? WHERE chk_id = ?", (chk_id, retry_of["chk_id"]))
    return chk_id


def _log_proposal(conn: sqlite3.Connection, run_id: str, worker_id: str, sig: Signature,
                  best: sqlite3.Row | None, score: float, decision: str, approved_chk: str | None) -> None:
    conn.execute(
        """INSERT INTO proposal (run_id, worker_id, signature_json, best_match_chk, score, decision, approved_chk)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, worker_id, json.dumps(sig.to_json(), ensure_ascii=False),
         best["chk_id"] if best else None, score if best else None, decision, approved_chk),
    )


def uncovered_hints(conn: sqlite3.Connection, catalog: Catalog, agent_version: str,
                    limit: int) -> list[dict[str, Any]]:
    """커버리지 빈 칸: (1) 한 번도 안 쓴 액션 (2) 다른 영역에선 썼지만 이 영역에선 안 쓴 액션."""
    covered = conn.execute(
        "SELECT area, action, tests FROM coverage WHERE agent_version = ?", (agent_version,)
    ).fetchall()
    used = {r["action"] for r in covered}
    hints: list[dict[str, Any]] = [
        {"kind": "untested_action", "action": a,
         "hint": f"'{a}' 액션을 쓰는 시나리오가 아직 없음"}
        for a in catalog.names("action") if a not in used
    ]
    areas = sorted({r["area"] for r in covered if r["area"] != "(none)"})
    pairs = {(r["area"], r["action"]) for r in covered}
    for area in areas:
        for action in sorted(used):
            if (area, action) not in pairs:
                hints.append({"kind": "untested_in_area", "area": area, "action": action,
                              "hint": f"영역 '{area}'에서 '{action}'를 쓴 시나리오가 없음"})
    return hints[:limit]
