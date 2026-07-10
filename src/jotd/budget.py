"""The interruption budget — enforced in code, not prompts.

The pulse agent is told the budget so its reasoning reads coherently, but
nothing it says can exceed what this module allows: the runner pre-filters
what the model may even consider, then hard-truncates what it returns.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from jotd import pulselog
from jotd.config import PulseConfig


def remaining_budget(cfg: PulseConfig, events: list[dict[str, Any]], today: date) -> int:
    sent_today = pulselog.nudges_on_day(events, today)
    return max(0, min(cfg.max_nudges_per_run, cfg.max_nudges_per_day - sent_today))


def eligible_loops(loops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Loops the model is allowed to see. derive already folded done/snoozed/
    silenced status, so eligibility is simply status == open — silenced loops
    never reach the packet, which makes re-nudging them structurally impossible."""
    return [lp for lp in loops if lp["status"] == "open"]


def enforce(
    nudges: list[dict[str, Any]],
    eligible_ids: set[str],
    budget: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Hard-truncate model output. Returns (kept, runner_suppressed) where each
    runner_suppressed entry carries the reason the runner rejected it."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in nudges:
        loop_id = n.get("loop_id", "")
        if loop_id not in eligible_ids:
            rejected.append({**n, "reason": "runner: unknown or ineligible loop id"})
        elif loop_id in seen:
            rejected.append({**n, "reason": "runner: duplicate nudge for one loop"})
        elif len(kept) >= budget:
            rejected.append({**n, "reason": "runner: over budget"})
        else:
            kept.append(n)
            seen.add(loop_id)
    return kept, rejected
