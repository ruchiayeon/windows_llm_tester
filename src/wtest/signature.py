"""시나리오 → 구조 시그니처 (§6: 값 제거 · 정규화)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .catalog import ActionSpec, Catalog, CatalogError

_NUM = re.compile(r"\d+(?:\.\d+)?")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Signature:
    steps: tuple[str, ...]
    preconditions: frozenset[str]
    criteria: frozenset[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "steps": list(self.steps),
            "preconditions": sorted(self.preconditions),
            "criteria": sorted(self.criteria),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Signature:
        return cls(
            steps=tuple(data["steps"]),
            preconditions=frozenset(data["preconditions"]),
            criteria=frozenset(data["criteria"]),
        )

    @property
    def hash(self) -> str:
        canon = json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    @property
    def actions(self) -> set[str]:
        """역색인용 액션 이름 집합."""
        return {token.split(":", 1)[0].split("@", 1)[0] for token in self.steps}


def normalize_text(text: str) -> str:
    """사전조건·판정기준 문장 정규화: 소문자, 공백 정리, 숫자 값 제거."""
    return _WS.sub(" ", _NUM.sub("<n>", text.strip().lower()))


def value_class(spec: ActionSpec, param: str, value: Any) -> str:
    p = spec.params[param]
    if not isinstance(value, int) or isinstance(value, bool):
        return "invalid"
    if (p.min is not None and value < p.min) or (p.max is not None and value > p.max):
        return "invalid"
    if value in (p.min, p.max):
        return "boundary"
    return "normal"


def step_token(spec: ActionSpec, params: dict[str, Any], value_classes: bool) -> str:
    token = spec.name
    keep = [str(params[p]).strip().lower() for p in spec.signature_params if p in params]
    if keep:
        token += ":" + ":".join(keep)
    if value_classes:
        classes = [f"{p}={value_class(spec, p, params[p])}" for p in spec.class_params if p in params]
        if classes:
            token += "@" + ",".join(classes)
    return token


def extract_signature(scenario: dict[str, Any], catalog: Catalog, value_classes: bool = False) -> Signature:
    """scenario = {steps: [{action, params}], preconditions: [str], criteria: [str]}."""
    steps = scenario.get("steps") or []
    if not steps:
        raise CatalogError("시나리오에 단계(steps)가 최소 1개 있어야 함")
    tokens = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict) or "action" not in step:
            raise CatalogError(f"steps[{i}]: {{action, params}} 형식이어야 함")
        spec = catalog.get(step["action"])
        params = dict(step.get("params") or {})
        # 경계 클래스 판정을 위해 invalid 값은 허용하되, 타입·이름 외 위반은 막는다
        unknown = set(params) - set(spec.params)
        if unknown:
            raise CatalogError(f"steps[{i}] {spec.name}: 알 수 없는 파라미터 {sorted(unknown)}")
        tokens.append(step_token(spec, params, value_classes))
    return Signature(
        steps=tuple(tokens),
        preconditions=frozenset(normalize_text(t) for t in scenario.get("preconditions") or [] if t.strip()),
        criteria=frozenset(normalize_text(t) for t in scenario.get("criteria") or [] if t.strip()),
    )
