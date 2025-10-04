from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import orjson
import yaml


def _deep_merge(a: dict, b: dict) -> dict:
	out = deepcopy(a)
	for k, v in b.items():
		if isinstance(v, dict) and isinstance(out.get(k), dict):
			out[k] = _deep_merge(out[k], v)
		else:
			out[k] = deepcopy(v)
	return out


@dataclass
class EffectiveConfig:
	data: dict

	def to_json_bytes(self) -> bytes:
		return orjson.dumps(self.data, option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS)


def load_and_merge_configs(base_path: Path, overrides_path: Path) -> EffectiveConfig:
	with base_path.open("rb") as f:
		base_cfg = yaml.safe_load(f) or {}
	if overrides_path.exists():
		with overrides_path.open("rb") as f:
			overrides_cfg = yaml.safe_load(f) or {}
	else:
		overrides_cfg = {}
	eff = _deep_merge(base_cfg, overrides_cfg)
	return EffectiveConfig(eff)


def save_effective_config(eff: EffectiveConfig, out_meta_dir: Path) -> None:
	out_meta_dir.mkdir(parents=True, exist_ok=True)
	(out_meta_dir / "config_effective.json").write_bytes(eff.to_json_bytes())


def get(cfg: EffectiveConfig, path: str, default: Any = None) -> Any:
	node: Mapping[str, Any] = cfg.data
	for part in path.split("."):
		if not isinstance(node, Mapping) or part not in node:
			return default
		node = node[part]
	return node
