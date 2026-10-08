"""VM 백엔드. MCP 프로세스는 WTEST_VM 하나에만 묶인다.

M1은 FakeVM으로 병렬 협업을 검증하고, M2에서 PowerShell Direct 백엔드(HyperVBackend)를 붙인다.
백엔드는 카탈로그 검증을 통과한 액션만 받는다. 검증은 MCP 계층(server.py)이 아니라
VMGuard가 맡아 어떤 백엔드를 쓰든 카탈로그 밖 동작이 실행되지 않게 한다.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any, Protocol

from .catalog import Catalog


class VMBackend(Protocol):
    name: str

    def action(self, action: str, params: dict[str, Any]) -> dict[str, Any]: ...
    def query(self, query: str, params: dict[str, Any]) -> dict[str, Any]: ...
    def read_log(self, source: str, max_lines: int) -> list[str]: ...
    def screenshot(self) -> dict[str, Any]: ...


class VMGuard:
    """카탈로그 검증 + 백엔드 위임. §10의 '정의된 액션만' 경계."""

    LOG_SOURCES = ("app", "System", "Application")

    def __init__(self, backend: VMBackend, catalog: Catalog):
        self.backend = backend
        self.catalog = catalog

    def action(self, action: str, params: dict[str, Any] | None) -> dict[str, Any]:
        checked = self.catalog.get(action, kind="action").validate(params)
        return self.backend.action(action, checked)

    def query(self, query: str, params: dict[str, Any] | None) -> dict[str, Any]:
        checked = self.catalog.get(query, kind="query").validate(params)
        return self.backend.query(query, checked)

    def read_log(self, source: str, max_lines: int = 50) -> list[str]:
        if source not in self.LOG_SOURCES:
            raise ValueError(f"알 수 없는 로그 소스 '{source}'. 허용: {list(self.LOG_SOURCES)}")
        return self.backend.read_log(source, max(1, min(max_lines, 500)))

    def screenshot(self) -> dict[str, Any]:
        return self.backend.screenshot()


class FakeVM:
    """메모리 상태만 가진 가짜 VM. 에이전트 서비스 하나와 설정, 방화벽을 흉내 낸다."""

    def __init__(self, name: str):
        self.name = name
        self.services = {"AgentSvc": "Running", "AgentUpdater": "Running"}
        self.processes = {"agent.exe", "agent_updater.exe", "explorer.exe"}
        self.config: dict[str, int] = {"timeout": 30, "retry": 3, "poll_interval": 10}
        self.blocked_ports: set[int] = set()
        self.logs: dict[str, list[str]] = {s: [] for s in VMGuard.LOG_SOURCES}
        self._log("app", "agent started")

    def _log(self, source: str, message: str) -> None:
        stamp = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
        self.logs[source].append(f"{stamp} [{self.name}] {message}")

    def action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        match action:
            case "set_config":
                old = self.config.get(params["key"])
                self.config[params["key"]] = params["value"]
                self._log("app", f"config {params['key']}: {old} -> {params['value']}")
                return {"ok": True, "old": old, "new": params["value"]}
            case "restart_service" | "stop_service" | "start_service":
                svc = params["svc"]
                if svc not in self.services:
                    return {"ok": False, "error": f"service '{svc}' not found"}
                state = "Stopped" if action == "stop_service" else "Running"
                self.services[svc] = state
                self._log("System", f"Service Control Manager: {svc} {action.split('_')[0]} -> {state}")
                return {"ok": True, "svc": svc, "state": state}
            case "kill_process":
                name = params["name"]
                if name not in self.processes:
                    return {"ok": False, "error": f"process '{name}' not running"}
                self.processes.discard(name)
                if name == "agent.exe":
                    self.services["AgentSvc"] = "Stopped"
                    self._log("Application", "Application Error: agent.exe terminated unexpectedly")
                return {"ok": True, "killed": name}
            case "block_network":
                self.blocked_ports.add(params["port"])
                self._log("app", f"connection to server failed (port {params['port']} blocked)")
                return {"ok": True, "blocked": sorted(self.blocked_ports)}
            case "unblock_network":
                self.blocked_ports.clear()
                self._log("app", "connection restored")
                return {"ok": True, "blocked": []}
            case "wait":
                # 가짜 VM은 기본적으로 기다리지 않는다. WTEST_FAKE_WAIT_SCALE로 실제 대기 비율을 줄 수 있다
                time.sleep(params["seconds"] * float(os.environ.get("WTEST_FAKE_WAIT_SCALE", "0")))
                return {"ok": True, "waited": params["seconds"]}
        raise NotImplementedError(action)

    def query(self, query: str, params: dict[str, Any]) -> dict[str, Any]:
        match query:
            case "service_status":
                return {"svc": params["svc"], "state": self.services.get(params["svc"], "NotFound")}
            case "process_list":
                return {"processes": sorted(self.processes)}
            case "port_list":
                return {"listening": [443, 8443], "blocked": sorted(self.blocked_ports)}
            case "get_config":
                if "key" in params:
                    return {params["key"]: self.config.get(params["key"])}
                return dict(self.config)
        raise NotImplementedError(query)

    def read_log(self, source: str, max_lines: int) -> list[str]:
        return self.logs[source][-max_lines:]

    def screenshot(self) -> dict[str, Any]:
        return {"ok": False, "error": "FakeVM은 스크린샷을 지원하지 않음"}


def make_backend(kind: str, vm_name: str) -> VMBackend:
    if kind == "fake":
        return FakeVM(vm_name)
    if kind == "hyperv":
        raise NotImplementedError("HyperV 백엔드는 M2에서 구현")
    raise ValueError(f"알 수 없는 백엔드 '{kind}'")
