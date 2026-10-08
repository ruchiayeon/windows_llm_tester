import pytest

from wtest.catalog import CatalogError
from wtest.session import SessionError

from helpers import RESTART


def test_record_step_requires_approval(make_session):
    s = make_session()
    with pytest.raises(SessionError, match="propose_test"):
        s.record_step("wait", {"seconds": 1}, "ok", "ok")


def test_explore_flow(make_session, conn):
    s = make_session()
    r = s.propose_test(RESTART)
    assert r["decision"] == "approved" and s.chk_id == r["chk_id"]

    with pytest.raises(SessionError, match="이미"):
        s.propose_test(RESTART)

    out = s.vm.action("restart_service", {"svc": "AgentSvc"})
    s.record_step("restart_service", {"svc": "AgentSvc"}, str(out), "ok")
    assert conn.execute("SELECT status FROM test WHERE chk_id=?", (s.chk_id,)).fetchone()[0] == "running"

    assert s.finish("PASS", "restarted fine")["verdict"] == "PASS"
    with pytest.raises(SessionError):
        s.record_step("wait", {"seconds": 1}, "late", "ok")


def test_fixed_mode_uses_env_chk(make_session):
    chk = make_session(worker="planner").propose_test(RESTART)["chk_id"]
    s = make_session(worker="w2", chk=chk)
    assert s.mode == "fixed"
    with pytest.raises(SessionError):
        s.propose_test(RESTART)
    s.record_step("wait", {"seconds": 1}, "ok", "ok")
    s.finish("FAIL", "x")
    with pytest.raises(SessionError, match="FAIL"):
        make_session(worker="w3", chk=chk)


def test_rejection_guidance_and_saturation(make_session):
    make_session(worker="w0").propose_test(RESTART)
    s = make_session(worker="w1")
    guidance = [s.propose_test(RESTART)["guidance"] for _ in range(5)]
    assert "diff" in guidance[0]
    assert "uncovered_hints" in guidance[2]
    assert "SATURATED" in guidance[4]
    with pytest.raises(SessionError, match="포화"):
        s.propose_test(RESTART)
    assert s.finish("SATURATED", "tried restart variants")["verdict"] == "SATURATED"


def test_new_findings_piggyback_excludes_own(make_session):
    a, b = make_session(worker="a"), make_session(worker="b")
    a.post_finding("high", "agent.exe crash on restart")
    b.post_finding("low", "b's own note")
    got = b.new_findings()
    assert [f["summary"] for f in got] == ["agent.exe crash on restart"]
    assert b.new_findings() == []  # 커서 이동 후 재전달 없음
    assert [f["summary"] for f in a.new_findings()] == ["b's own note"]


def test_vm_guard_blocks_outside_catalog(make_session):
    s = make_session()
    with pytest.raises(CatalogError):
        s.vm.action("format_disk", {})
    with pytest.raises(CatalogError):
        s.vm.action("service_status", {"svc": "AgentSvc"})  # 쿼리를 액션으로 실행 불가
    with pytest.raises(CatalogError):
        s.vm.action("block_network", {"port": "443"})  # 타입 위반
    with pytest.raises(ValueError):
        s.vm.read_log("Security")
    assert s.vm.query("service_status", {"svc": "AgentSvc"})["state"] == "Running"


def test_fake_vm_state(make_session):
    s = make_session()
    s.vm.action("kill_process", {"name": "agent.exe"})
    assert s.vm.query("service_status", {"svc": "AgentSvc"})["state"] == "Stopped"
    assert any("terminated" in line for line in s.vm.read_log("Application"))
