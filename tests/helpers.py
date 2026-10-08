"""테스트 시나리오 헬퍼."""

from __future__ import annotations


def scenario(*steps: tuple[str, dict], pre=(), crit=(), title="t", area="service") -> dict:
    return {
        "title": title,
        "area": area,
        "preconditions": list(pre),
        "steps": [{"action": a, "params": p} for a, p in steps],
        "criteria": list(crit),
    }


RESTART = scenario(
    ("set_config", {"key": "timeout", "value": 30}),
    ("restart_service", {"svc": "AgentSvc"}),
    ("wait", {"seconds": 60}),
    ("service_status", {"svc": "AgentSvc"}),
    pre=["AgentSvc running"],
    crit=["AgentSvc running within 60s", "no crash dump"],
    title="restart after timeout change",
)


def variant(i: int) -> dict:
    """RESTART와 값·문구만 조금 다른 근접 중복 (유사도 ≥ 0.7)."""
    import copy

    sc = copy.deepcopy(RESTART)
    sc["title"] = f"restart variant {i}"
    sc["steps"][0]["params"]["value"] = 10 + i
    sc["criteria"] = sc["criteria"] + [f"worker {i} extra check"]
    return sc


DISTINCT_STEPS = [
    ("set_config", {"key": "timeout", "value": 1}),
    ("restart_service", {"svc": "AgentSvc"}),
    ("stop_service", {"svc": "AgentSvc"}),
    ("start_service", {"svc": "AgentSvc"}),
    ("kill_process", {"name": "agent.exe"}),
    ("block_network", {"port": 443}),
    ("unblock_network", {}),
    ("wait", {"seconds": 5}),
]


def distinct(i: int) -> dict:
    """서로 구조가 다른 시나리오: 액션 하나만 쓰고 액션 종류를 i로 고른다."""
    return scenario(DISTINCT_STEPS[i % len(DISTINCT_STEPS)], title=f"distinct {i}")


def propose_worker(db_path: str, config_path: str, worker: str, sc: dict, barrier) -> dict:
    """별도 프로세스에서 자기 연결로 propose_test 한 번. 모든 프로세스가 barrier에서 동시에 출발한다."""
    import dataclasses
    from pathlib import Path

    from wtest.catalog import Catalog
    from wtest.config import load_config
    from wtest.db import connect
    from wtest.propose import propose_test

    cfg = dataclasses.replace(load_config(config_path), db_path=Path(db_path))
    catalog = Catalog.load(cfg.catalog_path)
    conn = connect(cfg.db_path, cfg.busy_timeout_ms)
    barrier.wait()
    try:
        result = propose_test(conn, cfg, catalog, run_id="run-test", worker_id=worker, scenario=sc)
    finally:
        conn.close()
    return {"worker": worker, **result}
