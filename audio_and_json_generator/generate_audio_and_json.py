import argparse
import io
import os
import re
import uuid
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openai import OpenAI
from pydub import AudioSegment
from pydub.generators import Sine


DEFAULT_OPENAI_API_KEY = "ADD_YOUR_API_KEY_HERE"

SPEAKER_AGENT_PREFIXES = ("Agent:",)
SPEAKER_CUSTOMER_PREFIXES = ("Customer:", "Kunde:")

SILENCE_RE = re.compile(r"^\[silence\s+([0-9]+(?:\.[0-9]+)?)s\]\s*$", re.IGNORECASE)
HOLD_RE = re.compile(r"^\[hold\s+([0-9]+(?:\.[0-9]+)?)s\]\s*$", re.IGNORECASE)
# Inline tag matcher (find hold/silence anywhere in text)
INLINE_TAG_RE = re.compile(r"\[(hold|silence)\s+([0-9]+(?:\.[0-9]+)?)s\]", re.IGNORECASE)


def _parse_scalar(value: str) -> Any:
	"""Best-effort scalar coercion: bool → int → float → str."""
	v = value.strip()
	lv = v.lower()
	if lv in ("true", "false"):
		return lv == "true"
	# integer
	if re.fullmatch(r"[-]?\d+", v):
		try:
			return int(v)
		except Exception:
			pass
	# float (with optional exponent)
	if re.fullmatch(r"[-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", v):
		try:
			return float(v)
		except Exception:
			pass
	return value


@dataclass
class Utterance:
	speaker: str  # "C1" or "C2" or "music" or "silence"
	text: str
	duration_hint_s: float | None = None


def parse_text_conversation(path: Path) -> Tuple[Dict[str, Any], List[Utterance]]:
	"""Parse our .txt conversation file into header metadata and a list of utterances/events.

	Returns: (header_dict, utterances)
	"""
	content = path.read_text(encoding="utf-8", errors="ignore").splitlines()

	# Separate header from dialogue
	headers: Dict[str, Any] = {}
	dialogue_start_idx = 0
	for i, line in enumerate(content):
		if line.strip() == "---- DIALOGUE ----":
			dialogue_start_idx = i + 1
			break
	# Parse header key: value lines from top until blank or divider
	for line in content[:dialogue_start_idx - 1]:
		line = line.strip()
		if not line or line.startswith("----"):
			continue
		if ":" in line:
			k, v = line.split(":", 1)
			headers[k.strip()] = _parse_scalar(v)

    # Parse dialogue lines
	utterances: List[Utterance] = []
	for raw in content[dialogue_start_idx:]:
		line = raw.strip()
		if not line:
			continue
		# Silence
		m_sil = SILENCE_RE.match(line)
		if m_sil:
			d = float(m_sil.group(1))
			utterances.append(Utterance("silence", "", duration_hint_s=d))
			continue
		# Hold
		m_hold = HOLD_RE.match(line)
		if m_hold:
			d = float(m_hold.group(1))
			utterances.append(Utterance("music", "hold music", duration_hint_s=d))
			continue
		# Agent / Customer lines
		speaker = None
		for p in SPEAKER_AGENT_PREFIXES:
			if line.startswith(p):
				speaker = "C1"
				text = line[len(p):].strip()
				break
		if speaker is None:
			for p in SPEAKER_CUSTOMER_PREFIXES:
				if line.startswith(p):
					speaker = "C2"
					text = line[len(p):].strip()
					break
		if speaker is None:
			# Accept German "Kunde:" typo or other variants by splitting once
			parts = line.split(":", 1)
			if len(parts) == 2:
				label, text = parts[0].strip(), parts[1].strip()
				if label.lower().startswith("agent"):
					speaker = "C1"
				elif label.lower().startswith("customer") or label.lower().startswith("kunde"):
					speaker = "C2"
		if speaker:
			# Split inline [hold Xs] / [silence Xs] out of spoken text
			pos = 0
			for m in INLINE_TAG_RE.finditer(text):
				leading = text[pos:m.start()].strip()
				if leading:
					utterances.append(Utterance(speaker, leading))
				kind = m.group(1).lower()
				dur = float(m.group(2))
				if kind == "hold":
					utterances.append(Utterance("music", "hold music", duration_hint_s=dur))
				else:
					utterances.append(Utterance("silence", "", duration_hint_s=dur))
				pos = m.end()
			trailing = text[pos:].strip()
			if trailing:
				utterances.append(Utterance(speaker, trailing))

	return headers, utterances


