from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .config import EffectiveConfig, get
from .rng import DeterministicRNG


@dataclass
class DailyVolumePlan:
	base: int
	estimated: int


def _incident_boost(day_ctx, rng: DeterministicRNG, cfg: EffectiveConfig) -> float:
	if not (getattr(day_ctx, "outage_flag", False) or getattr(day_ctx, "app_issue_flag", False)):
		return 0.0
	lo = float(get(cfg, "volume.incident_boost_min", 0.25))
	hi = float(get(cfg, "volume.incident_boost_max", 0.40))
	r = rng.seed_for(("incident_boost", str(day_ctx.date)))
	return float(r.uniform(lo, hi))


def estimate_daily_volume(day_ctx, cfg: EffectiveConfig, rng: DeterministicRNG) -> DailyVolumePlan:
	is_weekend = getattr(day_ctx, "is_weekend", False)
	base = int(get(cfg, "volume.base_weekend" if is_weekend else "volume.base_weekday", 200))
	factor = float(getattr(day_ctx, "weekday_factor", 1.0))
	boost = _incident_boost(day_ctx, rng, cfg)
	# 5x reduction factor
	reduction = float(get(cfg, "meta.volume_reduction_factor", 0.2))
	estimated = int(round(base * factor * (1.0 + boost) * reduction))
	return DailyVolumePlan(base=base, estimated=max(0, estimated))


def split_by_agent(daily_volume: int, is_weekend: bool, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, int]:
	alloc = get(cfg, "agents.allocation.weekend" if is_weekend else "agents.allocation.weekday", {})
	r = rng.seed_for(("split_by_agent", is_weekend, daily_volume))
	return DeterministicRNG(0).multinomial_split(daily_volume, alloc, r)


def split_by_shift(agent: str, agent_volume: int, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, int]:
	profile = get(cfg, f"agents.members.{agent}.shifts", {})
	r = rng.seed_for(("split_by_shift", agent))
	return DeterministicRNG(0).multinomial_split(agent_volume, profile, r)


def split_by_time_buckets(shift_block: int, is_weekend: bool, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, int]:
	bucket_profile = get(cfg, "buckets.weekend" if is_weekend else "buckets.weekday", {})
	r = rng.seed_for(("split_by_time_buckets", is_weekend, shift_block))
	return DeterministicRNG(0).multinomial_split(shift_block, bucket_profile, r)
