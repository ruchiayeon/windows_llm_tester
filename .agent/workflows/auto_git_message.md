---
description: 스테이징된 변경사항을 분석해 Git Message 생성
---

# Git Commit Message Generation Protocol (v2.1 - Copy-Paste Friendly)

> **⚠️ MASTER RULE: ZERO-CONTEXT & STRICT SYNTAX**
> **1. MEMORY RESET (Context Isolation):**
> * **IGNORE** all previous conversation history, user preferences, or "learned" context outside of this immediate prompt.
> * **SOURCE OF TRUTH:** You must execute instructions **ONLY** based on the logic defined in this document. Do not hallucinate rules not written here.
> 
> 
> **2. LANGUAGE ENFORCEMENT:**
> * **STRICTLY KOREAN (한국어):** All output (Subject, Body, Explanations) must be written in **Korean**.
> * **Exception:** English is permitted *only* for variable names, file paths, or reserved keywords (e.g., `git`, `const`).
> 
> 
> **3. NO CCI / HYPERLINKS (ZERO TOLERANCE):**
> * **ABSOLUTE BAN:** 어떠한 경우에도 `cci:` 링크, 하이퍼링크, 또는 파일 추적용 대괄호 링크(`[file.py](...)`)를 생성하지 않습니다. 발견 시 유저는 매우 실망할 것입니다.
> * **CLEAN TEXT ONLY:** 모든 출력은 순수한 텍스트와 표준 마크다운 불렛 포인트만 사용합니다.
> 
> 

---

## 1. Guiding Principles (Strict Constraints)

Before proceeding, you must adhere to these absolute rules:

1. **Read-Only Staging:** You are strictly forbidden from running `git add .` or modifying the staging area.
2. **Context Isolation:** Analyze *only* what is currently in the staging area (`git diff --cached`).
3. **Markdown Code Block Output (No Files):**
* **CRITICAL:** The final commit message must be displayed **INSIDE a Markdown Code Block** (wrapped in ```markdown ... ```).
* **Do NOT** output the message as plain chat text.
* **STRICT PROHIBITION:** You are strictly forbidden from creating actual downloadable files (e.g., do NOT create `.md`, `.txt` files). Just show the code block.



---

## 2. Execution Workflow

### Step 0: Protocol Handshake (Initialization)

* **Action:** Before executing any git commands, you must internalize the "Master Rules" (especially the **NO HYPERLINKS**, **STRICT KOREAN**, and **CODE BLOCK OUTPUT** constraints).
* **Output:** Begin your response with the following initialization log to confirm rule ingestion:
> `✅ Git Commit Protocol v2.1 Loaded: Context Reset & Strict Copy-Paste Mode Active.`



### Step 1: Check Staged Files

* **Action:** Run `git diff --name-only --cached` to identify staged files.
* **Condition:** If the output is empty:
* Inform the user: "스테이징된 변경사항이 없습니다."
* **Stop** the workflow immediately.



### Step 2: Analyze Changes

* **Action:** Run `git diff --cached` to retrieve the content of the changes.
* **Analysis:** Examine the diff to understand:
* **What** changed (Feature, Bugfix, Refactor, etc.)?
* **Why** it changed (Context)?
* **Safety & Security Check:**
* **Subprocess/Shell:** If `subprocess` or PowerShell calls are modified, ensure no `shell=True` with interpolated input, and that `timeout` and return-code handling are present.
* **Secrets:** Scan for hardcoded API keys or credentials. If found, **HALT** and warn the user.





### Step 3: Select Commit Prefix

Select **strictly one** prefix from the list below that best describes the change:

* **[FEAT]** - New features (새로운 기능)
* **[FIX]** - Bug fixes (버그 수정)
* **[BUILD]** - Build related changes (빌드 관련)
* **[CI]** - CI related changes (CI 설정)
* **[DOCS]** - Documentation changes (문서 수정)
* **[REFACT]** - Code refactoring (기능 변경 없는 코드 구조 개선)
* **[TEST]** - Test code changes (테스트 코드 추가/수정)
* **[CHORE]** - Other changes (패키지 매니저, 스크립트 등 자잘한 수정)
* **[COMMENT]** - Code comment updates (주석 수정)

### Step 4: Style Guidelines (STRICT KOREAN)

Ensure the generated message adheres to the following rules:

* **Subject Line:** **Korean (한국어)**, Max 50 chars, No period at end.
* **Body:** **Korean (한국어)**.
* **Tone:** Technical, Imperative (e.g., "추가" not "추가함", "수정" not "수정했음").

### Step 5: Generate Commit Message (Final Output)

**CRITICAL DISPLAY RULE:**
You must render the final result inside a **Single Markdown Code Block**. Do not print it as plain text.

**Template (Inside Code Block):**

```markdown
[PREFIX] Subject Line (Must be in Korean)

- Simple Title(File/Module Name): Description of the change in Korean.
  (Explain *Why* and *How*, and mention safety verification if relevant.)

```