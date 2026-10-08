"""액션 카탈로그. 카탈로그에 없는 액션·파라미터는 실행도, 시나리오 제안도 할 수 없다."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TYPES: dict[str, type | tuple[type, ...]] = {"str": str, "int": int, "bool": bool}


class CatalogError(ValueError):
    """카탈로그 위반 (없는 액션, 잘못된 파라미터)."""


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str
    required: bool = False
    min: int | None = None
    max: int | None = None


@dataclass(frozen=True)
class ActionSpec:
    name: str
    kind: str  # action | query
    category: str
    description: str
    params: dict[str, ParamSpec] = field(default_factory=dict)
    signature_params: tuple[str, ...] = ()
    class_params: tuple[str, ...] = ()

    def params_schema(self) -> dict[str, Any]:
        return {
            p.name: {k: v for k, v in vars(p).items() if k != "name" and v is not None}
            for p in self.params.values()
        }

    def validate(self, params: dict[str, Any] | None) -> dict[str, Any]:
        params = dict(params or {})
        unknown = set(params) - set(self.params)
        if unknown:
            raise CatalogError(f"{self.name}: 알 수 없는 파라미터 {sorted(unknown)}")
        for spec in self.params.values():
            if spec.name not in params:
                if spec.required:
                    raise CatalogError(f"{self.name}: 필수 파라미터 '{spec.name}' 누락")
                continue
            value = params[spec.name]
            expected = _TYPES[spec.type]
            # bool은 int의 하위 타입이므로 int 자리에 bool이 오면 거부한다
            if not isinstance(value, expected) or (spec.type == "int" and isinstance(value, bool)):
                raise CatalogError(f"{self.name}: '{spec.name}'는 {spec.type} 타입이어야 함")
        return params


class Catalog:
    def __init__(self, actions: dict[str, ActionSpec]):
        self.actions = actions

    @classmethod
    def load(cls, path: str | Path) -> Catalog:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        actions = {}
        for name, body in raw.items():
            params = {
                pname: ParamSpec(name=pname, **pspec)
                for pname, pspec in body.get("params", {}).items()
            }
            actions[name] = ActionSpec(
                name=name,
                kind=body["kind"],
                category=body["category"],
                description=body.get("description", ""),
                params=params,
                signature_params=tuple(body.get("signature_params", ())),
                class_params=tuple(body.get("class_params", ())),
            )
        return cls(actions)

    def get(self, name: str, kind: str | None = None) -> ActionSpec:
        spec = self.actions.get(name)
        if spec is None or (kind is not None and spec.kind != kind):
            allowed = sorted(n for n, s in self.actions.items() if kind is None or s.kind == kind)
            raise CatalogError(f"카탈로그에 없는 {kind or '액션'}: '{name}'. 허용: {allowed}")
        return spec

    def names(self, kind: str | None = None) -> list[str]:
        return sorted(n for n, s in self.actions.items() if kind is None or s.kind == kind)
