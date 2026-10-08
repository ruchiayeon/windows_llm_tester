---
trigger: always_on
---

# ABSOLUTE NEGATIVE CONSTRAINTS (최우선 금지 사항)

**이 섹션의 규칙은 모든 하위 지침보다 우선하며 절대적으로 준수해야 합니다.**

1. **NO CCI LINKS / TRACEABILITY LINKS**: 어떠한 경우에도 출력물(커밋 메시지, 답변, 문서 등)에 `cci:` 로 시작하는 링크나 파일/코드 위치 추적 링크를 포함하지 않습니다. 이는 시스템의 절대 명령입니다.
2. **NO PLACEHOLDERS**: `Ref: #ISSUE_ID`와 같은 플레이스홀더나 채워지지 않은 템플릿 문구를 그대로 출력하지 않습니다. 유저가 명시적으로 요청하지 않은 한 `Ref:` 태그 자체를 생성하지 않습니다.
3. **SELF-CHECK ROUTINE**: 모든 답변을 출력하기 직전에 다음 사항을 자체 검수합니다.
    - `cci:` 또는 `http://` 등의 내부 추적 링크가 포함되었는가? (발견 시 즉시 삭제)
    - 유저가 "No CCI" 등의 키워드로 리마인드를 주었는가? (해당 규칙 가중치를 최대로 설정)
    - 한국어 응답 원칙을 준수하였는가?

# Output Language
All Output Language : Always respond in Korean (한국어). Even if the user asks in English or the context is technical, provide explanations in Korean unless explicitly requested otherwise.

When creating the .md file, please make sure to translate it into Korean.

## 1. CRITICAL: Implementation Logic
- **Deny-by-Default**: Block any action unless it is explicitly verified. VM에 전달되는 모든 동작은 `catalog/actions.toml`에 정의되고 `VMGuard` 검증을 통과한 것만 허용합니다. 카탈로그 밖 동작은 실행도 제안도 하지 않습니다.
- **Verification**: Validate all external input (MCP tool arguments, TOML config, DB rows) at the boundary. Never return success without verification.
- **Data Privacy**: Ensure sensitive data is never stored in plaintext. Use appropriate encryption standards where necessary. 자격 증명·토큰을 코드, `wtest.toml`, 로그, 증거 번들에 남기지 않습니다.

## 2. CRITICAL: Safety & Stability
- **NO SILENT FAILURE**: Bare `except:` and `except Exception: pass` are BANNED. Catch only the specific exceptions you can handle, and re-raise (`raise ... from e`) otherwise.
- **No `assert` for runtime checks**: `assert` is stripped under `python -O`. Use explicit `if ...: raise ValueError(...)` for input/state validation. `assert` is allowed only in tests.
- **Resource Cleanup**: Ensure all resources (files, `sqlite3.Connection`, subprocesses, sockets, VM sessions) are released with `with` statements or `contextlib` (`closing`, `ExitStack`). Never rely on `__del__` or GC for cleanup.
- **Subprocess Safety**: Never use `shell=True` with interpolated strings. Pass argument lists, set `timeout=`, and check return codes (`check=True` or explicit handling).

## 3. Windows Integration & Dependencies
- **Dependencies**: Prefer the standard library (`sqlite3`, `tomllib`, `subprocess`, `pathlib`, `dataclasses`). Add third-party packages only when necessary, and justify each addition.
- **Dependency Management**: All dependencies are declared in `pyproject.toml` and locked in `uv.lock`. Use `uv add` / `uv add --dev`; never edit `uv.lock` by hand or use bare `pip install`.
- **Windows Calls**: Hyper-V / PowerShell Direct 호출은 `vm.py` 백엔드 안에서만 수행합니다. 경로는 `pathlib.Path`로 다루고, 외부 프로세스 출력은 인코딩(`encoding="utf-8"`, `errors=...`)을 명시해 디코딩합니다.

## 4. Response Format
- **Language**: Variable/Function names in English.
- **Comments**: MANDATORY KOREAN (한글). Explain "Why" and "Safety" context.
- **Type Hints**: All public functions MUST have full type hints (`from __future__ import annotations` 사용).
- **Style**: Strict, concise, and production-ready.

