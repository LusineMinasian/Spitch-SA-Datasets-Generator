from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict

import orjson

from .schema import validate_against_schema


def out_dir_for_date(base_out: Path, d: date) -> Path:
	p = base_out / d.isoformat()
	p.mkdir(parents=True, exist_ok=True)
	return p


def write_call_json(base_out: Path, call: Dict[str, Any], validate: bool = True) -> Path:
	if validate:
		validate_against_schema(call)
	day_dir = out_dir_for_date(base_out, date.fromisoformat(call["date"]))
	call_id = call["call_id"]
	path = day_dir / f"{call_id}.json"
	path.write_bytes(orjson.dumps(call, option=orjson.OPT_INDENT_2))
	return path
