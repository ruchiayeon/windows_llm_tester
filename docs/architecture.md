# wtest — Windows 에이전트 병렬 자동 테스트 아키텍처

> 상태: 설계 초안 v0.2 (2026-10-08, M1 구현 반영)
> 핵심 결정: Hyper-V + 차등 디스크 / VM 1대당 Claude 1세션 / 직접 통신 없이 MCP 공유 저장소로 협업 / RAG 전용(CAG 미사용) / 구조 유사도 70% 이상이면 동일 테스트

---

## 1. 전체 구성

```mermaid
flowchart LR
  subgraph HOST["Windows 11 Host (Orchestrator만 관리자 권한)"]
    ORCH["Orchestrator<br/>Python"]
    PLAN["Planner<br/>claude -p"]
    Q[("작업 큐")]

    subgraph WORKERS["Workers (병렬 N)"]
      W1["worker-1"]
      W2["worker-2"]
      WN["worker-N"]
    end

    subgraph CLAUDE["Claude 세션 (호스트 셸 권한 없음)"]
      C1["Claude A"]
      C2["Claude B"]
      CN["Claude N"]
    end

    subgraph MCP["wtest-mcp (세션마다 stdio 1개)"]
      M1["mcp #1<br/>VM=run-01"]
      M2["mcp #2<br/>VM=run-02"]
      MN["mcp #N<br/>VM=run-N"]
    end

    DB[("coverage.db<br/>SQLite + sqlite-vec")]
    COL["Collector"]
    REP["Reporter"]
    OUT[/"reports/<br/>CHK-xxx_*.zip<br/>report.html"/]
  end

  subgraph HV["Hyper-V"]
    BASE[("base.vhdx<br/>골든 이미지 · 읽기 전용")]
    V1["VM run-01<br/>차등 디스크"]
    V2["VM run-02<br/>차등 디스크"]
    VN["VM run-N<br/>차등 디스크"]
  end

  ORCH --> PLAN
  PLAN -- "list_coverage / propose_test" --> DB
  PLAN -- "승인된 시나리오" --> Q
  Q --> W1 & W2 & WN
  W1 --> C1 --> M1
  W2 --> C2 --> M2
  WN --> CN --> MN
  M1 & M2 & MN <--> DB
  M1 -- "PowerShell Direct" --> V1
  M2 -- "PowerShell Direct" --> V2
  MN -- "PowerShell Direct" --> VN
  BASE -. "부모 디스크" .-> V1 & V2 & VN
  W1 & W2 & WN --> COL --> OUT
  COL --> DB
  DB --> REP --> OUT
```

**원칙**
- Claude 세션끼리는 직접 통신하지 않는다. 모든 공유는 `coverage.db`를 통해서만 한다.
- Claude에게는 호스트 셸을 주지 않는다. 자기 VM에 묶인 MCP 도구만 준다.
- 프롬프트에는 행동 규칙만 넣고, 지식은 모두 MCP로 조회한다(RAG).

---

## 2. 전체 파이프라인

```mermaid
flowchart TD
  A["0. 이미지 빌드<br/>Packer → base.vhdx<br/>Windows + 에이전트 설치 + sysprep"] --> B
  B["1. Recon<br/>설치 전후 스냅샷 diff<br/>서비스·프로세스·레지스트리·포트·로그·설정"] --> C
  C["동작 프로파일 생성<br/>claude -p → profile 섹션별 DB 저장<br/>+ 문서 청크 임베딩"] --> D
  D["2. Plan<br/>Planner가 빈 커버리지 조회 후 시나리오 제안"] --> E{"propose_test<br/>유사도 < 0.7 ?"}
  E -- "예" --> F["큐 등록 (CHK-xxx)"]
  E -- "아니오" --> D
  F --> G["3. Execute (병렬)<br/>worker = VM + Claude 세션"]
  G --> H["4. Collect<br/>증거 수집 → CHK-xxx.zip"]
  H --> I["5. Judge<br/>결정적 체크 + Claude 해석"]
  I --> J["6. Report<br/>HTML 리포트 + 체크리스트 번호별 zip 목록"]
  G -. "탐색 모드: worker도 직접 propose_test" .-> E
```

