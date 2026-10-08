---
description: README & ARCHITECTURE 자동 업데이트
---

# Auto README & ARCHITECTURE Update Workflow (Integrity & Delta Check)

**CRITICAL INSTRUCTION: You MUST read EVERY SINGLE FILE in the entire project directory without omission.**
**Do not skip any file or directory. Comprehensive analysis is required.**

This workflow analyzes the latest code state, compares it with **both `README.md` and `docs/architecture.md`**, calculates the **Delta (Changes)**, and performs a **Surgical Update on both documents**.

**Core Principle**: Preserve the existing structure of both documents. Only modify what has changed. The two documents have different scopes:

* **`README.md`** — 사용자 관점의 기능 카탈로그·디렉토리 트리·시작 가이드
* **`docs/architecture.md`** (이하 ARCHITECTURE) — 개발자 관점의 전체 구성·파이프라인·시퀀스 다이어그램·MCP 도구·데이터 모델·권한 경계·마일스톤

두 문서를 일관된 한 번의 분석 결과로 동기화합니다.

## ⚠️ LANGUAGE ENFORCEMENT (KOREAN ONLY)

**All reasoning, explanations, Delta Reports, and interactions MUST be provided in KOREAN.**

* *Exception:* Technical terms (e.g., `class`, `pyproject.toml`, `src/wtest/cli.py`) and the actual content of the documents (if they require English) should remain in their original language.

## 0. Protocol Handshake (Rule Ingestion)

1. **Acknowledge Constraints:** Confirm strict full scanning of both `README.md` and `docs/architecture.md`.
2. **Commit to Preservation:** Confirm that existing headers and formatting in **both files** will remain untouched unless they are factually incorrect.
3. **Handshake Output:** Begin with:
> `✅ README & ARCHITECTURE Protocol Loaded: Integrity Scan & Delta Reporting Mode Active [Korean Output Enforced].`



## 1. Context & Rule Loading

1. Read `.agent/rules/default.md` (if exists).
2. **CRITICAL — README**: Read the current `README.md` and cache its **Structure Skeleton** (Headers, Table of Contents ordering, file tree section). 기존 §1~§N 헤더 순서를 그대로 유지해야 합니다.
3. **CRITICAL — ARCHITECTURE**: Read the current `docs/architecture.md` and cache:
    * **Header Skeleton** (`## 1. 전체 구성`, `## 2. 전체 파이프라인`, `## 3. VM 수명 주기`, `## 4. Worker 1회 실행 시퀀스`, `## 5. Claude 세션 행동 루프`, `## 6. propose_test 판정 로직`, `## 7. MCP 도구 구성`, `## 8. 데이터 모델 (coverage.db)`, `## 9. 증거 번들 구조`, `## 10. 권한과 격리 경계`, `## 11. 마일스톤`, `## 12. 미정 사항` 등 — 실제 파일의 헤더를 기준으로 캐시)
    * **결정 기록** — ADR 섹션이 있으면 기존 ADR-001 ~ ADR-NNN 번호를 캐시. 신규 ADR 은 다음 번호부터 부여 (재사용·역행 금지)
    * **Mermaid 다이어그램 위치** — 구성/시퀀스/플로우 다이어그램의 식별자와 섹션 매핑

## 2. Codebase Analysis (Read-Only) - **STRICT FULL SCAN**

### 2.1 Project Metadata

* Read `pyproject.toml`, `uv.lock`, `.python-version`, `wtest.toml`, `catalog/actions.toml` to identify dependency, config, and catalog changes.
* **ARCHITECTURE 영향**: 외부 패키지 추가/제거/버전 변경, 설정 키 변경, 카탈로그 액션 변경은 §1 전체 구성 및 §7 MCP 도구 구성에 반영해야 합니다.

### 2.2 Master Inventory Creation

* **Action**: Use `list_dir` recursively to get a flat list of **ALL** files.
* **Inventory Check**: Ensure no file is missed.

### 2.3 Module Detailed Analysis (1-to-1 Enforcement)

