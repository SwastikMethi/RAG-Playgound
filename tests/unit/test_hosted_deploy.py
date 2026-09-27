import subprocess
import pytest
from deploy import backup


def test_bad_hosted_settings_do_not_echo_secret_inputs():
    from app.settings import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as caught:
        Settings(deployment="hosted", public_origin="http://wrong.example", master_key="private-master-value",
                 turnstile_secret_key="private-turnstile-value", _env_file=None)
    assert "input_value" not in str(caught.value)


def test_backup_only_prunes_owned_successful_snapshots():
    base = {"volume-id": "volume-a", "freeform-tags": backup.TAG, "lifecycle-state": "AVAILABLE", "time-created": "2026-09-27"}
    rows = [dict(base, id="owned"), dict(base, id="foreign", **{"volume-id": "volume-b"}),
            dict(base, id="untagged", **{"freeform-tags": {}}),
            dict(base, id="pending", **{"freeform-tags": {"rag-playground": "pending-v1"}})]
    assert [row["id"] for row in backup.owned_backups(rows, "volume-a")] == ["owned"]


def test_failed_backup_restarts_without_certifying_or_deleting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    monkeypatch.setattr(backup, "DATA", tmp_path / "data", raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / ".env.production").write_text("OCI_DATA_VOLUME_ID=ocid1.volume.test\nOCI_COMPARTMENT_ID=ocid1.compartment.test\n")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/profiles.yaml").write_text("profiles: []")
    commands = []
    def run(command, **kwargs):
        commands.append(command)
    monkeypatch.setattr(backup.subprocess, "run", run)
    monkeypatch.setattr(backup.subprocess, "check_output", lambda *args, **kwargs: "commit")
    monkeypatch.setattr(backup.os, "sync", lambda: None)
    def oci(*args):
        commands.append(list(args))
        if "create" in args:
            assert 'pending-v1' in args[args.index("--freeform-tags")+1]
            raise subprocess.CalledProcessError(1, "oci")
        return []
    monkeypatch.setattr(backup, "oci", oci)
    with pytest.raises(subprocess.CalledProcessError):
        backup.backup()
    assert commands[-1][1:] == ["up", "-d"]
    assert not any("delete" in command or "update" in command for command in commands)
