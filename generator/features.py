from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict

import numpy as np

from .config import EffectiveConfig, get
from .rng import DeterministicRNG
from .weights import intent_weights, scenario_weights, channel_weights, device_weights, product_weights


@dataclass
class Context:
	date: date
	weekday: str
	time_of_day_bucket: str
	agent_name: str
	team: str
	agent_shift: str
	customer_segment: str
	channel: str
	region: str
	language: str
	device_type: str
	outage_flag: bool
	app_issue_flag: bool
	premium_wait_peak: bool
	call_rng: np.random.Generator
	hour_lt_18: bool


AGENT_NAMES = ["Monika_Mueller","Lukas_Schmidt","Anna_Ziegler","Peter_Keller","Jasmin_Caggiano","Heidi_Vogt","Marco_Fischer","Laura_Brunner","Karin_Herzog","Sven_Meier","Nina_Weber","Paul_Huber"]
TEAMS = ["Team A","Team B","Team C"]
SHIFTS = ["Early","Mid","Late"]
BUCKETS = ["Night","Morning","Afternoon","Evening"]
CHANNELS = ["voice","text"]
LANGS = ["DE","IT","FR"]
REGIONS = ["ZH","BE","GE","VD","TI"]
DEVICES = ["iOS","Android","Desktop"]
SEGMENTS = ["Premium","Standard"]


def _sample_from_weights(rng: DeterministicRNG, mapping: Dict[str, float], key: tuple) -> str:
	r = rng.seed_for(key)
	items = list(mapping.keys())
	probs = np.array([float(mapping[k]) for k in items], dtype=float)
	probs = np.clip(probs, 0.0, None)
	t = probs.sum()
	if t <= 0 or not np.isfinite(t):
		probs = np.ones(len(items), dtype=float) / max(1, len(items))
	else:
		probs = probs / t
	idx = r.choice(len(items), p=probs)
	return items[int(idx)]


def sample_customer_segment(ctx: Context, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, Any]:
	weights = get(cfg, "segments.customer", {"Premium": 0.25, "Standard": 0.75})
	segment = _sample_from_weights(rng, weights, ("segment", ctx.date.isoformat(), ctx.agent_name))
	return {"customer_segment": segment}


def sample_channel(ctx: Context, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, Any]:
	w = channel_weights(ctx, cfg)
	ch = _sample_from_weights(rng, w, ("channel", ctx.time_of_day_bucket, ctx.agent_name))
	return {"channel": ch}


def sample_geo_language_device(ctx: Context, cfg: EffectiveConfig, rng: DeterministicRNG, segment: str) -> Dict[str, Any]:
	region = _sample_from_weights(rng, get(cfg, "geo.region", {}), ("region", ctx.date.isoformat()))
	lang_base = dict(get(cfg, "geo.language", {}))
	if segment == "Premium":
		bias = get(cfg, "geo.premium_language_bias", {})
		for k, v in (bias or {}).items():
			lang_base[k] = max(0.0, float(lang_base.get(k, 0.0)) + float(v))
	language = _sample_from_weights(rng, lang_base, ("language", ctx.date.isoformat()))
	dev = _sample_from_weights(rng, device_weights(ctx, cfg), ("device", ctx.channel))
	return {"region": region, "language": language, "device_type": dev}


def sample_intent(ctx: Context, cfg: EffectiveConfig, rng: DeterministicRNG) -> str | list[str]:
	"""Sample 1-3 intents: 70% one, 20% two, 10% three (distinct)."""
	w = intent_weights(ctx, cfg)
	intents = list(w.keys())
	if not intents:
		return "Online-Banking"
	# decide count deterministically
	r = rng.seed_for(("intent_count", ctx.date.isoformat(), ctx.agent_name, ctx.time_of_day_bucket))
	p = float(r.random())
	count = 1 if p < 0.70 else (2 if p < 0.90 else 3)
	# sample without replacement proportional to weights
	chosen: list[str] = []
	local_w = dict(w)
	for _ in range(count):
		if not local_w:
			break
		pick = _sample_from_weights(rng, local_w, ("intent", ctx.time_of_day_bucket, ctx.agent_name, len(chosen)))
		chosen.append(pick)
		local_w.pop(pick, None)
	return chosen[0] if len(chosen) == 1 else chosen


def sample_scenario(ctx: Context, intent: str | list[str], cfg: EffectiveConfig, rng: DeterministicRNG) -> str:
	"""Sample a scenario consistent with the primary intent (first in list if multi)."""
	primary = intent[0] if isinstance(intent, list) and intent else (intent if isinstance(intent, str) else "Online-Banking")
	w = scenario_weights(ctx, primary, cfg)
	return _sample_from_weights(rng, w, ("scenario", primary, ctx.agent_name))


def _trunc_normal(r, mean: float, sigma: float, min_v: float = 0.0) -> float:
	v = float(r.normal(mean, sigma))
	return max(min_v, v)


