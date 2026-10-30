from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


API_KEY_ENV = "DEEPSEEK_API_KEY"


def _env_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / ".env"


def _decode_value(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, str) else ""
        except json.JSONDecodeError:
            return ""
    return value


def load_project_environment(project_root: str | Path) -> bool:
    """Load the app-owned API key file into this process environment."""
    path = _env_path(project_root)
    if not path.is_file():
        return False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == API_KEY_ENV:
            key = _decode_value(value)
            if key:
                os.environ[API_KEY_ENV] = key
                return True
    return False


def has_api_key() -> bool:
    return bool(os.getenv(API_KEY_ENV, "").strip())


def save_project_api_key(project_root: str | Path, api_key: str) -> None:
    """Atomically persist a user-entered key without embedding it in code."""
    key = api_key.strip()
    if not key:
        raise ValueError("API Key 不能为空")
    path = _env_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if path.is_file():
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith(f"{API_KEY_ENV}=")
        ]
    lines.append(f"{API_KEY_ENV}={json.dumps(key, ensure_ascii=False)}")
    content = "\n".join(lines).rstrip() + "\n"
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".env.",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    os.environ[API_KEY_ENV] = key

