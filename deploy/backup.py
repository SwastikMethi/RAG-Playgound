"""Quiesce the stack, take an OCI volume backup, restart, then retain three owned backups.

Run on the VM with OCI CLI instance-principal access. No cloud resource is provisioned.
"""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/srv/ragplayground")
TAG = {"rag-playground": "consistent-v1"}


def oci(*args):
    result = subprocess.run(["oci", "--auth", "instance_principal", *args],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)["data"] if result.stdout.strip() else None


def owned_backups(rows, volume):
    return sorted((row for row in rows if row["volume-id"] == volume
                   and row.get("freeform-tags", {}).get("rag-playground") == TAG["rag-playground"]
                   and row["lifecycle-state"] == "AVAILABLE"), key=lambda row: row["time-created"], reverse=True)


def backup():
    os.chdir(ROOT)
    values = dict(line.split("=", 1) for line in (ROOT / ".env.production").read_text().splitlines()
                  if line and not line.startswith("#"))
    volume, compartment = values.get("OCI_DATA_VOLUME_ID", ""), values.get("OCI_COMPARTMENT_ID", "")
    if not volume.startswith("ocid1.volume.") or not compartment.startswith("ocid1.compartment."):
        raise SystemExit("Set OCI_DATA_VOLUME_ID and OCI_COMPARTMENT_ID in .env.production first.")
    compose = [str(ROOT / "deploy/compose.sh")]
    # The wrapper checks the mount and secret-file permissions before touching services.
    subprocess.run([*compose, "config", "--quiet"], check=True)
    listed = oci("bv", "backup", "list", "--compartment-id", compartment, "--all")
    boot = oci("bv", "boot-volume-backup", "list", "--compartment-id", compartment, "--all")
    if sum(row["lifecycle-state"] != "TERMINATED" for row in listed + boot) >= 5:
        raise SystemExit("No free backup slot remains in this compartment. Review backups in the console; nothing was deleted.")
    restore = DATA / "restore"
    restore.mkdir(mode=0o700, exist_ok=True)
    shutil.copy2(ROOT / ".env.production", restore / ".env.production")
    shutil.copy2(ROOT / "deploy/profiles.yaml", restore / "profiles.yaml")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    (restore / "release.json").write_text(json.dumps({"commit": commit, "created_at": datetime.now(timezone.utc).isoformat()}))
    try:
        subprocess.run([*compose, "stop", "--timeout", "120"], check=True)
        os.sync()
        created = oci("bv", "backup", "create", "--volume-id", volume, "--type", "INCREMENTAL",
                      "--display-name", "rag-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                      "--freeform-tags", json.dumps({"rag-playground": "pending-v1"}),
                      "--wait-for-state", "AVAILABLE", "--max-wait-seconds", "1800")
        if created["lifecycle-state"] != "AVAILABLE":
            raise RuntimeError("The new backup is not available; existing backups were retained.")
        oci("bv", "backup", "update", "--volume-backup-id", created["id"], "--freeform-tags", json.dumps(TAG), "--force")
    finally:
        subprocess.run([*compose, "up", "-d"], check=True)
    # Delete only this application's available backups on this exact volume, after success.
    rows = owned_backups(oci("bv", "backup", "list", "--compartment-id", compartment, "--all"), volume)
    for row in rows[3:]:
        oci("bv", "backup", "delete", "--volume-backup-id", row["id"], "--force")
    print("Consistent backup available; stack restarted; three latest application backups retained.")


if __name__ == "__main__":
    os.umask(0o077)
    with (ROOT / ".backup.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            backup()
        except subprocess.CalledProcessError:
            raise SystemExit("A backup command failed. Check OCI/service status; no command credentials were logged.") from None
