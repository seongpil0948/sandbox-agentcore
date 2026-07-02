from __future__ import annotations

import os


def resolve_optional_env(primary: str, *aliases: str) -> str | None:
    for key in (primary, *aliases):
        value = os.getenv(key)
        if value:
            return value
    return None


def resolve_required_env(primary: str, *aliases: str) -> str:
    value = resolve_optional_env(primary, *aliases)
    if value:
        return value

    joined = ", ".join((primary, *aliases))
    raise EnvironmentError(f"missing required environment variable: one of {joined}")