def select_agent_gender(agent_name: str) -> str:
	"""Return 'female' or 'male' based on known agent names; default to 'female'."""
	females = {"Monika_Mueller","Anna_Ziegler","Jasmin_Caggiano","Heidi_Vogt","Laura_Brunner","Karin_Herzog","Nina_Weber"}
	males = {"Lukas_Schmidt","Peter_Keller","Marco_Fischer","Sven_Meier","Paul_Huber"}
	if agent_name in males:
		return "male"
	return "female"


def gpt_tts_generate(client: OpenAI, text: str, voice: str = "nova", output_dir: str = "temp") -> tuple[str, float]:
	"""Generate TTS using OpenAI tts-1 and save WAV directly; return wav_path and duration seconds."""
	os.makedirs(output_dir, exist_ok=True)
	filename = uuid.uuid4().hex
	wav_path = os.path.join(output_dir, f"{filename}.wav")
	try:
		# Stream WAV directly to file to avoid mp3->wav conversion and ffmpeg dependency
		with client.audio.speech.with_streaming_response.create(
			model="tts-1",
			voice=voice,
			input=text,
			response_format="wav",
		) as response:
			response.stream_to_file(wav_path)
		# Compute duration from WAV
		audio_segment = AudioSegment.from_file(wav_path, format="wav")
		duration_sec = len(audio_segment) / 1000.0
		return wav_path, duration_sec
	except Exception:
		# Fallback: create full response and write WAV bytes
		resp = client.audio.speech.create(
			model="tts-1",
			voice=voice,
			input=text,
			response_format="wav",
		)
		try:
			resp.write_to_file(wav_path)  # type: ignore[attr-defined]
		except Exception:
			data = resp.read() if hasattr(resp, "read") else bytes(resp)  # type: ignore
			with open(wav_path, "wb") as f:
				f.write(data)
		audio_segment = AudioSegment.from_file(wav_path, format="wav")
		duration_sec = len(audio_segment) / 1000.0
		return wav_path, duration_sec


