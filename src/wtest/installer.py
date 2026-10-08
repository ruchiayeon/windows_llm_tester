"""테스트 대상 설치 파일 검증.

VM으로 복사하기 전에 호스트에서 파일 존재와 SHA-256을 확인한다.
실제 복사·실행(PowerShell Direct)은 M2에서 vm.py의 Hyper-V 백엔드가 맡는다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .config import Config, InstallerConfig

_CHUNK = 1024 * 1024


class InstallerError(ValueError):
    """등록되지 않았거나, 없거나, 해시가 다른 설치 파일."""


def sha256_file(path: Path) -> str:
    """파일 SHA-256을 1MB씩 읽어 계산한다 (큰 설치 파일도 메모리에 다 올리지 않음)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def resolve_installer(cfg: Config, key: str) -> InstallerConfig:
    """키로 설치 파일을 찾고 검증한다.

    1. 허용 목록에 없는 키면 `InstallerError`를 발생시켜야 합니다.
    2. 파일이 없으면 `InstallerError`를 발생시켜야 합니다.
    3. SHA-256이 등록 값과 다르면 `InstallerError`를 발생시켜야 합니다.
    4. 모두 통과하면 해당 `InstallerConfig`를 반환합니다.
    """
    spec = cfg.installers.get(key)
    if spec is None:
        raise InstallerError(f"등록되지 않은 설치 파일 '{key}'. 허용: {sorted(cfg.installers)}")
    if not spec.path.is_file():
        raise InstallerError(f"설치 파일 없음: {spec.path}")
    actual = sha256_file(spec.path)
    if actual != spec.sha256:
        raise InstallerError(f"'{key}' 해시 불일치: 등록 {spec.sha256}, 실제 {actual}")
    return spec
