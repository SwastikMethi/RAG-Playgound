"""Create fresh hosted secrets locally; never prints them or overwrites an existing file."""
import base64
import getpass
import os
from pathlib import Path
import re
import secrets


def main():
    destination = Path(__file__).resolve().parents[1] / ".env.production"
    if destination.exists():
        raise SystemExit(".env.production already exists. Preserve it; do not regenerate the master key.")
    domain = input("DuckDNS hostname (name.duckdns.org): ").strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.duckdns\.org", domain):
        raise SystemExit("Enter a single DuckDNS hostname without a URL or path.")
    email = input("TLS certificate contact email: ").strip()
    site = input("Turnstile site key: ").strip()
    secret = getpass.getpass("Turnstile secret key: ").strip()
    if not re.fullmatch(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", email):
        raise SystemExit("Enter a valid contact email.")
    if not all(re.fullmatch(r"[a-zA-Z0-9_-]{10,200}", value) for value in [site, secret]):
        raise SystemExit("Enter the Turnstile keys from the widget settings.")
    values = dict(RAG_DOMAIN=domain, ACME_EMAIL=email, RAG_TURNSTILE_SITE_KEY=site,
        RAG_TURNSTILE_SECRET_KEY=secret, RAG_MASTER_KEY=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        POSTGRES_PASSWORD=secrets.token_hex(32), OCI_DATA_VOLUME_ID="", OCI_COMPARTMENT_ID="",
        RAG_DATABASE_HOST_ALLOWLIST="[]", RAG_DATABASE_RELATION_ALLOWLIST="[]")
    with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        file.write("# Secret: keep an encrypted copy outside the VM. Never regenerate after storing credentials.\n")
        file.writelines(f"{key}={value}\n" for key, value in values.items())
    print("Created .env.production (0600). Save an encrypted off-VM copy before launch.")


if __name__ == "__main__":
    main()