def build_audio_and_json(
	client: OpenAI,
	headers: Dict[str, Any],
	utterances: List[Utterance],
	hold_audio_path: Path,
	voice_agent: str,
	voice_customer: str,
	tmp_dir: str,
) -> Tuple[AudioSegment, Dict[str, Any]]:
	"""Synthesize audio timeline and return (audio_segment, json_payload)."""
	# Preload/prepare hold music
	try:
		hold_base = AudioSegment.from_file(hold_audio_path)
	except Exception:
		# Fallback to synthetic music-like tone if hold asset missing
		tone_a = Sine(440).to_audio_segment(duration=500)
		tone_b = Sine(660).to_audio_segment(duration=500)
		tone = tone_a.append(tone_b, crossfade=50)
		hold_base = tone - 18

	# Containers for JSON output
	smoothed_c1: List[Dict[str, Any]] = []
	smoothed_c2: List[Dict[str, Any]] = []

	# First pass: generate all segments
	events: List[Dict[str, Any]] = []  # {type, speaker, text, seg, dur_ms}
	voice_agent = normalize_voice_name(voice_agent)
	voice_customer = normalize_voice_name(voice_customer)
	channel_value = str(headers.get("channel", "")).strip().lower()
	for u in utterances:
		if u.speaker == "silence":
			# Skip adding explicit silence segments for text channel transcripts
			continue
		elif u.speaker == "music":
			# Include hold music only for voice channel; skip for text
			if channel_value == "voice":
				dur_ms = int(max(0.0, float(u.duration_hint_s or 0.0) * 1000.0))
				if dur_ms <= 0:
					continue
				unit_ms = len(hold_base)
				if unit_ms <= 0:
					continue
				repeats = dur_ms // unit_ms
				remainder = dur_ms % unit_ms
				seg = (hold_base * max(0, repeats)) + (hold_base[:remainder] if remainder > 0 else AudioSegment.silent(duration=0))
				events.append({"type": "music", "speaker": "C1", "text": "hold music", "seg": seg, "dur_ms": len(seg)})
			continue
		elif u.speaker == "C1":
			wav_path, _ = gpt_tts_generate(client, u.text, voice_agent, output_dir=tmp_dir)
			seg = AudioSegment.from_wav(wav_path)
			events.append({"type": "speech", "speaker": "C1", "text": u.text, "seg": seg, "dur_ms": len(seg)})
		elif u.speaker == "C2":
			wav_path, _ = gpt_tts_generate(client, u.text, voice_customer, output_dir=tmp_dir)
			seg = AudioSegment.from_wav(wav_path)
			events.append({"type": "speech", "speaker": "C2", "text": u.text, "seg": seg, "dur_ms": len(seg)})

	# Determine interruptions and compute start times
	try:
		interruptions_target = int(float(headers.get("Interruptions_count", 0)))
	except Exception:
		interruptions_target = 0
	pairs: List[int] = []  # indices i where events[i] and events[i+1] are speech with different speakers
	for i in range(len(events) - 1):
		a, b = events[i], events[i + 1]
		if a["type"] == b["type"] == "speech" and a["speaker"] != b["speaker"]:
			pairs.append(i)
	random.shuffle(pairs)
	chosen_pairs = set(pairs[: max(0, interruptions_target)])
	# start times
	starts: List[int] = []
	for i, ev in enumerate(events):
		if i == 0:
			starts.append(0)
			continue
		prev_end = starts[i - 1] + events[i - 1]["dur_ms"]
		if (i - 1) in chosen_pairs:
			# overlap current with previous
			max_overlap = int(events[i - 1]["dur_ms"] * 0.3)
			if max_overlap >= 150:
				overlap_ms = random.randint(150, min(600, max_overlap))
				starts.append(max(0, prev_end - overlap_ms))
				continue
		starts.append(prev_end)

	# Second pass: build JSON and render by overlaying
	total_ms = 0
	for i, ev in enumerate(events):
		start_ms = starts[i]
		end_ms = start_ms + ev["dur_ms"]
		total_ms = max(total_ms, end_ms)
		start_s = round(start_ms / 1000.0, 3)
		end_s = round(end_ms / 1000.0, 3)
		if ev["type"] == "speech" and ev["speaker"] == "C1":
			smoothed_c1.append({
				"start": start_s,
				"end": end_s,
				"cid": "C1",
				"text": ev["text"],
				"denormalized": ev["text"],
				"stype": "female" if voice_agent_female(voice_agent) else "male",
			})
		elif ev["type"] == "speech" and ev["speaker"] == "C2":
			smoothed_c2.append({
				"start": start_s,
				"end": end_s,
				"cid": "C2",
				"text": ev["text"],
				"denormalized": ev["text"],
				"stype": "male",
			})
		elif ev["type"] == "music":
			smoothed_c1.append({
				"start": start_s,
				"end": end_s,
				"cid": "C1",
				"text": "hold music",
				"denormalized": "hold music",
				"stype": "music",
			})
	# Render overlay
	# Build stereo by rendering per-speaker mono tracks then combine
	left_track = AudioSegment.silent(duration=total_ms)   # Agent (C1)
	right_track = AudioSegment.silent(duration=total_ms)  # Client (C2)
	for i, ev in enumerate(events):
		pos = starts[i]
		if ev["type"] == "speech":
			mono = ev["seg"].set_channels(1)
			if ev["speaker"] == "C1":
				left_track = left_track.overlay(mono, position=pos)
			elif ev["speaker"] == "C2":
				right_track = right_track.overlay(mono, position=pos)
		elif ev["type"] == "music":
			# hold music centered (both channels, slightly lower volume)
			mono_music = ev["seg"].set_channels(1) - 3
			left_track = left_track.overlay(mono_music, position=pos)
			right_track = right_track.overlay(mono_music, position=pos)

	final = AudioSegment.from_mono_audiosegments(left_track, right_track)

	# Build JSON payload
	c1_payload: Dict[str, Any] = {
		"cid": "1",
		"metadata": {"smoothed": smoothed_c1},
	}
	# copy ALL header entries into C1
	c1_payload.update(headers)

	c2_payload: Dict[str, Any] = {
		"cid": "2",
		"metadata": {"smoothed": smoothed_c2},
	}

	return final, {"C1": c1_payload, "C2": c2_payload}