def sample_ops_metrics(ctx: Context, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, Any]:
	r = ctx.call_rng
	awt_cfg = get(cfg, "ops.awt_seconds", {})
	awt_med = float(awt_cfg.get("base_median", 90))
	awt_sigma = float(awt_cfg.get("base_sigma", 25))
	awt = _trunc_normal(r, awt_med, awt_sigma)
	if ctx.outage_flag:
		awt += float(awt_cfg.get("outage_delta", 0))
	awt += float(awt_cfg.get("channel_deltas", {}).get(ctx.channel, 0))
	awt += float(awt_cfg.get("team_deltas", {}).get(ctx.team, 0))
	if ctx.premium_wait_peak:
		awt += float(awt_cfg.get("premium_wait_peak_delta", 0))

	hold_cfg = get(cfg, "ops.hold_seconds", {})
	hold = _trunc_normal(r, float(hold_cfg.get("base_median", 45)), float(hold_cfg.get("base_sigma", 20)))
	hold += float(get(cfg, f"ops.hold_seconds.channel_deltas.{ctx.channel}", 0))

	trans_cfg = get(cfg, "ops.transfers_count", {})
	trans_probs = trans_cfg.get("channel_overrides", {}).get(ctx.channel, trans_cfg.get("base_probs", {0:0.7,1:0.2,2:0.08,3:0.02}))
	keys = list(map(int, trans_probs.keys()))
	vals = np.array([float(trans_probs[k]) for k in keys], dtype=float)
	vals = np.clip(vals, 0.0, None)
	vals = vals / (vals.sum() if vals.sum() > 0 else len(vals))
	transfers = int(r.choice(keys, p=vals))

	sil = _trunc_normal(r, float(get(cfg, "ops.silence_ratio.mean", 9.0)) + float(get(cfg, f"ops.silence_ratio.channel_deltas.{ctx.channel}", 0.0)), float(get(cfg, "ops.silence_ratio.sigma", 4.0)))
	intr = _trunc_normal(r, float(get(cfg, "ops.interruptions_count.mean", 1.2)) + float(get(cfg, f"ops.interruptions_count.channel_deltas.{ctx.channel}", 0.0)), float(get(cfg, "ops.interruptions_count.sigma", 0.8)))

	fcr_prob = float(get(cfg, "ops.fcr_base_prob", 0.78))
	if ctx.outage_flag:
		fcr_prob += float(get(cfg, "ops.fcr_penalties.outage", -0.15))
	fcr_prob += float(get(cfg, f"ops.fcr_penalties.channel.{ctx.channel}", 0.0))
	fcr_prob += float(get(cfg, f"ops.fcr_penalties.team.{ctx.team}", 0.0))
	fcr = bool(r.random() < max(0.0, min(1.0, fcr_prob)))

	return {
		"AWT": round(awt, 2),
		"Hold_time": round(hold, 2),
		"Transfers_count": transfers,
		"Silence_ratio": round(sil, 2),
		"Interruptions_count": int(round(intr)),
		"FCR": fcr,
	}


def sample_resolution(ctx: Context, intent: str, scenario: str, cfg: EffectiveConfig, rng: DeterministicRNG, fcr: bool) -> Dict[str, Any]:
	r = ctx.call_rng
	repeat = bool(r.random() < (0.35 if not fcr else 0.10))
	if not fcr and intent in ("Online-Banking","Technical Support"):
		esc = "IT Ticket"
	else:
		esc = "None" if fcr else ("Backoffice" if r.random() < 0.2 else "Supervisor")
	complaint = "WaitTime" if (ctx.premium_wait_peak and ctx.channel == "voice") else ("TechnicalIssue" if not fcr else "Fees")
	return {
		"repeat_call_within_72h": repeat,
		"escalation": esc,
		"complaint_category": complaint,
	}


def sample_nps(ctx: Context, fcr: bool, awt: float, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, Any]:
	r = ctx.call_rng
	base = dict(get(cfg, "nps.base_weights", {6:0.15,7:0.2,8:0.25,9:0.25,10:0.15}))
	keys = list(map(int, base.keys()))
	vals = np.array([float(base[k]) for k in keys], dtype=float)
	vals = np.clip(vals, 0.0, None)
	vals = vals / (vals.sum() if vals.sum() > 0 else len(vals))
	score = int(r.choice(keys, p=vals))
	corr = 0
	if awt > 120:
		corr += int(get(cfg, "nps.corrections.awt_gt_120", -2))
	if not fcr:
		corr += int(get(cfg, "nps.corrections.fcr_zero", -1))
	if ctx.premium_wait_peak:
		corr += int(get(cfg, "nps.corrections.premium_waittime", -2))
	score = max(0, min(int(get(cfg, "nps.corrections.happy_cap", 10)), score + corr))
	sent = max(-1.0, min(1.0, (score - 5) / 5.0 + float(r.normal(0, 0.1))))
	return {"NPS_score": score, "sentiment_score": round(sent, 3)}


