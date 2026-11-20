"""Load secrets into os.environ the same way everywhere: .env (local / Pi) and, on GitHub Actions,
the ALL_SECRETS JSON blob (every repository secret, so any secret name used in config.yaml works)."""

import json
import os
from pathlib import Path


def load_secrets() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass
    blob = os.environ.get("ALL_SECRETS")
    if blob:
        try:
            for k, v in json.loads(blob).items():
                if isinstance(v, str) and v and k not in os.environ:
                    os.environ[k] = v
        except ValueError:
            pass
