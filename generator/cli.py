from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any

import click

from .config import EffectiveConfig, load_and_merge_configs, save_effective_config
from .rng import DeterministicRNG
from .calendar import make_calendar, DayPlan
from .volume import estimate_daily_volume, split_by_agent, split_by_shift, split_by_time_buckets
from .features import Context, sample_customer_segment, sample_channel, sample_geo_language_device, sample_intent, sample_scenario, sample_ops_metrics, sample_resolution, sample_nps, sample_products, sample_automation, sample_compliance, sample_silence_total_seconds, generate_german_ani
from .schema import save_schema, save_field_descriptions, save_prompt_template
from .io import write_call_json


def generate_dataset(cfg: EffectiveConfig, start_date: date, end_date: date, out_dir: Path, seed: int, validate: bool = True) -> None:
	rng = DeterministicRNG(seed)
	days = make_calendar(start_date, end_date, cfg, rng)
	ani_cache: dict[str, Dict[str, Any]] = {}
	for day in days:
		day_rng = rng.seed_for(("day", day.date.isoformat()))
		vol = estimate_daily_volume(day, cfg, rng)
		by_agent = split_by_agent(vol.estimated, day.is_weekend, cfg, rng)
		for agent_name, agent_count in by_agent.items():
			by_shift = split_by_shift(agent_name, agent_count, cfg, rng)
			team = cfg.data.get("agents", {}).get("members", {}).get(agent_name, {}).get("team", "Team A")
			for shift_name, shift_count in by_shift.items():
				by_bucket = split_by_time_buckets(shift_count, day.is_weekend, cfg, rng)
				for bucket, n_calls in by_bucket.items():
					for i in range(n_calls):
						call_rng = rng.seed_for((day.date.isoformat(), agent_name, shift_name, bucket, i))
			# Identity/time
						ctx = Context(
							date=day.date,
							weekday=day.weekday,
							time_of_day_bucket=bucket,
							agent_name=agent_name,
							team=team,
							agent_shift=shift_name,
							customer_segment="",
							channel="",
				region="",
				language="",
							device_type="",
							outage_flag=day.outage_flag,
							app_issue_flag=day.app_issue_flag,
							premium_wait_peak=day.premium_wait_peak,
							call_rng=call_rng,
							hour_lt_18=(bucket in ("Morning","Afternoon")),
						)

						from .rng import DeterministicRNG as DR
						det = DR(seed)

						call: Dict[str, Any] = {
							"call_id": det.uuid4_deterministic(call_rng),
							"date": day.date.isoformat(),
							"weekday": day.weekday,
							"time_of_day_bucket": bucket,
							"agent_name": agent_name,
							"team": team,
							"agent_shift": shift_name,
						}

						seg = sample_customer_segment(ctx, cfg, det)["customer_segment"]
						ctx.customer_segment = seg
						call.update({"customer_segment": seg})

						ch = sample_channel(ctx, cfg, det)["channel"]
						ctx.channel = ch
						call.update({"channel": ch})

			# Sample geo/language/device from config weights
			geo = sample_geo_language_device(ctx, cfg, det, seg)
			ctx.region = str(geo.get("region", "ZH"))
			ctx.language = str(geo.get("language", "EN"))
			ctx.device_type = str(geo.get("device_type", "iOS"))
			call.update({"region": ctx.region, "language": ctx.language, "device_type": ctx.device_type})

						intent = sample_intent(ctx, cfg, det)
						intent_str = intent[0] if isinstance(intent, list) and intent else (intent if isinstance(intent, str) else "Online-Banking")
						call["intent"] = intent_str
						ctx.intent = intent_str  # type: ignore[attr-defined]

						scenario = sample_scenario(ctx, intent_str, cfg, det)
						call["scenario"] = scenario

						op = sample_ops_metrics(ctx, cfg, det)
						call.update(op)

						# For text channel, omit hold/silence/interruptions from metadata entirely
						if ctx.channel == "text":
							for k in ("Hold_time", "Silence_ratio", "Interruptions_count"):
								if k in call:
									call.pop(k, None)

						res = sample_resolution(ctx, intent_str, scenario, cfg, det, op["FCR"])
						call.update(res)

						nps = sample_nps(ctx, op["FCR"], op["AWT"], cfg, det)
						call.update(nps)

						# Deterministic customer key
						cust_key = (seg, ctx.channel, scenario.split(" ")[0])
						if cust_key in ani_cache:
							cust_meta = ani_cache[cust_key]
							ani = cust_meta["ANI"]
							call.update({
								"ANI": ani,
								"region": cust_meta["region"],
								"language": cust_meta["language"],
							})
						else:
				ani = generate_german_ani(det, cust_key)
				ani_cache[cust_key] = {"ANI": ani, "region": ctx.region, "language": ctx.language}
							call["ANI"] = ani

						# Silence total seconds depends on scenario and NPS
						sil_total = sample_silence_total_seconds(ctx, scenario, nps["NPS_score"], cfg)
						call["Silence_total_seconds"] = sil_total

						prod = sample_products(ctx, cfg, det)
						call.update(prod)

						auto = sample_automation(ctx, cfg, det)
						call.update(auto)

						comp = sample_compliance(ctx, cfg, det)
						call.update(comp)

						# Skip JSON schema validation for text channel where optional fields are omitted
						validate_this = bool(validate and ctx.channel != "text")
						write_call_json(out_dir, call, validate=validate_this)


def write_meta(out_dir: Path) -> None:
	(out_dir / "_meta").mkdir(parents=True, exist_ok=True)
	save_field_descriptions(out_dir / "_meta" / "field_descriptions.json")
	save_prompt_template(out_dir / "_meta" / "prompt_template.json")


@click.command()
@click.option("--start", required=True, type=str, help="Start date YYYY-MM-DD")
@click.option("--end", required=True, type=str, help="End date YYYY-MM-DD")
@click.option("--out", "out_dir", required=True, type=click.Path(path_type=Path), help="Output directory")
@click.option("--seed", required=True, type=int, help="Global seed")
@click.option("--outages", required=False, type=int, default=None, help="Override outages count")
@click.option("--validate/--no-validate", default=True)
@click.option("--config-base", type=click.Path(path_type=Path), default=Path("config/base.yml"))
@click.option("--config-overrides", type=click.Path(path_type=Path), default=Path("config/overrides.yml"))
def main(start: str, end: str, out_dir: Path, seed: int, outages: int | None, validate: bool, config_base: Path, config_overrides: Path) -> None:
	start_date = datetime.strptime(start, "%Y-%m-%d").date()
	end_date = datetime.strptime(end, "%Y-%m-%d").date()
	cfg = load_and_merge_configs(config_base, config_overrides)
	if outages is not None:
		cfg.data.setdefault("calendar", {}).setdefault("incidents", {})["outages_count"] = outages
	out_dir.mkdir(parents=True, exist_ok=True)
	(out_dir / "_meta").mkdir(parents=True, exist_ok=True)
	save_effective_config(cfg, out_dir / "_meta")
	save_schema(out_dir / "_meta" / "schema_call.json")
	write_meta(out_dir)
	generate_dataset(cfg, start_date, end_date, out_dir, seed, validate)


if __name__ == "__main__":
	main()
