"""Data-dir resolution and jotd.toml config."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

POINTER_FILE = Path.home() / ".config" / "jotd" / "dir"
DEFAULT_DATA_DIR = Path.home() / "jotd"


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    """Precedence: --dir flag > $JOTD_DIR > cwd-that-is-a-jotd-dir > pointer file > ~/jotd.

    The cwd rule is what makes agent subprocesses Just Work: /organize and the
    pulse run with cwd = the data dir, so `jotd unprocessed` inside them needs
    no configuration.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("JOTD_DIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd()
    if (cwd / "jotd.toml").is_file():
        return cwd
    if POINTER_FILE.is_file():
        pointed = Path(POINTER_FILE.read_text(encoding="utf-8").strip()).expanduser()
        if pointed.is_dir():
            return pointed
    return DEFAULT_DATA_DIR


@dataclass
class PulseConfig:
    slots: dict[str, str] = field(
        default_factory=lambda: {"morning": "09:00", "midday": "13:30", "evening": "17:30"}
    )
    max_nudges_per_run: int = 3
    max_nudges_per_day: int = 6
    stale_after_days: int = 4
    snooze_days: int = 3
    model: str = "sonnet"
    channel: str = "macos"  # macos | stdout (slack/email are v0.3+ config hooks)


def load_config(data_dir: Path) -> PulseConfig:
    cfg = PulseConfig()
    toml_path = data_dir / "jotd.toml"
    if not toml_path.is_file():
        return cfg
    data = tomllib.loads(toml_path.read_text(encoding="utf-8")).get("pulse", {})
    for key in (
        "max_nudges_per_run",
        "max_nudges_per_day",
        "stale_after_days",
        "snooze_days",
        "model",
        "channel",
    ):
        if key in data:
            setattr(cfg, key, data[key])
    if "slots" in data:
        cfg.slots = dict(data["slots"])
    return cfg
