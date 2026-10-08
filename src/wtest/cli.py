"""wtest 명령행.

  wtest init                            coverage.db 스키마 생성 + 액션 카탈로그 적재
  wtest new-run RUN_ID --agent-version  run 등록
  wtest mcp                             wtest-mcp stdio 서버 (env로 세션 고정)
  wtest mcp-config --run --worker --vm  claude --mcp-config 용 JSON 출력
  wtest status [--run]                  테스트 · 커버리지 요약
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .catalog import Catalog
from .config import load_config
from .db import connect, create_run, init_db


def _conn(args: argparse.Namespace):
    cfg = load_config(args.config)
    return cfg, connect(cfg.db_path, cfg.busy_timeout_ms)


def cmd_init(args: argparse.Namespace) -> None:
    cfg, conn = _conn(args)
    init_db(conn, Catalog.load(cfg.catalog_path))
    print(f"initialized {cfg.db_path}")


def cmd_new_run(args: argparse.Namespace) -> None:
    _, conn = _conn(args)
    create_run(conn, args.run_id, args.agent_version, args.profile_version)
    print(f"run {args.run_id} (agent {args.agent_version})")


def cmd_mcp(args: argparse.Namespace) -> None:
    if args.config:
        os.environ["WTEST_CONFIG"] = str(Path(args.config).resolve())
    from .server import main

    main()


def cmd_mcp_config(args: argparse.Namespace) -> None:
    env = {
        "WTEST_CONFIG": str(Path(args.config or "wtest.toml").resolve()),
        "WTEST_RUN": args.run,
        "WTEST_WORKER": args.worker,
        "WTEST_VM": args.vm,
        "WTEST_BACKEND": args.backend,
    }
    if args.chk:
        env["WTEST_CHK"] = args.chk
    if args.db:
        env["WTEST_DB"] = str(Path(args.db).resolve())
    config = {"mcpServers": {"wtest": {"command": sys.executable, "args": ["-m", "wtest", "mcp"], "env": env}}}
    print(json.dumps(config, ensure_ascii=False, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    _, conn = _conn(args)
    where, params = ("WHERE run_id = ?", (args.run,)) if args.run else ("", ())
    for r in conn.execute(f"SELECT chk_id, worker_id, status, retry_count, title FROM test {where} "
                          "ORDER BY chk_id", params):
        print(f"{r['chk_id']}  {r['status']:<12} {r['worker_id']:<10} retry={r['retry_count']}  {r['title']}")
    for r in conn.execute(f"SELECT decision, COUNT(*) n FROM proposal {where} GROUP BY decision", params):
        print(f"proposals {r['decision']}: {r['n']}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="wtest")
    p.add_argument("--config", help="wtest.toml 경로 (기본: WTEST_CONFIG 또는 ./wtest.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    s = sub.add_parser("new-run")
    s.add_argument("run_id")
    s.add_argument("--agent-version", required=True)
    s.add_argument("--profile-version")
    s.set_defaults(fn=cmd_new_run)

    sub.add_parser("mcp").set_defaults(fn=cmd_mcp)

    s = sub.add_parser("mcp-config")
    s.add_argument("--run", required=True)
    s.add_argument("--worker", required=True)
    s.add_argument("--vm", required=True)
    s.add_argument("--chk")
    s.add_argument("--db", help="coverage.db 경로 (기본: 설정 파일 값)")
    s.add_argument("--backend", default="fake", choices=["fake", "hyperv"])
    s.set_defaults(fn=cmd_mcp_config)

    s = sub.add_parser("status")
    s.add_argument("--run")
    s.set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    args.fn(args)
