from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from .config import EffectiveConfig, get
from .rng import DeterministicRNG


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class DayPlan:
	date: date
	weekday: str
	is_weekend: bool
	weekday_factor: float
	outage_flag: bool
	app_issue_flag: bool
	premium_wait_peak: bool


def daterange(start: date, end: date) -> Iterable[date]:
	d = start
	while d <= end:
		yield d
		d += timedelta(days=1)


def select_outage_days(start: date, end: date, outages: int, rng: DeterministicRNG) -> set[date]:
	weekdays = [d for d in daterange(start, end) if d.weekday() < 5]
	r = rng.seed_for(("outages", start.isoformat(), end.isoformat()))
	if outages <= 0 or not weekdays:
		return set()
	outages = min(outages, len(weekdays))
	idxs = r.choice(len(weekdays), size=outages, replace=False)
	return {weekdays[int(i)] for i in idxs}


def make_calendar(start_date: date, end_date: date, cfg: EffectiveConfig, rng: DeterministicRNG) -> list[DayPlan]:
	wd_factors = get(cfg, "calendar.weekday_factors", {})
	outages_count = int(get(cfg, "calendar.incidents.outages_count", 0) or 0)
	app_after_days = int(get(cfg, "calendar.incidents.app_issue_after_outage_days", 0) or 0)
	premium_peak_days = set(get(cfg, "calendar.incidents.premium_wait_peak_days", []) or [])

	outage_days = select_outage_days(start_date, end_date, outages_count, rng)
	app_issue_days: set[date] = set()
	for d in outage_days:
		for k in range(1, app_after_days + 1):
			nd = d + timedelta(days=k)
			if nd <= end_date:
				app_issue_days.add(nd)

	days: list[DayPlan] = []
	for d in daterange(start_date, end_date):
		wd_idx = d.weekday()
		wd = WEEKDAYS[wd_idx]
		is_weekend = wd_idx >= 5
		factor = float(wd_factors.get(wd, 1.0))
		outage_flag = d in outage_days
		app_issue_flag = d in app_issue_days
		premium_wait_peak = wd in premium_peak_days
		days.append(DayPlan(
			date=d,
			weekday=wd,
			is_weekend=is_weekend,
			weekday_factor=factor,
			outage_flag=outage_flag,
			app_issue_flag=app_issue_flag,
			premium_wait_peak=premium_wait_peak,
		))
	return days