---

## 3. VM 수명 주기 (Docker 대응)

```mermaid
flowchart LR
  P["Packer build<br/>(= docker build)"] --> BASE[("base.vhdx<br/>(= image)")]
  BASE --> N1["New-VHD -Differencing<br/>run-03.vhdx<br/>(= 쓰기 레이어)"]
  N1 --> N2["New-VM / Start-VM<br/>(= docker run)"]
  N2 --> N3{"PS Direct<br/>응답?"}
  N3 -- "타임아웃" --> X["부팅 실패 기록<br/>INCONCLUSIVE"]
  N3 -- "OK" --> N4["Invoke-Command -VMName<br/>(= docker exec)"]
  N4 --> N5["Copy-Item -FromSession<br/>(= docker cp)"]
  N5 --> N6["Stop-VM · Remove-VM<br/>run-03.vhdx 삭제<br/>(= docker rm)"]
  X --> N6
  N6 --> N1
```

---

## 4. Worker 1회 실행 시퀀스

```mermaid
sequenceDiagram
  autonumber
  participant O as Orchestrator
  participant W as Worker
  participant H as Hyper-V
  participant C as Claude 세션
  participant M as wtest-mcp
  participant D as coverage.db
  participant V as VM

  O->>W: 작업 할당 (CHK-031 또는 탐색 과제)
  W->>H: 차등 디스크 생성 + VM 기동
  H-->>W: PS Direct 준비 완료
  W->>C: claude -p 실행<br/>env: WTEST_WORKER / WTEST_VM / WTEST_CHK
  C->>M: (stdio) MCP 연결

  C->>M: get_profile / list_actions
  M->>D: 조회
  D-->>M: 결과
  M-->>C: 결과 + new_findings

  C->>M: propose_test(시나리오)
  M->>D: [트랜잭션] 유사도 비교 + 선점
  alt 유사도 < 0.7
    D-->>M: approved
    M-->>C: approved, CHK-031
  else 유사도 >= 0.7
    D-->>M: rejected + similar + hints
    M-->>C: rejected → 재구상
  end

  loop 시나리오 단계
    C->>M: vm_action / vm_query / vm_read_log
    M->>V: PowerShell Direct
    V-->>M: 결과
    M-->>C: 결과 + new_findings
    C->>M: record_step
    M->>D: 단계 기록
  end

  opt 이상 현상 발견
    C->>M: post_finding
    M->>D: 저장 + 임베딩
  end

  C->>M: finish(verdict, summary)
  M->>D: 결과 확정
  C-->>W: 종료 (stream-json transcript)
  W->>V: 증거 수집 (로그·이벤트·덤프·스냅샷)
  W->>W: CHK-031_*.zip 생성 (+ transcript)
  W->>H: VM 삭제 + 차등 디스크 삭제
  W-->>O: 완료 → 다음 작업
```

---

## 5. Claude 세션 행동 루프

```mermaid
stateDiagram-v2
  [*] --> Context: 과제 수신
  Context --> Ideate: get_profile / list_coverage / read_findings
  Ideate --> Propose: 시나리오 구상
  Propose --> Execute: approved
  Propose --> Ideate: rejected 1~2회 (diff 참고해 구조 변경)
  Propose --> UseHint: rejected 3~4회
  UseHint --> Propose: uncovered_hints 채택
  Propose --> Saturated: rejected 5회
  Execute --> Execute: vm_action → 관찰 → record_step
  Execute --> Finish: 단계 완료
  Execute --> Finish: max_turns 또는 타임아웃 (INCONCLUSIVE)
  Saturated --> Finish: 탐색 포화 보고
  Finish --> [*]
```

---

## 6. propose_test 판정 로직

