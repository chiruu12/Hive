"""Shared subprocess environment helpers (secret scrubbing)."""

from __future__ import annotations

import os
import re

# Credential-looking keys never passed to untrusted child processes unless the
# caller explicitly opts into full inheritance. Matches ShellToolkit policy.
_SECRET_ENV = re.compile(
    r"(_API_KEY|_KEY|_TOKEN|_SECRET|_SECRETS|_PASSWORD|_PASSWD|_PASS|_PWD"
    r"|_CREDENTIAL|_CREDENTIALS|_AUTH|_DSN|_PRIVATE_KEY|_ACCESS_KEY|_SESSION_TOKEN)$"
    r"|^(ANTHROPIC|OPENAI|GROQ|FIREWORKS|OPENROUTER|DEEPGRAM|AWS|AZURE|GCP|GOOGLE"
    r"|GITHUB|GITLAB|GH|SSH|STRIPE|TWILIO|SLACK|HF|HUGGINGFACE|NPM|DOCKER|VAULT|PG)_"
    r"|^(DATABASE_URL|DATABASE_URI|DB_URL|DB_URI|REDIS_URL|MONGODB_URI|MONGO_URL"
    r"|PGPASSWORD|PGUSER|SECRET_KEY|PRIVATE_KEY|ACCESS_TOKEN|SESSION_SECRET)$"
)


def scrub_secrets_from_env(
    *,
    workspace: str | None = None,
    tmp_dir: str | None = None,
) -> dict[str, str]:
    """Return a copy of ``os.environ`` with credential-like keys removed."""
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    if workspace is not None:
        env["HOME"] = workspace
    if tmp_dir is not None:
        env["TMPDIR"] = tmp_dir
        env["TEMP"] = tmp_dir
        env["TMP"] = tmp_dir
    return env
