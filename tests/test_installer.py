import dataclasses
import hashlib

import pytest

from wtest.config import InstallerConfig
from wtest.installer import InstallerError, resolve_installer


@pytest.fixture
def with_installer(cfg, tmp_path):
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"fake installer")
    spec = InstallerConfig(key="agent-1", path=exe, sha256=hashlib.sha256(b"fake installer").hexdigest())
    return dataclasses.replace(cfg, installers={"agent-1": spec}), exe


def test_spec_resolve_installer_unknown_key_raises_error(with_installer):
    # Spec: 1. 허용 목록에 없는 키면 `InstallerError`를 발생시켜야 합니다.
    cfg, _ = with_installer
    with pytest.raises(InstallerError, match="등록되지 않은"):
        resolve_installer(cfg, "agent-2")


def test_spec_resolve_installer_missing_file_raises_error(with_installer):
    # Spec: 2. 파일이 없으면 `InstallerError`를 발생시켜야 합니다.
    cfg, exe = with_installer
    exe.unlink()
    with pytest.raises(InstallerError, match="없음"):
        resolve_installer(cfg, "agent-1")


def test_spec_resolve_installer_hash_mismatch_raises_error(with_installer):
    # Spec: 3. SHA-256이 등록 값과 다르면 `InstallerError`를 발생시켜야 합니다.
    cfg, exe = with_installer
    exe.write_bytes(b"tampered")
    with pytest.raises(InstallerError, match="해시 불일치"):
        resolve_installer(cfg, "agent-1")


def test_spec_resolve_installer_valid_returns_config(with_installer):
    # Spec: 4. 모두 통과하면 해당 `InstallerConfig`를 반환합니다.
    cfg, exe = with_installer
    assert resolve_installer(cfg, "agent-1").path == exe


def test_spec_config_loads_registered_installer(cfg):
    # 실제 wtest.toml의 등록 항목이 읽히는지 (파일 존재 여부와 무관)
    spec = cfg.installers["savex-1.16.0.19"]
    assert spec.args == () and spec.success_codes == (0, 3010)
    assert spec.path.name.endswith("v1.16.0.19.exe")
