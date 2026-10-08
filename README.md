# wtest

Windows 에이전트 병렬 자동 테스트. 설계는 [docs/architecture.md](docs/architecture.md)를 보세요.

현재 단계: **M1 기반** (wtest-mcp 골격, coverage.db 스키마, 구조 유사도와 propose_test, 가짜 VM으로 병렬 협업 검증)

## 구성

| 경로 | 내용 |
|---|---|
| `wtest.toml` | 임계값 · 가중치 · 재시도 정책 · DB 경로 |
| `catalog/actions.toml` | 액션·쿼리 카탈로그. 여기에 없는 동작은 실행도 제안도 못 한다 |
| `src/wtest/signature.py` | 시나리오 → 구조 시그니처 (값 제거 · 정규화) |
| `src/wtest/similarity.py` | `0.6×순서 유사도 + 0.2×사전조건 Jaccard + 0.2×판정기준 Jaccard` |
| `src/wtest/propose.py` | `BEGIN IMMEDIATE` 안에서 후보 축소 · 판정 · 선점 |
| `src/wtest/session.py` | 세션 하나의 상태와 도구 동작 (MCP와 분리) |
| `src/wtest/server.py` | stdio MCP 서버 (`MCPServer`, mcp 2.x) |
| `src/wtest/vm.py` | `VMGuard`(카탈로그 검증) + `FakeVM`. Hyper-V 백엔드는 M2 |

## 사용

```powershell
uv sync
uv run wtest init                                   # data/coverage.db 생성 + 카탈로그 적재
uv run wtest new-run run-001 --agent-version 1.0.0
uv run wtest mcp-config --run run-001 --worker w1 --vm run-01 > mcp-w1.json
# --tools "" 로 내장 도구(Bash · PowerShell · Edit · Write 등)를 모두 제거하고 wtest MCP 도구만 남긴다 (§10)
claude -p "탐색 과제: ..." --mcp-config mcp-w1.json --strict-mcp-config --tools "" --allowedTools "mcp__wtest__*"
uv run wtest status --run run-001
```

## 테스트

```powershell
uv run pytest -q
```

`tests/test_parallel.py`가 M1 종료 기준입니다.
- 별도 프로세스 8개가 근접 중복 시나리오를 동시에 제안 → 정확히 1개만 승인, 나머지는 그 CHK를 `best_match`로 거절
- 서로 다른 시나리오 8개 동시 제안 → 모두 승인, CHK 번호 중복 없음
- 실제 stdio MCP 서버 4개를 같은 DB에 붙여 제안 · 실행 · 기록 · 발견 공유 · `new_findings` 편승 · 카탈로그 밖 액션 거부 확인