* **Action**: Iterate through the "Master Inventory".
* **For EVERY file**:
    1. Read content.
    2. Extract symbols (`class`, `def`, `Protocol`, `@dataclass`, `Enum`, 모듈 상수, SQL 테이블).
    3. Generate a 1-line summary for README.
    4. **Capture architectural elements for docs/architecture.md**:
        * 공개 API 시그니처, MCP 도구 이름·인자 (§7 MCP 도구 구성용)
        * `subprocess`, `threading`, `multiprocessing`, `BEGIN IMMEDIATE` 트랜잭션 흐름 (§4·§6 시퀀스/판정 로직용)
        * `schema.sql` 테이블·컬럼 변경 (§8 데이터 모델용)
        * 모듈 수준 전역 상태·캐시 (`functools.cache`, 모듈 변수, `threading.Lock` 등)
        * 모듈 간 `import` 의존 관계 — §1 전체 구성 다이어그램용
        * 새로운 동작 결정 — 신규 결정 기록(ADR) 후보



---

## 3. Delta Calculation & Pre-Update Report (MANDATORY STEP)

**Before generating the final document content, you MUST output a unified "Delta Report" block covering BOTH `README.md` and `docs/architecture.md`.**
Do not proceed to file writing until this report is generated and presented to the user.

**Action**: Compare [Current README + ARCHITECTURE] vs [Codebase Analysis].
**Output Format (MUST BE IN KOREAN)**:

### 🔍 **Delta Report: Proposed Changes (변경 제안 보고서)**

#### 📘 README.md

| Type | Path / Section | Change Description (Korean) |
| --- | --- | --- |
| **[NEW]** | `src/wtest/hyperv.py` | 구성 표에 추가됨. 기능: PowerShell Direct 기반 VM 백엔드. |
| **[MOD]** | `src/wtest/cli.py` | 설명 업데이트: `report` 하위 명령 추가됨. |
| **[DEL]** | `src/wtest/temp.py` | 구성 표에서 삭제됨. |
| **[DOC]** | `## Features` | "자동 업데이트" 기능 설명 추가. |
| **[KEEP]** | `## Installation` | 변경 사항 없음. 기존 텍스트 유지. |

#### 📗 docs/architecture.md

| Type | Path / Section | Change Description (Korean) |
| --- | --- | --- |
| **[TOOL]** | `## 7. MCP 도구 구성` | 도구 시그니처 갱신: `record_result` 에 `evidence` 인자 추가. |
| **[SEQ]** | `## 4. Worker 1회 실행 시퀀스` | 시퀀스 다이어그램에 재시도 분기 추가. |
| **[LOGIC]** | `## 6. propose_test 판정 로직` | 유사도 가중치·임계값 변경 반영. |
| **[DATA]** | `## 8. 데이터 모델 (coverage.db)` | `schema.sql` 신규 테이블/컬럼 반영. |
| **[DEP]** | `## 1. 전체 구성` | 신규 패키지 추가/버전 변경 반영. |
| **[ADR-NEW]** | `ADR-XXX` (신규 번호) | 새 아키텍처 결정 1줄 요약. 기존 번호 재사용 금지. |
| **[KEEP]** | `## 2. 전체 파이프라인` | 변경 사항 없음. 기존 텍스트 유지. |

* **Review Rule**:
    * 두 표 모두 `[MOD]`/`[NEW]`/`[TOOL]`/`[SEQ]`/`[LOGIC]`/`[DATA]`/`[ADR-NEW]` 가 비어 있으면 "로직 변경 사항이 감지되지 않았습니다 (No logic changes detected)."
    * **ADR 번호 무결성**: 신규 ADR 은 반드시 기존 최대 번호 + 1 부터 부여. 기존 번호의 의미를 변경해야 한다면 `[ADR-MOD]` 로 표기하고 본문에서 사유 명시.

---

## 4. Execution: Surgical Update Strategy

**Only after the Delta Report is generated, proceed to create the file content for BOTH documents.**

