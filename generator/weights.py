from __future__ import annotations

from typing import Dict

from .config import EffectiveConfig, get
from .rng import DeterministicRNG


def _apply_adjustments(base: Dict[str, float], adjustments: Dict[str, float]) -> Dict[str, float]:
	out = dict(base)
	for k, v in (adjustments or {}).items():
		out[k] = out.get(k, 0.0) + float(v)
	return out


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
	total = sum(max(0.0, v) for v in weights.values())
	if total <= 0.0:
		n = len(weights) or 1
		return {k: 1.0 / n for k in weights}
	return {k: max(0.0, v) / total for k, v in weights.items()}


def intent_weights(context, cfg: EffectiveConfig) -> Dict[str, float]:
	w = dict(get(cfg, "intents.base", {}) or {})
	# time_of_day
	w = _apply_adjustments(w, get(cfg, f"intents.time_of_day.{context.time_of_day_bucket}", {}))
	# agent
	w = _apply_adjustments(w, get(cfg, f"intents.agent.{context.agent_name}", {}))
	# segment
	w = _apply_adjustments(w, get(cfg, f"intents.segment.{context.customer_segment}", {}))
	# incident
	if context.outage_flag:
		w = _apply_adjustments(w, get(cfg, "intents.incident.outage", {}))
	if context.app_issue_flag:
		w = _apply_adjustments(w, get(cfg, "intents.incident.app_issue", {}))
	return _normalize(w)


def scenario_weights(context, intent: str, cfg: EffectiveConfig) -> Dict[str, float]:
	w = dict(get(cfg, "scenarios.base", {}) or {})
	w = _apply_adjustments(w, get(cfg, f"scenarios.agent.{context.agent_name}", {}))
	w = _apply_adjustments(w, get(cfg, f"scenarios.intent.{intent}", {}))
	if context.outage_flag:
		w = _apply_adjustments(w, get(cfg, "scenarios.incident.outage", {}))
	return _normalize(w)


def channel_weights(context, cfg: EffectiveConfig) -> Dict[str, float]:
	w = dict(get(cfg, "channels.base", {}) or {})
	w = _apply_adjustments(w, get(cfg, f"channels.time_of_day_adjustment.{context.time_of_day_bucket}", {}))
	return _normalize(w)


def device_weights(context, cfg: EffectiveConfig) -> Dict[str, float]:
	w = dict(get(cfg, "devices.base", {}) or {})
	over = get(cfg, f"devices.channel_overrides.{context.channel}", {})
	w = _apply_adjustments(w, over)
	return _normalize(w)


def product_weights(context, cfg: EffectiveConfig) -> Dict[str, float]:
	w = dict(get(cfg, "products.base", {}) or {})
	if context.outage_flag:
		w = _apply_adjustments(w, get(cfg, "products.outage_adjustment", {}))
	if getattr(context, "hour_lt_18", True):
		w = _apply_adjustments(w, get(cfg, "products.hour_lt_18_adjustment", {}))
	return _normalize(w)