```mermaid
flowchart TD
  IN["propose_test(scenario)"] --> S1["구조 시그니처 추출<br/>값 제거 · 정규화"]
  S1 --> LOCK["BEGIN IMMEDIATE<br/>(쓰기 잠금)"]
  LOCK --> S2["후보 축소<br/>같은 agent_version<br/>+ 액션 종류 역색인<br/>(재시도로 대체된 테스트 제외)"]
  S2 --> S3["후보별 유사도 계산"]
  S3 --> F["score = 0.6 × 단계 순서 유사도 (편집 거리)<br/>+ 0.2 × 사전조건 Jaccard<br/>+ 0.2 × 판정기준 Jaccard"]
  F --> T{"max score ≥ 0.7 ?"}
  T -- "아니오" --> OK["tests에 INSERT (status=claimed)<br/>proposals에 approved 기록"]
  OK --> R1["approved + chk_id"]
  T -- "예" --> P{"기존 결과 정책"}
  P -- "INCONCLUSIVE 이고 재시도 < N" --> OK
  P -- "FAIL 이고 재현 확인 전" --> OK
  P -- "그 외" --> NG["proposals에 rejected 기록<br/>(점수 · 비교 대상 · diff)"]
  NG --> HINT["uncovered_hints 생성<br/>커버리지 빈 칸 SQL 집계"]
  HINT --> R2["rejected + similar top-3 + diff + hints"]
  R1 & R2 --> COMMIT["COMMIT"]
```

**시그니처 예시**

| 원본 | 시그니처 |
|---|---|
| `set_config(key=timeout, value=30)` | `set_config:timeout` |
| `block_network(port=443)` | `block_network` |
| `restart_service(svc=AgentSvc)` | `restart_service` |
| `wait(60)` | `wait` |

임계값, 가중치, 값 경계 클래스 사용 여부(`normal/boundary/invalid`)는 설정 파일로 관리한다.

- 후보 축소도 잠금 안에서 한다. 잠금 밖에서 후보를 고르면 그 사이 다른 worker가 넣은 시나리오를 놓쳐 중복 승인이 생긴다.
- 유사 테스트가 여럿이면 **모두** 재승인 가능할 때만 승인한다. 재승인되면 새 CHK를 만들고 원본은 `superseded_by`로 후보에서 뺀다.
- "FAIL 재현 확인 전"은 직전 테스트(`retry_of`)가 FAIL이 아닌 FAIL을 뜻한다. FAIL → FAIL이면 재현 확인으로 본다. 모든 재승인은 `max_retries`로 제한한다.

---

## 7. MCP 도구 구성

```mermaid
flowchart LR
  ENV["실행 환경이 고정<br/>WTEST_WORKER · WTEST_VM · WTEST_CHK"] --> SRV

  subgraph SRV["wtest-mcp"]
    subgraph VMT["VM 도구 (WTEST_VM에 고정)"]
      a1["vm_action"]
      a2["vm_query"]
      a3["vm_read_log"]
      a4["vm_screenshot"]
    end
    subgraph KN["지식 조회 (RAG)"]
      k1["list_actions"]
      k2["describe_action"]
      k3["get_profile"]
      k4["search_docs (벡터)"]
    end
    subgraph CO["협업"]
      c1["propose_test"]
      c2["list_coverage"]
      c3["post_finding"]
      c4["read_findings"]
      c5["search_findings (벡터)"]
      c6["search_logs (벡터)"]
    end
    subgraph RC["기록 (WTEST_CHK에 고정)"]
      r1["record_step"]
      r2["finish"]
    end
  end

  VMT --> PSD["PowerShell Direct → 자기 VM"]
  KN & CO & RC --> DB[("coverage.db")]
  SRV -. "모든 응답에 편승" .-> NF["new_findings<br/>(마지막 호출 이후 신규 발견)"]
```

