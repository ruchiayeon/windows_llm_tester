"""wtest-mcp: Claude 세션 하나에 붙는 stdio MCP 서버 (§7).

실행 환경이 세션을 고정한다:
  WTEST_RUN     run_id (필수)
  WTEST_WORKER  worker id (필수)
  WTEST_VM      이 세션이 조작할 수 있는 유일한 VM (필수)
  WTEST_CHK     고정 모드의 체크리스트 번호 (없으면 탐색 모드)
  WTEST_BACKEND fake | hyperv (기본 fake)
  WTEST_CONFIG  wtest.toml 경로

stdout은 MCP 프로토콜 전용이다. 로그는 모두 stderr로 보낸다.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from .catalog import Catalog, CatalogError
from .config import load_config
from .db import connect
from .session import Session, SessionError
from .vm import VMGuard, make_backend

log = logging.getLogger("wtest.mcp")

INSTRUCTIONS = """\
Windows 에이전트 테스트용 도구. 너는 VM 하나에 묶여 있고, 다른 세션과는 이 도구의 공유 저장소로만 협업한다.
1) get_profile · list_actions · list_coverage · read_findings로 맥락을 파악한다.
2) 탐색 모드면 propose_test로 시나리오를 제안한다. 거절되면 응답의 diff · guidance · uncovered_hints를 따른다.
3) 승인되면 vm_action · vm_query · vm_read_log로 실행하고, 단계마다 record_step으로 남긴다.
4) 이상 현상은 즉시 post_finding으로 공유한다. 모든 응답의 new_findings에 다른 세션의 발견이 실린다.
5) 끝나면 finish(verdict, summary). 거절 한도에 걸리면 finish(verdict='SATURATED').
"""


class Step(BaseModel):
    action: str = Field(description="카탈로그의 액션 또는 쿼리 이름")
    params: dict[str, Any] = Field(default_factory=dict)


class Scenario(BaseModel):
    title: str
    area: str = Field(description="테스트 영역 (예: service, network, config)")
    preconditions: list[str] = Field(default_factory=list)
    steps: list[Step]
    criteria: list[str] = Field(default_factory=list, description="PASS 판정 기준")


def build_server(session: Session) -> MCPServer:
    mcp = MCPServer("wtest", instructions=INSTRUCTIONS)
    # 세션 락: sqlite 연결과 세션 상태(CHK, 커서)를 보호한다.
    # VM 호출은 수십 초 걸릴 수 있고 외부 프로세스를 부르므로 락 밖에서 실행한다 (규칙 7.2).
    # VM 도구는 세션 상태를 건드리지 않으므로 락 없이도 안전하다.
    lock = threading.Lock()

    def wrap(result: Any) -> dict[str, Any]:
        with lock:
            return {"result": result, "new_findings": session.new_findings()}

    def call(fn: Callable[[], Any]) -> dict[str, Any]:
        """DB·세션 상태를 쓰는 도구: 실행부터 편승까지 세션 락 안에서."""
        with lock:
            try:
                result = fn()
            except (SessionError, CatalogError, ValueError, LookupError) as e:
                raise ToolError(str(e)) from e
            return {"result": result, "new_findings": session.new_findings()}

    def call_vm(fn: Callable[[], Any]) -> dict[str, Any]:
        """VM 도구: 실행은 락 밖, 편승 조회만 락 안에서."""
        try:
            result = fn()
        except (CatalogError, ValueError) as e:
            raise ToolError(str(e)) from e
        return wrap(result)

    # ---- VM 도구 (WTEST_VM에 고정) ------------------------------------------------
    @mcp.tool()
    def vm_action(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """자기 VM에서 카탈로그의 상태 변경 액션을 실행한다. 카탈로그 밖 액션은 거부된다."""
        return call_vm(lambda: session.vm.action(action, params))

    @mcp.tool()
    def vm_query(query: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """자기 VM의 상태를 읽기 전용으로 조회한다 (service_status, process_list, port_list, get_config 등)."""
        return call_vm(lambda: session.vm.query(query, params))

    @mcp.tool()
    def vm_read_log(source: Literal["app", "System", "Application"], max_lines: int = 50) -> dict[str, Any]:
        """자기 VM의 로그 마지막 N줄을 읽는다."""
        return call_vm(lambda: session.vm.read_log(source, max_lines))

    @mcp.tool()
    def vm_screenshot() -> dict[str, Any]:
        """자기 VM 화면을 캡처한다 (GUI 시나리오용)."""
        return call_vm(session.vm.screenshot)

    # ---- 지식 조회 (RAG) ---------------------------------------------------------
    @mcp.tool()
    def list_actions(kind: Literal["action", "query"] | None = None) -> dict[str, Any]:
        """사용할 수 있는 액션·쿼리 카탈로그."""
        return call(lambda: session.list_actions(kind))

    @mcp.tool()
    def describe_action(name: str) -> dict[str, Any]:
        """액션의 파라미터 스키마와 시그니처에 남는 파라미터."""
        return call(lambda: session.describe_action(name))

    @mcp.tool()
    def get_profile(section: str | None = None) -> dict[str, Any]:
        """에이전트 동작 프로파일. section 없이 부르면 섹션 목록을 준다."""
        return call(lambda: session.get_profile(section))

    @mcp.tool()
    def search_docs(query: str, limit: int = 5) -> dict[str, Any]:
        """제품 문서 청크 검색."""
        return call(lambda: session.search_docs(query, limit))

    # ---- 협업 ------------------------------------------------------------------
    @mcp.tool()
    def propose_test(scenario: Scenario) -> dict[str, Any]:
        """시나리오를 제안한다. 기존 테스트와 구조 유사도가 임계값 이상이면 거절되고 diff·힌트를 받는다."""
        return call(lambda: session.propose_test(scenario.model_dump()))

    @mcp.tool()
    def list_coverage(area: str | None = None) -> dict[str, Any]:
        """영역 × 액션 커버리지와 빈 칸 힌트."""
        return call(lambda: session.list_coverage(area))

    @mcp.tool()
    def post_finding(severity: Literal["info", "low", "medium", "high", "critical"], summary: str,
                     evidence_ref: str | None = None) -> dict[str, Any]:
        """이상 현상을 모든 세션에 공유한다."""
        return call(lambda: session.post_finding(severity, summary, evidence_ref))

    @mcp.tool()
    def read_findings(since_id: int = 0, limit: int = 20) -> dict[str, Any]:
        """공유된 발견 목록 (최신순)."""
        return call(lambda: session.read_findings(since_id, limit))

    @mcp.tool()
    def search_findings(query: str, limit: int = 10) -> dict[str, Any]:
        """발견 검색."""
        return call(lambda: session.search_findings(query, limit))

    @mcp.tool()
    def search_logs(query: str, limit: int = 10) -> dict[str, Any]:
        """수집된 로그 시그니처 검색."""
        return call(lambda: session.search_logs(query, limit))

    # ---- 기록 (배정된 CHK에 고정) -------------------------------------------------
    @mcp.tool()
    def record_step(action: str, observed: str, result: Literal["ok", "fail", "skip"],
                    params: dict[str, Any] | None = None) -> dict[str, Any]:
        """실행한 단계와 관찰 결과를 기록한다. CHK가 배정된 뒤에만 쓸 수 있다."""
        return call(lambda: session.record_step(action, params, observed, result))

    @mcp.tool()
    def finish(verdict: Literal["PASS", "FAIL", "INCONCLUSIVE", "SATURATED"], summary: str) -> dict[str, Any]:
        """테스트 결과를 확정하고 세션을 끝낸다."""
        return call(lambda: session.finish(verdict, summary))

    return mcp


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"환경 변수 {name}가 필요함")
    return value


def session_from_env() -> Session:
    cfg = load_config()
    catalog = Catalog.load(cfg.catalog_path)
    conn = connect(cfg.db_path, cfg.busy_timeout_ms)
    vm_name = _require_env("WTEST_VM")
    vm = VMGuard(make_backend(os.environ.get("WTEST_BACKEND", "fake"), vm_name), catalog)
    return Session(cfg, catalog, conn, vm, run_id=_require_env("WTEST_RUN"),
                   worker_id=_require_env("WTEST_WORKER"), chk_id=os.environ.get("WTEST_CHK") or None)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    session = session_from_env()
    log.info("start worker=%s vm=%s mode=%s chk=%s", session.worker_id, session.vm.backend.name,
             session.mode, session.chk_id)
    build_server(session).run("stdio")


if __name__ == "__main__":
    main()
