"""wtest.toml 로딩. 상대 경로는 설정 파일 위치 기준으로 해석한다."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SimilarityConfig:
    threshold: float = 0.7
    w_steps: float = 0.6
    w_preconditions: float = 0.2
    w_criteria: float = 0.2
    value_classes: bool = False


@dataclass(frozen=True)
class PolicyConfig:
    max_retries: int = 2
    hint_after_rejections: int = 3
    saturate_after_rejections: int = 5
    similar_top_k: int = 3
    hint_limit: int = 5


@dataclass(frozen=True)
class Config:
    db_path: Path
    busy_timeout_ms: int
    catalog_path: Path
    similarity: SimilarityConfig
    policy: PolicyConfig


def load_config(path: str | Path | None = None) -> Config:
    """설정을 읽는다. 경로가 없으면 WTEST_CONFIG, 그다음 ./wtest.toml 순으로 찾는다."""
    path = Path(path or os.environ.get("WTEST_CONFIG") or "wtest.toml").resolve()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent

    db = raw.get("db", {})
    db_path = Path(os.environ.get("WTEST_DB") or db.get("path", "data/coverage.db"))
    catalog_path = Path(raw.get("catalog", {}).get("path", "catalog/actions.toml"))

    return Config(
        db_path=db_path if db_path.is_absolute() else base / db_path,
        busy_timeout_ms=int(db.get("busy_timeout_ms", 30000)),
        catalog_path=catalog_path if catalog_path.is_absolute() else base / catalog_path,
        similarity=SimilarityConfig(**raw.get("similarity", {})),
        policy=PolicyConfig(**raw.get("policy", {})),
    )
