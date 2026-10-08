"""M1 종료 기준: 별도 프로세스 N개가 동시에 제안해도 같은 테스트는 정확히 하나만 승인된다."""

import asyncio
import contextlib
import json
import multiprocessing as mp
import sys
from concurrent.futures import ProcessPoolExecutor

from mcp import Client, StdioServerParameters

from conftest import ROOT, RUN
from helpers import distinct, propose_worker, variant

N = 8


def run_parallel(cfg, scenarios):
    with mp.Manager() as manager:
        barrier = manager.Barrier(len(scenarios))
        with ProcessPoolExecutor(max_workers=len(scenarios)) as pool:
            futures = [
                pool.submit(propose_worker, str(cfg.db_path), str(ROOT / "wtest.toml"), f"w{i}", sc, barrier)
                for i, sc in enumerate(scenarios)
            ]
            return [f.result(timeout=120) for f in futures]


def test_near_duplicates_exactly_one_approved(conn, cfg):
    results = run_parallel(cfg, [variant(i) for i in range(N)])
    approved = [r for r in results if r["decision"] == "approved"]
    rejected = [r for r in results if r["decision"] == "rejected"]
    assert len(approved) == 1, results
    assert len(rejected) == N - 1
    assert all(r["best_match"] == approved[0]["chk_id"] for r in rejected)
    assert all(r["score"] >= cfg.similarity.threshold for r in rejected)
    assert conn.execute("SELECT COUNT(*) FROM test").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM proposal").fetchone()[0] == N


def test_distinct_scenarios_all_approved_with_unique_ids(conn, cfg):
    results = run_parallel(cfg, [distinct(i) for i in range(N)])
    assert all(r["decision"] == "approved" for r in results), results
    assert len({r["chk_id"] for r in results}) == N


def server_params(cfg, worker: str, vm: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "wtest", "mcp"],
        env={"WTEST_CONFIG": str(ROOT / "wtest.toml"), "WTEST_DB": str(cfg.db_path),
             "WTEST_RUN": RUN, "WTEST_WORKER": worker, "WTEST_VM": vm, "WTEST_BACKEND": "fake"},
    )


def payload(result) -> dict:
    assert not result.is_error, result.content
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def test_mcp_stdio_sessions_collaborate(conn, cfg):
    """실제 stdio MCP 서버 N개(= Claude 세션 N개 자리)를 같은 DB에 붙여 협업시킨다."""
    n = 4
    finding = "AgentSvc does not auto-restart after kill"

    async def main():
        async with contextlib.AsyncExitStack() as stack:
            # anyio 컨텍스트는 연 태스크에서 닫아야 하므로 연결은 순서대로 연다
            clients = [await stack.enter_async_context(Client(server_params(cfg, f"w{i}", f"run-{i:02d}")))
                       for i in range(n)]

            # 1) 근접 중복을 동시에 제안
            proposals = await asyncio.gather(*(
                c.call_tool("propose_test", {"scenario": variant(i)}) for i, c in enumerate(clients)))
            decisions = [payload(r)["result"] for r in proposals]
            winners = [i for i, d in enumerate(decisions) if d["decision"] == "approved"]
            assert len(winners) == 1, decisions
            w = clients[winners[0]]

            # 2) 승인 세션: 자기 VM에서 실행 → 기록 → 발견 공유 → 확정
            out = payload(await w.call_tool("vm_action", {"action": "kill_process", "params": {"name": "agent.exe"}}))
            assert out["result"]["ok"]
            await w.call_tool("record_step", {"action": "kill_process", "params": {"name": "agent.exe"},
                                              "observed": "AgentSvc stopped", "result": "fail"})
            await w.call_tool("post_finding", {"severity": "high", "summary": finding})
            fin = payload(await w.call_tool("finish", {"verdict": "FAIL", "summary": "no auto-restart"}))
            assert fin["result"]["verdict"] == "FAIL"

            # 3) 거절 세션: 카탈로그 밖 액션 거부, 승인 전 기록 불가, 다른 세션의 발견이 편승됨
            seen = {}
            for i, c in enumerate(clients):
                if i == winners[0]:
                    continue
                assert (await c.call_tool("vm_action", {"action": "format_disk"})).is_error
                assert (await c.call_tool("record_step", {"action": "wait", "observed": "x",
                                                          "result": "ok"})).is_error
                seen[i] = payload(await c.call_tool("list_actions", {}))["new_findings"]
            own = payload(await w.call_tool("list_actions", {}))["new_findings"]
            return seen, own

    seen, own = asyncio.run(main())
    assert own == []  # 자기 발견은 편승되지 않는다
    assert all([f["summary"] for f in s] == [finding] for s in seen.values()), seen
    assert [r[0] for r in conn.execute("SELECT status FROM test")] == ["FAIL"]
