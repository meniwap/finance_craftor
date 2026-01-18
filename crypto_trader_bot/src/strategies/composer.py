from __future__ import annotations

from typing import Any

from src.core.config import _deep_merge


def compose_strategy_config(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Build a strategy config from UI selections.
    Expected payload:
      - mode: "all" | "any"
      - selections: list of strategy configs:
          {name, indicators?, signals?, sizing?, exits?}
    Returns a StrategyConfig-like dict.
    """
    selections = payload.get("selections") or []
    if not isinstance(selections, list) or not selections:
        raise ValueError("selections must be a non-empty list")

    if len(selections) == 1:
        return selections[0]

    mode = str(payload.get("mode", "all"))
    # Composite must carry indicator config so the engine can compute values.
    merged_indicators: dict[str, Any] = {}
    for s in selections:
        ind = s.get("indicators") or {}
        if isinstance(ind, dict):
            merged_indicators = _deep_merge(merged_indicators, ind)

    # Use first child's sizing/exits as the composite defaults (UI sends consistent children).
    first = selections[0] if selections else {}
    return {
        "name": "composite",
        "signals": {
            "composite": {
                "mode": mode,
                "children": selections,
            }
        },
        "indicators": merged_indicators,
        "sizing": dict(first.get("sizing") or {}),
        "exits": dict(first.get("exits") or {}),
    }