def voice_agent_female(voice_name: str) -> bool:
	# Heuristic classification for stype in JSON
	female_like = {"nova", "fable", "coral", "shimmer"}
	return voice_name.lower() in female_like


def normalize_voice_name(name: str) -> str:
	allowed = {"nova", "shimmer", "echo", "onyx", "fable", "alloy", "ash", "sage", "coral"}
	alias = {
		"aria": "nova",
		"verse": "alloy",
	}
	n = name.lower()
	n = alias.get(n, n)
	return n if n in allowed else "alloy"


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate audio + JSON timeline from conversation .txt")
	parser.add_argument("--in_file", type=str, help="Path to a single conversation .txt file", default=None)
	parser.add_argument("--in_dir", type=str, help="Directory with .txt conversations to process", default=None)
	parser.add_argument("--out_dir", type=str, help="Output directory for audio (.wav) and .wav.json", default="audio_and_json_generator/results")
	parser.add_argument("--api_key", type=str, help="OpenAI API key (or use OPENAI_API_KEY env)", default=None)
	parser.add_argument("--hold", type=str, help="Path to hold music audio (mp3/wav)", default="audio_and_json_generator/hold.mp3")
	parser.add_argument("--voice_female", type=str, default="nova", help="TTS voice for female agent (supported: nova, shimmer, fable, coral)")
	parser.add_argument("--voice_male", type=str, default="alloy", help="TTS voice for male agent (supported: alloy, ash, onyx, echo, sage)")
	parser.add_argument("--voice_customer", type=str, default="ash", help="TTS voice for customer")
	parser.add_argument("--tmp_dir", type=str, default="temp", help="Directory to store intermediate TTS files")
	args = parser.parse_args()

	if not args.in_file and not args.in_dir:
		parser.error("Provide --in_file or --in_dir")

	client = OpenAI(api_key=args.api_key or os.getenv("OPENAI_API_KEY") or DEFAULT_OPENAI_API_KEY)
	out_root = Path(args.out_dir)
	out_root.mkdir(parents=True, exist_ok=True)
	hold_path = Path(args.hold)

	input_files: List[Path] = []
	if args.in_file:
		input_files.append(Path(args.in_file))
	if args.in_dir:
		for p in Path(args.in_dir).glob("*.txt"):
			input_files.append(p)

	for in_path in input_files:
		headers, utterances = parse_text_conversation(in_path)
		agent_name = str(headers.get("agent_name", ""))
		agent_gender = select_agent_gender(agent_name)
		voice_agent = args.voice_female if agent_gender == "female" else args.voice_male
		final_audio, payload = build_audio_and_json(
			client=client,
			headers=headers,
			utterances=utterances,
			hold_audio_path=hold_path,
			voice_agent=voice_agent,
			voice_customer=args.voice_customer,
			tmp_dir=args.tmp_dir,
		)

		base = in_path.stem
		wav_path = out_root / f"{base}.wav"
		json_path = out_root / f"{base}.wav.json"

		# Export audio unless channel is text
		ch = str(headers.get("channel", "")).strip().lower()
		if ch != "text":
			final_audio.export(wav_path, format="wav")

		# Dump JSON
		import orjson
		json_bytes = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
		json_path.write_bytes(json_bytes)


if __name__ == "__main__":
	main()


