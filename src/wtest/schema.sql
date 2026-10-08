-- coverage.db 스키마 (architecture.md §8). *_VEC 가상 테이블은 M5에서 추가한다.

CREATE TABLE IF NOT EXISTS run (
    run_id          TEXT PRIMARY KEY,
    agent_version   TEXT NOT NULL,
    profile_version TEXT,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS action (
    name          TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('action', 'query')),
    category      TEXT NOT NULL,
    params_schema TEXT NOT NULL,
    description   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test (
    chk_id         TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES run(run_id),
    agent_version  TEXT NOT NULL,
    worker_id      TEXT NOT NULL,
    vm_name        TEXT,
    mode           TEXT NOT NULL CHECK (mode IN ('fixed', 'explore')),
    title          TEXT,
    area           TEXT,
    scenario_json  TEXT NOT NULL,
    signature_json TEXT NOT NULL,
    signature_hash TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'claimed'
                   CHECK (status IN ('claimed', 'running', 'PASS', 'FAIL', 'INCONCLUSIVE')),
    retry_count    INTEGER NOT NULL DEFAULT 0,
    retry_of       TEXT REFERENCES test(chk_id),   -- 재시도·재현 대상
    superseded_by  TEXT REFERENCES test(chk_id),   -- 재시도로 대체되면 유사도 후보에서 빠진다
    summary        TEXT,
    claimed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_test_candidates ON test(agent_version, superseded_by);

-- 후보 축소용 역색인: 시나리오가 쓰는 액션 종류
CREATE TABLE IF NOT EXISTS test_action (
    chk_id TEXT NOT NULL REFERENCES test(chk_id),
    action TEXT NOT NULL REFERENCES action(name),
    PRIMARY KEY (action, chk_id)
);

CREATE TABLE IF NOT EXISTS step (
    step_id     INTEGER PRIMARY KEY,
    chk_id      TEXT NOT NULL REFERENCES test(chk_id),
    seq         INTEGER NOT NULL,
    action      TEXT NOT NULL REFERENCES action(name),
    params_json TEXT NOT NULL,
    observed    TEXT,
    result      TEXT NOT NULL CHECK (result IN ('ok', 'fail', 'skip')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (chk_id, seq)
);

CREATE TABLE IF NOT EXISTS proposal (
    proposal_id    INTEGER PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES run(run_id),
    worker_id      TEXT NOT NULL,
    signature_json TEXT NOT NULL,
    best_match_chk TEXT REFERENCES test(chk_id),
    score          REAL,
    decision       TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    approved_chk   TEXT REFERENCES test(chk_id),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS finding (
    finding_id   INTEGER PRIMARY KEY,
    chk_id       TEXT REFERENCES test(chk_id),
    worker_id    TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    summary      TEXT NOT NULL,
    evidence_ref TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS log_signature (
    log_id             INTEGER PRIMARY KEY,
    chk_id             TEXT NOT NULL REFERENCES test(chk_id),
    source             TEXT NOT NULL CHECK (source IN ('app', 'System', 'Application', 'kernel')),
    normalized_message TEXT NOT NULL,
    count              INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bundle (
    chk_id     TEXT PRIMARY KEY REFERENCES test(chk_id),
    zip_path   TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_section (
    section         TEXT PRIMARY KEY,
    profile_version TEXT NOT NULL,
    content         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doc_chunk (
    chunk_id INTEGER PRIMARY KEY,
    source   TEXT NOT NULL,
    content  TEXT NOT NULL
);

-- 세션 단위 이벤트 (탐색 포화 보고 등). Orchestrator가 transcript 없이도 상태를 알 수 있게 한다.
CREATE TABLE IF NOT EXISTS worker_event (
    event_id   INTEGER PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES run(run_id),
    worker_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- 커버리지: 별도 테이블 없이 영역 × 액션 집계 뷰 (§8). 대체된 재시도 원본은 제외한다.
CREATE VIEW IF NOT EXISTS coverage AS
SELECT t.agent_version,
       COALESCE(t.area, '(none)')                          AS area,
       ta.action                                           AS action,
       COUNT(*)                                            AS tests,
       SUM(t.status = 'PASS')                              AS pass,
       SUM(t.status = 'FAIL')                              AS fail,
       SUM(t.status = 'INCONCLUSIVE')                      AS inconclusive,
       SUM(t.status IN ('claimed', 'running'))             AS in_progress
FROM test t
JOIN test_action ta ON ta.chk_id = t.chk_id
WHERE t.superseded_by IS NULL
GROUP BY t.agent_version, area, ta.action;
