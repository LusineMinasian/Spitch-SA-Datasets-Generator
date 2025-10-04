from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

import numpy as np


class DeterministicRNG:
	"""Deterministic RNG with hierarchical seeding and helpers."""

	def __init__(self, global_seed: int) -> None:
		self.global_seed = int(global_seed)
		self._root = np.random.default_rng(self.global_seed)

	@staticmethod
	def _hash_to_uint64(data: bytes) -> int:
		digest = hashlib.blake2b(data, digest_size=8).digest()
		return int.from_bytes(digest, byteorder="big", signed=False)

	def seed_for(self, key: Any) -> np.random.Generator:
		data = key if isinstance(key, bytes) else repr(key).encode("utf-8")
		combined = self.global_seed.to_bytes(8, "big", signed=False) + data
		seed_int = self._hash_to_uint64(combined)
		return np.random.default_rng(seed_int)

	@staticmethod
	def normalize(weights: Mapping[str, float]) -> Mapping[str, float]:
		total = float(sum(max(0.0, v) for v in weights.values()))
		if total <= 0.0:
			n = len(weights) or 1
			return {k: 1.0 / n for k in weights}
		return {k: max(0.0, v) / total for k, v in weights.items()}

	def choice_weighted(self, items: Sequence[str], weights: Sequence[float], rng: np.random.Generator | None = None) -> str:
		r = rng or self._root
		idx = r.choice(len(items), p=np.array(weights, dtype=float))
		return items[int(idx)]

	def multinomial_split(self, total: int, ratios: Mapping[str, float], rng: np.random.Generator | None = None) -> dict[str, int]:
		r = rng or self._root
		keys = list(ratios.keys())
		probs = np.array([ratios[k] for k in keys], dtype=float)
		if probs.sum() <= 0:
			probs = np.ones_like(probs) / len(probs)
		draws = r.multinomial(total, (probs / probs.sum()).tolist()) if total > 0 else np.zeros_like(probs, dtype=int)
		return {k: int(v) for k, v in zip(keys, draws.tolist())}

	def uuid4_deterministic(self, rng: np.random.Generator | None = None) -> str:
		r = rng or self._root
		b = bytearray(r.bytes(16))
		b[6] = (b[6] & 0x0F) | 0x40
		b[8] = (b[8] & 0x3F) | 0x80
		import uuid
		return str(uuid.UUID(bytes=bytes(b)))