def sample_products(ctx: Context, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, Any]:
	prod = _sample_from_weights(rng, product_weights(ctx, cfg), ("product", ctx.time_of_day_bucket))
	amount = _sample_from_weights(rng, get(cfg, "products.amount_buckets", {}), ("amount", prod)) if prod in ("Transfer","Loan","Hypothek") else None
	return {"product": prod, "amount_bucket": amount}



def sample_automation(ctx: Context, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, Any]:
	r = ctx.call_rng
	# Normalize intent for automation context
	intent_attr = getattr(ctx, "intent", "")
	intent_str = intent_attr[0] if isinstance(intent_attr, list) and intent_attr else (intent_attr if isinstance(intent_attr, str) else "")
	ssp = _sample_from_weights(rng, get(cfg, "automation.self_service_potential", {}), ("ssp", intent_str))
	p = float(get(cfg, "automation.action_present_base", 0.15))
	if intent_str in ("Online-Banking","Transfer"):
		p += float(get(cfg, f"automation.intent_lifts.{intent_str}", 0.0))
	if ctx.outage_flag:
		p += float(get(cfg, "automation.outage_penalty", -0.07))
	if ctx.channel == "Text":
		p += 0.0
	present = bool(r.random() < max(0.0, min(1.0, p)))
	action_type = _sample_from_weights(rng, get(cfg, "automation.action_type", {}), ("action", intent_str)) if present else None
	return {"self_service_potential": ssp, "automation_action_present": present, "automation_action_type": action_type}


def sample_compliance(ctx: Context, cfg: EffectiveConfig, rng: DeterministicRNG) -> Dict[str, Any]:
	r = ctx.call_rng
	passes = dict(get(cfg, "compliance.pass_rates", {}))
	# Apply global/channel/team deltas to decrease pass rates
	global_delta = float(get(cfg, "compliance.global_delta", 0.0))
	chan_d = float(get(cfg, f"compliance.channel_deltas.{ctx.channel}", 0.0))
	team_d = float(get(cfg, f"compliance.team_deltas.{ctx.team}", 0.0))
	for k in list(passes.keys()):
		passes[k] = max(0.0, min(0.999, float(passes[k]) + global_delta + chan_d + team_d))
	if ctx.outage_flag:
		passes["Empathy"] = max(0.0, float(passes.get("Empathy", 0.9)) + float(get(cfg, "compliance.outage_empathy_penalty", -0.08)))
	if ctx.agent_name == "Monika_Mueller":
		passes = {k: min(0.999, float(v) + float(get(cfg, "compliance.monika_pass_bonus", 0.05))) for k, v in passes.items()}
	flags = {k: ("pass" if r.random() < max(0.0, min(1.0, float(v))) else "fail") for k, v in passes.items()}
	script = max(0.0, min(100.0, float(r.normal(float(get(cfg, "compliance.script_adherence_mean", 86.0)), float(get(cfg, "compliance.script_adherence_sigma", 6.0))))))
	return {
		"compliance_flags": flags,
		"kb_article_used": bool(r.random() < 0.5),
		"language_switch": bool(r.random() < 0.05),
		"pii_disclosure_flag": bool(r.random() < 0.02),
		"script_adherence": round(script, 1),
	}


def sample_silence_total_seconds(ctx: Context, scenario: str, nps_score: int, cfg: EffectiveConfig) -> float:
	base_mean = float(get(cfg, "ops.silence_total_seconds.base_mean", 12.0))
	base_sigma = float(get(cfg, "ops.silence_total_seconds.base_sigma", 6.0))
	agent_delta = float(get(cfg, f"ops.silence_total_seconds.agent_deltas.{ctx.agent_name}", 0.0))
	team_delta = float(get(cfg, f"ops.silence_total_seconds.team_deltas.{ctx.team}", 0.0))
	channel_lift = float(get(cfg, f"ops.silence_total_seconds.channel_lifts.{ctx.channel}", 0.0))
	scenario_lift = float(get(cfg, f"ops.silence_total_seconds.scenario_lifts.{scenario}", 0.0))
	low_thr = int(get(cfg, "ops.silence_total_seconds.nps.low_threshold", 7))
	per_point = float(get(cfg, "ops.silence_total_seconds.nps.per_point_below", 1.5))
	nps_penalty = max(0, low_thr - int(nps_score)) * per_point
	mean = base_mean + agent_delta + team_delta + channel_lift + scenario_lift + nps_penalty
	r = ctx.call_rng
	value = _trunc_normal(r, mean, base_sigma, 0.0)
	return round(value, 2)


def generate_german_ani(rng: DeterministicRNG, key: tuple) -> str:
	"""Generate German E.164 ANI like +49XXXXXXXXX (9..12 digits after +49)."""
	r = rng.seed_for(("ani",) + tuple(key))
	length = int(r.integers(9, 13))
	digits = ''.join(str(int(d)) for d in r.integers(0, 10, size=length))
	return "+49" + digits