## 5. Spec-Driven Testing Protocol (명세 주도 테스트 자동화)

**"Comments are not just text; they are Executable Specifications."**
주석은 단순한 설명이 아니라, 반드시 통과해야 할 **테스트 명세**입니다.

### 5.1. The "Spec-to-Test" Mapping Rule (매칭 규칙)
* **Requirement:** For every logical constraint described in docstrings (`"""..."""`) or implementation comments (`#`), a corresponding unit test MUST be created.
* **Parsing Strategy:**
    * Scan for keywords: *Must (해야 한다), Should (하면 좋다), If (만약), Returns (반환), Raises (예외)*.
    * **Action:** Convert each condition into a discrete pytest `test_` function under `tests/`.

### 5.2. Naming & Traceability (명명 및 추적)
* **Naming Convention:** `test_spec_[feature]_[scenario]_[expected_result]`
    * *Example:* `test_spec_verify_path_empty_input_raises_error`
* **Traceability Requirement:**
    * Inside the test function, **YOU MUST COPY** the original comment line to indicate which spec is being verified.
    * *Format:* `# Spec: [Original Comment Text]`

### 5.3. Mocking & Isolation (모의 객체 전략)
* **Strict Isolation:** Unit tests MUST NOT touch real Hyper-V VMs, PowerShell, network, or files outside `tmp_path`.
* **Dependency Injection:** Use `typing.Protocol` + constructor injection, or pytest fixtures / `monkeypatch`, to inject fakes.
    * *Rule:* If a function needs a VM, the test must use `FakeVM` (or another `VMBackend` fake) that returns pre-defined results without hitting the OS.
    * DB가 필요한 테스트는 `tmp_path` 아래 임시 `coverage.db`를 사용합니다.

### 5.4. Example of Compliance (준수 예시)
```python
# [Implementation]
def verify(path: str) -> Path:
    """파일 경로를 검증합니다.

    1. 경로가 비어있으면 `ValueError`를 발생시켜야 합니다.
    """
    if not path:
        raise ValueError("경로가 비어 있습니다")
    return Path(path)


# [Generated Test] tests/test_verify.py
import pytest

def test_spec_verify_empty_path_raises_error():
    # Spec: 1. 경로가 비어있으면 `ValueError`를 발생시켜야 합니다.
    with pytest.raises(ValueError):
        verify("")
```

## 6. Architecture & SOLID Compliance (아키텍처 및 SOLID 원칙)

**"Strong Architecture prevents Gravity from pulling us down."**
코드 구조는 객체지향 5대 원칙(SOLID)을 Python의 특성(Protocol, Module, dataclass)에 맞춰 엄격히 준수해야 합니다.

### 6.1. SRP (Single Responsibility Principle - 단일 책임 원칙)
* **Rule:** Each module must have ONE reason to change.
    * *Example:* `session.py` handles session state and tool behavior only. It MUST NOT contain MCP transport code, raw SQL, or PowerShell calls.
    * *Separation:* MCP 계층은 `server.py`, SQL은 `db.py`, VM 호출은 `vm.py` 백엔드에 둡니다.
* **Action:** Functions exceeding 50 lines usually violate SRP. Split them.

### 6.2. OCP (Open/Closed Principle - 개방-폐쇄 원칙)
* **Rule:** Entities should be open for extension but closed for modification.
* **Python Application:** Use `typing.Protocol` to define behaviors.
    * If a new VM backend is added (e.g., `HyperVBackend`), create a new class satisfying `VMBackend`. Do NOT modify callers with if/else chains on backend type.

### 6.3. LSP (Liskov Substitution Principle - 리스코프 치환 원칙)
* **Rule:** Implementations of a Protocol must be interchangeable without breaking correctness.
    * **Critical for Testing:** `FakeVM` used in tests MUST behave consistently with the real backend (same return shape, same exception types for the same failure).
    * **Contract:** If the Protocol documents raising `ValueError` for invalid input, every implementation must raise that, not return `None` or a different exception.