- **CHK 고정 범위**: 고정 모드는 `WTEST_CHK`로 시작부터 정해진다. 탐색 모드는 `propose_test` 승인 시점에 세션 CHK가 정해지며, 그 전에는 `record_step`·`finish(PASS|FAIL|INCONCLUSIVE)`를 쓸 수 없다. 세션 하나는 CHK 하나만 가진다.
- 세션 내 거절 횟수에 따라 응답의 `guidance`가 바뀐다(§5). 거절 한도에 도달하면 `propose_test`는 거부되고 `finish(verdict="SATURATED")`만 남는다.
- `new_findings`는 세션 시작 이후 **다른** worker가 올린 발견만 싣는다.
- `search_*`는 M5 전까지 벡터 대신 부분 문자열 검색으로 동작한다(도구 인터페이스는 동일).

---

## 8. 데이터 모델 (coverage.db)

```mermaid
erDiagram
  RUN ||--o{ TEST : contains
  TEST ||--o{ STEP : has
  TEST ||--o{ FINDING : produces
  TEST ||--o{ LOG_SIGNATURE : emits
  TEST ||--o| BUNDLE : evidence
  RUN ||--o{ PROPOSAL : logs
  PROPOSAL }o--o| TEST : "best match"
  FINDING ||--o| FINDING_VEC : embedding
  LOG_SIGNATURE ||--o| LOG_VEC : embedding
  PROFILE_SECTION }o--|| RUN : "profile_version"
  DOC_CHUNK ||--o| DOC_VEC : embedding
  ACTION ||--o{ STEP : "used by"

  RUN {
    text run_id PK
    text agent_version
    text profile_version
    datetime started_at
  }
  TEST {
    text chk_id PK
    text run_id FK
    text agent_version
    text worker_id
    text vm_name
    text mode "fixed | explore"
    text signature_json
    text signature_hash
    text status "claimed | running | PASS | FAIL | INCONCLUSIVE"
    int retry_count
    datetime claimed_at
    datetime finished_at
  }
  STEP {
    int step_id PK
    text chk_id FK
    int seq
    text action FK
    text params_json
    text observed
    text result "ok | fail | skip"
  }
  PROPOSAL {
    int proposal_id PK
    text run_id FK
    text worker_id
    text signature_json
    text best_match_chk
    real score
    text decision "approved | rejected"
  }
  FINDING {
    int finding_id PK
    text chk_id FK
    text worker_id
    text severity
    text summary
    text evidence_ref
    datetime created_at
  }
  LOG_SIGNATURE {
    int log_id PK
    text chk_id FK
    text source "app | System | Application | kernel"
    text normalized_message
    int count
  }
  BUNDLE {
    text chk_id PK
    text zip_path
    text sha256
    int size_bytes
  }
  ACTION {
    text name PK
    text category
    text params_schema
    text description
  }
  PROFILE_SECTION {
    text section PK
    text profile_version
    text content
  }
  DOC_CHUNK {
    int chunk_id PK
    text source
    text content
  }
  FINDING_VEC {
    int finding_id PK
    blob embedding
  }
  LOG_VEC {
    int log_id PK
    blob embedding
  }
  DOC_VEC {
    int chunk_id PK
    blob embedding
  }
```

- M1 구현에서 추가한 열·테이블: `TEST.title · area · scenario_json · retry_of · superseded_by · summary`, `PROPOSAL.approved_chk`, 후보 축소 역색인 `test_action(chk_id, action)`, 세션 이벤트 `worker_event`(탐색 포화 보고 등).
- `coverage`는 별도 테이블이 아니라 `TEST`와 `STEP`을 영역 × 액션 × 조건으로 집계한 뷰로 둔다.
  - M1의 `coverage` 뷰는 영역 × 액션까지만 집계한다. 조건 축은 Recon 프로파일로 조건 어휘가 정해지는 M3에서 추가한다.
- `*_VEC`는 sqlite-vec 가상 테이블이며, 임베딩은 로컬 다국어 모델로 생성한다.
- SQLite는 WAL 모드로 여러 MCP 프로세스의 동시 읽기·쓰기를 처리한다.

