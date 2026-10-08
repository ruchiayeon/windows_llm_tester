import copy

from wtest.propose import propose_test

from conftest import RUN
from helpers import RESTART, scenario

NETWORK = scenario(
    ("block_network", {"port": 443}),
    ("wait", {"seconds": 120}),
    ("unblock_network", {}),
    ("service_status", {"svc": "AgentSvc"}),
    pre=["AgentSvc running"],
    crit=["agent reconnects after unblock"],
    title="network outage recovery",
    area="network",
)


def propose(conn, cfg, catalog, sc, worker="w1"):
    return propose_test(conn, cfg, catalog, run_id=RUN, worker_id=worker, scenario=sc)


def set_status(conn, chk, status):
    conn.execute("UPDATE test SET status = ? WHERE chk_id = ?", (status, chk))


def test_first_is_approved_and_duplicate_rejected(conn, cfg, catalog):
    a = propose(conn, cfg, catalog, RESTART)
    assert a["decision"] == "approved" and a["chk_id"] == "CHK-001"

    dup = copy.deepcopy(RESTART)
    dup["steps"][0]["params"]["value"] = 90  # 값만 다름
    r = propose(conn, cfg, catalog, dup, worker="w2")
    assert r["decision"] == "rejected"
    assert r["best_match"] == "CHK-001" and r["score"] == 1.0
    assert r["similar"][0]["diff"]["steps"] == ["  " + t for t in
                                                 ["set_config:timeout", "restart_service", "wait", "service_status"]]
    hinted = {h["action"] for h in r["uncovered_hints"]}
    assert "block_network" in hinted and "set_config" not in hinted

    rows = conn.execute("SELECT decision, best_match_chk FROM proposal ORDER BY proposal_id").fetchall()
    assert [tuple(r) for r in rows] == [("approved", None), ("rejected", "CHK-001")]


def test_structurally_different_is_approved(conn, cfg, catalog):
    propose(conn, cfg, catalog, RESTART)
    r = propose(conn, cfg, catalog, NETWORK)
    assert r["decision"] == "approved" and r["chk_id"] == "CHK-002"


def test_reordered_steps_with_diff(conn, cfg, catalog):
    propose(conn, cfg, catalog, RESTART)
    reordered = copy.deepcopy(RESTART)
    reordered["steps"] = list(reversed(reordered["steps"]))
    r = propose(conn, cfg, catalog, reordered)
    # 순서가 뒤집히면 편집거리가 커져 다른 테스트로 본다
    assert r["decision"] == "approved"


def test_inconclusive_can_be_retried_until_limit(conn, cfg, catalog):
    first = propose(conn, cfg, catalog, RESTART)["chk_id"]
    set_status(conn, first, "INCONCLUSIVE")

    retry1 = propose(conn, cfg, catalog, RESTART)
    assert retry1["decision"] == "approved" and retry1["retry_of"] == first
    assert retry1["retry_reason"] == "inconclusive_retry"
    # 원본은 대체되어 후보에서 빠지고, 진행 중인 재시도가 다음 중복을 막는다
    assert propose(conn, cfg, catalog, RESTART)["decision"] == "rejected"

    set_status(conn, retry1["chk_id"], "INCONCLUSIVE")
    retry2 = propose(conn, cfg, catalog, RESTART)
    assert retry2["decision"] == "approved" and retry2["retry_of"] == retry1["chk_id"]

    set_status(conn, retry2["chk_id"], "INCONCLUSIVE")  # retry_count == max_retries(2)
    assert propose(conn, cfg, catalog, RESTART)["decision"] == "rejected"


def test_fail_is_reproduced_once(conn, cfg, catalog):
    first = propose(conn, cfg, catalog, RESTART)["chk_id"]
    set_status(conn, first, "FAIL")

    repro = propose(conn, cfg, catalog, RESTART)
    assert repro["decision"] == "approved" and repro["retry_reason"] == "fail_reproduction"

    set_status(conn, repro["chk_id"], "FAIL")  # FAIL → FAIL: 재현 확인 완료
    assert propose(conn, cfg, catalog, RESTART)["decision"] == "rejected"


def test_pass_blocks(conn, cfg, catalog):
    chk = propose(conn, cfg, catalog, RESTART)["chk_id"]
    set_status(conn, chk, "PASS")
    assert propose(conn, cfg, catalog, RESTART)["decision"] == "rejected"


def test_other_agent_version_is_not_compared(conn, cfg, catalog):
    propose(conn, cfg, catalog, RESTART)
    conn.execute("INSERT INTO run (run_id, agent_version) VALUES ('run-2', '2.0.0')")
    r = propose_test(conn, cfg, catalog, run_id="run-2", worker_id="w1", scenario=RESTART)
    assert r["decision"] == "approved"


def test_coverage_view(conn, cfg, catalog):
    propose(conn, cfg, catalog, RESTART)
    propose(conn, cfg, catalog, NETWORK)
    rows = {(r["area"], r["action"]): r["tests"] for r in conn.execute("SELECT * FROM coverage")}
    assert rows[("service", "restart_service")] == 1
    assert rows[("network", "wait")] == 1
    assert rows[("service", "wait")] == 1
