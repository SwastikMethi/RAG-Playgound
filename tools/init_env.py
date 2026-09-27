"""Create private local settings once; never overwrite an existing environment."""

from pathlib import Path
import os
from cryptography.fernet import Fernet

path = Path(".env")
value = Path(".env.example").read_text()
value = value.replace("RAG_MASTER_KEY=\n", f"RAG_MASTER_KEY={Fernet.generate_key().decode()}\n")
try:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
        output.write(value)
    print("Created private .env. Set OPENAI_API_KEY locally, then start the services.")
except FileExistsError:
    print(".env already exists; no settings were changed.")