### 4.1 Structural Preservation Rule (The Anchor)

* **DO NOT** regenerate the entire file structure from scratch (둘 다 해당).
* **DO NOT** reorder existing Headers (`##`, `###`).
* **DO NOT** renumber existing sections or ADR (ADR-001 ~ ADR-NNN 의 번호와 의미는 immutable).
* **DO** inject new information into the existing skeleton.
* *Example*: If `## Usage` is at the bottom of README, keep it at the bottom. ARCHITECTURE 의 `## 12. 미정 사항` 도 항상 마지막 섹션 유지.

### 4.2 File Tree Mirroring (README §구성 + ARCHITECTURE §1)

* Update the "구성" table in `README.md` AND the module listing in `docs/architecture.md` §1 to match the **Master Inventory** exactly.
* Ensure every file in the Delta Report `[NEW]` list is added in **both** documents.
* Ensure every file in the Delta Report `[DEL]` list is removed from **both** documents.
* Ensure descriptions for `[MOD]` files are updated in **both** documents (README 는 1줄 요약, ARCHITECTURE 는 책임·핵심 자료구조까지).

### 4.3 Content Injection

#### README.md
* Update `구성`, `사용`, `테스트` 섹션 및 "현재 단계" 문구 only if the code analysis explicitly confirms a change.

#### docs/architecture.md
* **§1 전체 구성**: 모듈 추가/제거, 외부 패키지(`pyproject.toml`) 변경 시 구성 다이어그램과 설명 갱신.
* **§2~§5 파이프라인·VM 수명 주기·Worker 시퀀스·세션 루프**: 실행 흐름(`subprocess` 호출, 프로세스 생성, 재시도·타임아웃 분기)이 바뀌면 mermaid `sequenceDiagram`/`flowchart` 블록 갱신.
* **§6 propose_test 판정 로직**: 유사도 공식·가중치·임계값(`wtest.toml`)·`BEGIN IMMEDIATE` 선점 흐름 변경 반영.
* **§7 MCP 도구 구성**: `server.py` 의 도구 추가/제거/인자 변경, `catalog/actions.toml` 변경 반영.
* **§8 데이터 모델**: `schema.sql` 테이블·컬럼·인덱스 변경 반영.
* **§10 권한과 격리 경계**: `VMGuard` 검증 규칙이나 허용 도구 범위가 바뀌면 반영.
* **§11 마일스톤**: 완료된 단계 표시 갱신 (README "현재 단계"와 일치).
* **결정 기록 (ADR)**:
    * ADR 섹션이 있으면 신규 결정은 다음 번호부터 추가 (`ADR-NNN+1`, `ADR-NNN+2`, …).
    * 형식: `### ADR-NNN: 제목` + `**결정**` / `**이유**` / `**효과**` (또는 트레이드오프) 섹션.
    * 기존 ADR 의 결정이 번복되었다면 새 ADR 로 추가하고 본문에서 "ADR-XXX 를 대체" 명시 (기존 ADR 삭제 금지).

### 4.4 Cross-Document Consistency Check

작성 완료 후 다음을 확인:
* README §구성 표와 ARCHITECTURE §1 전체 구성의 모듈 목록이 일치하는가?
* README 의 "구현 모듈" 언급과 ARCHITECTURE 모듈 설명이 충돌하지 않는가?
* README 의 기능 설명에 명시된 동작이 ARCHITECTURE 의 시퀀스 다이어그램·ADR 과 모순되지 않는가?

## 5. Final Output

* **Action**: Display the full content of `README.md` and `docs/architecture.md` (또는 변경된 섹션만) in code blocks for user verification OR use `write_to_file` if explicitly authorized for both.
* **Order**: README.md 먼저, docs/architecture.md 나중. (사용자 관점 → 개발자 관점 순서)
* **Language**: **Korean (Interaction) & Bilingual (File Content)**. The final document content should follow each file's original language settings (English/Korean mixed), but your explanation must be in Korean.
