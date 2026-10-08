from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from wtest.catalog import Catalog
from wtest.config import Config, load_config
from wtest.db import connect, create_run, init_db
from wtest.session import Session
from wtest.vm import FakeVM, VMGuard

ROOT = Path(__file__).resolve().parents[1]
RUN = "run-test"
AGENT = "1.0.0"


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return dataclasses.replace(load_config(ROOT / "wtest.toml"), db_path=tmp_path / "coverage.db")


@pytest.fixture
def catalog(cfg: Config) -> Catalog:
    return Catalog.load(cfg.catalog_path)


@pytest.fixture
def conn(cfg: Config, catalog: Catalog):
    c = connect(cfg.db_path, cfg.busy_timeout_ms)
    init_db(c, catalog)
    create_run(c, RUN, AGENT)
    yield c
    c.close()


@pytest.fixture
def make_session(cfg, catalog, conn):
    def make(worker: str = "w1", vm: str = "run-01", chk: str | None = None) -> Session:
        return Session(cfg, catalog, conn, VMGuard(FakeVM(vm), catalog), run_id=RUN, worker_id=worker, chk_id=chk)

    return make