---

## 9. 증거 번들 구조

```mermaid
flowchart TD
  Z["CHK-031_service_restart_FAIL_20261007-1432.zip"]
  Z --> m["manifest.json<br/>시나리오 · 단계 결과 · 타임스탬프 · SHA256"]
  Z --> t["claude_transcript.jsonl<br/>판단 과정"]
  Z --> a["app_logs/<br/>에이전트 자체 로그"]
  Z --> e["eventlog/<br/>System · Application · 에이전트 채널 .evtx<br/>(테스트 시간 범위)"]
  Z --> s["state/<br/>전후 서비스 · 프로세스 · 포트 · 레지스트리 스냅샷"]
  Z --> w["wer/<br/>앱 크래시 덤프"]
  Z --> k["kernel/<br/>minidump · WPR 트레이스<br/>(FAIL 또는 시나리오 지정 시만)"]
  Z --> sc["screenshots/<br/>(GUI 시나리오만)"]
```

---

## 10. 권한과 격리 경계

```mermaid
flowchart LR
  subgraph T1["신뢰 영역: Host 관리자"]
    ORCH["Orchestrator · Worker"]
    MCPS["wtest-mcp 프로세스"]
  end
  subgraph T2["제한 영역: Claude 세션"]
    CL["Claude<br/>Bash · PowerShell · Edit · Write 금지<br/>mcp__wtest__* 만 허용<br/>max_turns · 타임아웃"]
  end
  subgraph T3["폐기 영역: 테스트 VM"]
    VM["run-NN<br/>매 테스트 후 삭제"]
  end

  ORCH -- "env로 VM · CHK 고정" --> MCPS
  CL -- "정의된 도구 호출만" --> MCPS
  MCPS -- "정의된 액션만<br/>PowerShell Direct" --> VM
  CL -. "직접 접근 불가" .-x VM
  CL -. "호스트 셸 없음" .-x ORCH
```

액션 카탈로그에 없는 동작은 실행할 수 없으므로, 테스트 범위를 벗어나는 행동은 구조적으로 차단된다.

---

## 11. 마일스톤

```mermaid
flowchart LR
  M1["M1 기반<br/>· wtest-mcp 골격<br/>· coverage.db 스키마<br/>· 구조 유사도 + propose_test<br/>· 가짜 VM으로 병렬 협업 검증"]
  M2["M2 VM 연결<br/>· wtest up/exec/down<br/>· 액션 6~8개<br/>· Collector + zip<br/>· VM 1대 + Claude 1개 E2E"]
  M3["M3 병렬화<br/>· 작업 큐 · worker N<br/>· Recon + 동작 프로파일<br/>· Planner"]
  M4["M4 판정 · 리포트<br/>· 결정적 체크 + Claude 해석<br/>· HTML 리포트<br/>· 체크리스트별 zip 목록"]
  M5["M5 고도화<br/>· 벡터 검색 (findings · logs · docs)<br/>· 버전 간 회귀 diff<br/>· 실패 재현 시나리오 축소"]
  M1 --> M2 --> M3 --> M4 --> M5
```

---

## 12. 미정 사항

| 항목 | 상태 |
|---|---|
| 테스트 대상 에이전트 형태 (GUI · 서비스 · 드라이버) | 미정. UI 자동화와 커널 수집 범위가 여기에 따라 결정됨 |
| 골든 이미지 확보 방법 (평가판 ISO · 사내 이미지) | 미정 |
| 호스트 RAM, 즉 병렬 VM 수 | 미정 (VM당 약 4GB 가정) |
| Claude 연결 방식 | M1~M2는 `claude -p --strict-mcp-config --tools= --allowedTools mcp__wtest`(M1 스모크 확인), 이후 Agent SDK 전환 검토 |
| 임베딩 모델 | 로컬 다국어 모델 (M5에서 확정) |
