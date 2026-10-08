"""구조 유사도 (§6).

score = w_steps × 단계 순서 유사도(1 - 편집거리/최대길이)
      + w_pre   × 사전조건 Jaccard
      + w_crit  × 판정기준 Jaccard

경계 규칙: 두 집합이 모두 비면 Jaccard = 1, 두 단계 목록이 모두 비면 순서 유사도 = 1.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from typing import Any

from .config import SimilarityConfig
from .signature import Signature


def levenshtein(a: Sequence[str], b: Sequence[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def sequence_similarity(a: Sequence[str], b: Sequence[str]) -> float:
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - levenshtein(a, b) / longest


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def score(a: Signature, b: Signature, cfg: SimilarityConfig) -> float:
    raw = (
        cfg.w_steps * sequence_similarity(a.steps, b.steps)
        + cfg.w_preconditions * jaccard(a.preconditions, b.preconditions)
        + cfg.w_criteria * jaccard(a.criteria, b.criteria)
    )
    # 부동소수 오차로 정확히 0.7인 점수가 0.6999…가 되어 임계값을 비켜가지 않게 한다
    return round(raw, 9)


def diff(proposed: Signature, existing: Signature) -> dict[str, Any]:
    """거절 응답용 diff. Claude가 '구조를 어떻게 바꿔야 하는지' 보도록 기존 대비 차이를 준다."""
    step_diff = [
        line
        for line in difflib.ndiff(list(existing.steps), list(proposed.steps))
        if line[:1] in "+- "
    ]
    return {
        "steps": step_diff,  # '- ' 기존에만, '+ ' 제안에만, '  ' 공통
        "preconditions": {
            "only_proposed": sorted(proposed.preconditions - existing.preconditions),
            "only_existing": sorted(existing.preconditions - proposed.preconditions),
        },
        "criteria": {
            "only_proposed": sorted(proposed.criteria - existing.criteria),
            "only_existing": sorted(existing.criteria - proposed.criteria),
        },
    }