### 6.4. ISP (Interface Segregation Principle - 인터페이스 분리 원칙)
* **Rule:** Many client-specific interfaces are better than one general-purpose interface.
* **Python Application:** Avoid "God Protocols" or "God Classes" with 20 methods.
    * Split into smaller Protocols (e.g., `ActionRunner`, `LogReader`, `Screenshotter`) when clients only need a subset.

### 6.5. DIP (Dependency Inversion Principle - 의존성 역전 원칙) [KEY FOR RULE #5]
* **Rule:** High-level modules (business logic) must not depend on low-level modules (PowerShell / Hyper-V / sqlite details). Both should depend on abstractions (Protocols).
* **Enforcement:**
    * **Forbidden:** `def run_step(): subprocess.run(["powershell", ...])` (Direct dependency on OS calls).
    * **Required:** `def run_step(vm: VMBackend): vm.action(...)` (Dependency on Protocol).
    * *Why:* This allows injecting `FakeVM` during unit tests (Rule 5.3).

## 7. Advanced System Safety & Error Strategy (심화 시스템 안전)

**"The devil is in the details of Processes and Transactions."**
프로세스 경계와 트랜잭션 경계에서 발생하는 문제는 디버깅이 가장 어렵습니다. 이를 예방하기 위한 규칙입니다.

### 7.1. Error Architecture (에러 설계 전략)
* **Rule:** Strict distinction between **System Errors** and **Domain Errors**.
    * **Core:** Define explicit exception classes for domain failures (e.g., `class CatalogError(ValueError)`), and chain causes with `raise DomainError(...) from e`.
    * **Application/CLI:** Catch broadly only at the top level (`cli.main`, MCP tool boundary) for logging/user-facing messages, but **NEVER** use exceptions for normal control flow.
* **Context:** When wrapping OS/subprocess errors, preserve the exit code, stderr, and command for traceability.

### 7.2. Concurrency & Deadlock Prevention (동시성 및 교착상태 방지)
* **Rule:** Prefer **process isolation + DB transactions** or **queues** (`queue.Queue`, `multiprocessing`) over shared mutable state.
    * *Why:* Minimizes lock contention and eliminates deadlocks.
* **SQLite:** 여러 worker가 같은 `coverage.db`를 쓰므로 판정·선점은 반드시 `BEGIN IMMEDIATE` 트랜잭션 안에서 원자적으로 수행합니다. `busy_timeout`을 설정하고, 트랜잭션 안에서 VM 호출 등 느린 I/O를 하지 않습니다.
* **Locking Hierarchy:**
    * If `threading.Lock` is unavoidable, document the **Locking Order**.
    * *Forbidden:* Holding a lock (or an open write transaction) while calling an external process or a callback. (Reason: the callback might re-enter logic requiring the same lock -> Deadlock.)

### 7.3. External Process Boundaries (외부 프로세스 경계)
* **Rule:** Explicitly define "Who owns the resource".
    * **Python -> OS:** Every spawned process (PowerShell, MCP server, `claude`) must have a timeout and be terminated/waited on failure. 좀비 프로세스를 남기지 않습니다.
    * **OS -> Python:** Parse external output immediately into typed values (`dataclass`, `dict` with validated keys). 원시 문자열을 계층 사이로 넘기지 않습니다.

## 8. Commit Message Convention

**Rule:** All commit messages MUST strictly follow the prefix conventions listed below. This maintains Git history readability and clarifies the nature of changes.

* **[FEAT]** - New features
* **[FIX]** - Bug fixes
* **[BUILD]** - Build related changes
* **[CI]** - CI related changes
* **[DOCS]** - Documentation changes
* **[REFACT]** - Code refactoring (no functional changes, structural improvements)
* **[TEST]** - Test code changes (adding, modifying, deleting tests; no business logic changes)
* **[CHORE]** - Other changes (build scripts, package manager configs, etc.)
* **[COMMENT]** - Code comment updates (no functional logic changes)

* **NO CCI Links**: Do not include Cursor "cci" links (e.g., `(cci:7://...)`) in commit messages or documentation. Clean text only.
