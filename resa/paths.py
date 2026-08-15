"""Safe path helpers for report folders and Studio identifiers."""
from __future__ import annotations

import re
from pathlib import Path

ENGINE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CONFIG_HASH_RE = re.compile(r"^[A-Fa-f0-9]{8,16}$")
_OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def safe_run_dirname(engine: str, config_hash: str) -> str:
    """``<engine>_<hash>`` folder name, rejecting path-like engine names."""
    if not ENGINE_NAME_RE.match(engine):
        raise ValueError(
            f"engine name must be 1–64 letters, digits, '.', '_' or '-' "
            f"(got {engine!r})"
        )
    if not CONFIG_HASH_RE.match(config_hash):
        raise ValueError(f"invalid config hash: {config_hash!r}")
    return f"{engine}_{config_hash}"


def safe_output_name(name: str, *, fallback: str = "output") -> str:
    """Single path component for campaign / export directories."""
    raw = Path(str(name)).name.strip()
    if not raw or raw in {".", ".."}:
        raw = fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    if not cleaned or not _OUTPUT_NAME_RE.match(cleaned):
        cleaned = fallback
    return cleaned


def confined_relative(output: str, root: Path) -> Path:
    """Resolve a campaign artifact path under *root*; reject ``..`` / absolute."""
    p = Path(output)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(
            f"output path must be relative and stay under the campaign "
            f"directory (got {output!r})"
        )
    dest = (root / p).resolve()
    if not dest.is_relative_to(root.resolve()):
        raise ValueError(
            f"output path escapes the campaign directory: {output!r}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest
