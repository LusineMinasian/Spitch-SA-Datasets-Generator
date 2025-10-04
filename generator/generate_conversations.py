import os
import sys
from pathlib import Path
from typing import Any, Dict

import orjson
from openai import OpenAI
import hashlib
import random
import argparse


TEMPLATE_PATH = Path("out/_meta/prompt_template.json")
LABELS_PATH = Path("config/labels.json")
VALUE_LABELS_PATH = Path("config/value_labels.json")
VALUE_LABELS_DATA: Dict[str, Any] = {}

# WARNING: Hardcoding API keys in code is insecure. Replace the placeholder below with your key only if
# you understand the risks, or prefer using --api-key flag or OPENAI_API_KEY env var.
DEFAULT_OPENAI_API_KEY = "ADD_YOUR_API_KEY_HERE"


def load_json(path: Path) -> Any:
	return orjson.loads(path.read_bytes())



def localize_value(loc: str, key: str, value: Any) -> Any:
	if loc != "de":
		return value
	try:
		vmap_all = VALUE_LABELS_DATA or load_json(VALUE_LABELS_PATH)
		vmap = vmap_all.get("de", {}).get(key, {})
		if isinstance(value, bool):
			return vmap.get("true" if value else "false", value)
		if isinstance(value, (int, float)):
			return value
		# strings
		return vmap.get(str(value), value)
	except Exception:
		return value


def render_prompt(template: Dict[str, Any], call: Dict[str, Any], preferred_locale: str | None = None) -> str:
	# Simple {{key}} replacement including dotted keys
	def get_value(key: str) -> Any:
		parts = key.split('.')
		val: Any = call
		for p in parts:
			if isinstance(val, dict) and p in val:
				val = val[p]
			else:
				return ""
		return val

	# Choose prompt by preferred_locale first, then call language
	prompt = template.get("prompt_en", "")
	loc = (preferred_locale or "").strip().lower() if preferred_locale else ""
	if loc and f"prompt_{loc}" in template:
		prompt = template.get(f"prompt_{loc}", prompt)
	else:
		lang_val = str(call.get("language", "DE"))
		lang_norm = lang_val.strip().lower()
		if lang_norm in ("de", "de-de", "german", "deutsch"):
			prompt = template.get("prompt_de", prompt)
	# For text channel, strip hold/silence instructions from the prompt
	channel = str(call.get("channel", "voice")).strip().lower()
	if channel == "text":
		lines = prompt.splitlines()
		filtered: list[str] = []
		for line in lines:
			if "Silence:" in line:
				continue
			filtered.append(line.replace("with [hold {{duration}}s] if needed", ""))
		prompt = "\n".join(filtered)
		prompt = prompt.replace("include [hold Xs] totalling ~{{Hold_time}}; ", "")
	for key in template.get("placeholders", []):
		val = get_value(key)
		prompt = prompt.replace("{{" + key + "}}", str(val))
	return prompt


def infer_time_suffix(call: Dict[str, Any]) -> str:
	"""Return a deterministic random HHMMSS within the bucket range."""
	bucket = str(call.get("time_of_day_bucket", ""))
	# Seed per call for determinism
	seed_bytes = repr((call.get("date"), call.get("agent_name"), bucket, call.get("call_id"))).encode("utf-8")
	seed = int.from_bytes(hashlib.blake2b(seed_bytes, digest_size=8).digest(), "big")
	rng = random.Random(seed)

	if bucket == "Night":
		start_h, end_h = 0, 5
	elif bucket == "Morning":
		start_h, end_h = 6, 11
	elif bucket == "Afternoon":
		start_h, end_h = 12, 17
	elif bucket == "Evening":
		start_h, end_h = 18, 23
	else:
		start_h, end_h = 12, 14

	h = rng.randint(start_h, end_h)
	m = rng.randint(0, 59)
	s = rng.randint(0, 59)
	return f"{h:02d}{m:02d}{s:02d}"


def extract_text_from_response(resp: Any) -> str:
	# Chat completions: choices[0].message.content may be str or list
	try:
		choice0 = resp.choices[0]
		msg = getattr(choice0, "message", None) or choice0["message"]
		content = getattr(msg, "content", None)
		if isinstance(content, str):
			return content
		if isinstance(content, list):
			parts: list[str] = []
			for c in content:
				if isinstance(c, dict) and "text" in c:
					parts.append(str(c["text"]))
				else:
					text = getattr(c, "text", None)
					if text:
						parts.append(str(text))
			return "\n".join(parts)
	except Exception:
		pass
	# Responses API compatibility fallback
	text = getattr(resp, "output_text", None)
	return text or ""


def generate_dialog(client: OpenAI, model: str, prompt: str) -> str:
	# Try Responses API first (with quality params if supported)
	try:
		resp = client.responses.create(
			model=model,
			input=[
				{"role": "system", "content": "Act as a realistic dialogue generator. Create natural, coherent transcripts."},
				{"role": "user", "content": prompt},
			],
			max_output_tokens=2048,
			temperature=0.7,
			top_p=0.9,
		)
		text = getattr(resp, "output_text", None) or extract_text_from_response(resp)
		if text and text.strip():
			return text.strip()
	except Exception as e:
		print(f"Responses API error ({model}): {e}", file=sys.stderr)
	# Fallback to Chat Completions with penalties to reduce repetition
	try:
		# normalize model name for chat if needed
		chat_model = "gpt-5-chat-latest" if model.strip() == "gpt-5" else model
		resp = client.chat.completions.create(
			model=chat_model,
			messages=[
				{"role": "system", "content": "Acting as a realistic dialogue generator. Your job is to create natural, engaging, and believable dialogues."},
				{"role": "user", "content": prompt},
			],
			max_tokens=2048,
			temperature=0.7,
			top_p=0.9,
			frequency_penalty=0.4,
			presence_penalty=0.2,
		)
		return extract_text_from_response(resp).strip()
	except Exception as e:
		print(f"Chat API error ({chat_model}): {e}", file=sys.stderr)
		return ""


def synthesize_dialog(call: Dict[str, Any]) -> str:
	"""Rule-based deterministic fallback transcript when LLM output is empty, with variety."""
	rng_seed = repr((call.get("call_id"), call.get("agent_name"), call.get("date"), call.get("intent"), call.get("scenario"))).encode("utf-8")
	rng = random.Random(int.from_bytes(hashlib.blake2b(rng_seed, digest_size=8).digest(), "big"))
	lang = str(call.get("language", "DE"))
	voice = ("Agent:", "Customer:") if lang != "DE" else ("Agent:", "Kunde:")
	intent = str(call.get("intent", ""))
	scenario = str(call.get("scenario", ""))
	channel = str(call.get("channel", "voice"))
	nps = int(call.get("NPS_score", 8))
	fcr = bool(call.get("FCR", True))
	esc = str(call.get("escalation", "None"))
	kb = bool(call.get("kb_article_used", False))
	transfers = int(call.get("Transfers_count", 0))
	hold_total = int(round(float(call.get("Hold_time", 0))))
	sil_total = float(call.get("Silence_total_seconds", 8.0))

	customer_openers_de = [
		f"Ich habe ein Problem mit {intent}.",
		f"Es geht um {scenario} bei {intent}.",
		"Ich komme nicht weiter, können Sie helfen?",
	]
	agent_openers_de = [
		"Willkommen bei MusterBank, wie kann ich Ihnen helfen?",
		"Guten Tag, hier ist die MusterBank. Worum geht es?",
		"Hallo, MusterBank Kundenservice. Wie kann ich unterstützen?",
	]
	customer_openers_en = [
		f"I have an issue with {intent}.",
		f"It's about {scenario} under {intent}.",
		"I'm stuck, could you help me?",
	]
	agent_openers_en = [
		"Welcome to MusterBank, how may I help you?",
		"Good day, this is MusterBank. What can I do for you?",
		"Hello, MusterBank support. How can I assist?",
	]

	agent_empathy_de = [
		"Ich verstehe, das ist ärgerlich.",
		"Danke für die Info, ich prüfe das sofort.",
		"Ich kümmere mich direkt darum.",
	]
	agent_empathy_en = [
		"I understand, that's frustrating.",
		"Thanks for the details, I'll check right away.",
		"I'll take care of this immediately.",
	]

	kb_tag_de = "Ich nutze kurz unseren Wissensartikel." if kb else ""
	kb_tag_en = "Let me quickly consult our KB article." if kb else ""

	def pick(arr: list[str]) -> str:
		return arr[rng.randrange(len(arr))]

	turn_min, turn_max = (16, 26) if channel == "voice" else (16, 26)
	n_turns = rng.randint(turn_min, turn_max)
	parts: list[str] = []


	# greeting
	if lang == "DE":
		parts.append(f"{voice[0]} {pick(agent_openers_de)}")
		parts.append(f"{voice[1]} {pick(customer_openers_de)}")
	else:
		parts.append(f"{voice[0]} {pick(agent_openers_en)}")
		parts.append(f"{voice[1]} {pick(customer_openers_en)}")

	# Main body with empathy/holds/transfers
	used_hold = 0
	used_transfers = 0
	for i in range(n_turns - 4):
		if i % 2 == 0:
			# Agent turn
			if lang == "DE":
				resp = pick(agent_empathy_de)
				if kb_tag_de and rng.random() < 0.3:
					resp += " " + kb_tag_de
			else:
				resp = pick(agent_empathy_en)
				if kb_tag_en and rng.random() < 0.3:
					resp += " " + kb_tag_en
			parts.append(f"{voice[0]} {resp}")
			# Optional hold
			if used_hold < hold_total and rng.random() < 0.35:
				slice_len = max(3, min(30, rng.randint(5, 1 + max(5, hold_total - used_hold))))
				used_hold += slice_len
				parts.append(f"[hold {slice_len}s]")
			# Optional transfer
			if used_transfers < transfers and rng.random() < 0.4:
				parts.append(f"{voice[0]} {('Ich verbinde Sie intern weiter…' if lang=='DE' else 'I will transfer you internally…')}")
				used_transfers += 1
				# small silence after transfer
				parts.append(f"[silence {rng.randint(2,5)}s]")
			# occasional silence
			if sil_total > 0 and rng.random() < (0.25 + (0 if nps>=7 else 0.15)):
				d = max(1, min(6, int(rng.uniform(1, min(6, sil_total)))))
				sil_total -= d
				parts.append(f"[silence {d}s]")
		else:
			# Customer turn
			if lang == "DE":
				cust_pool = [
					"Danke.",
					"Verstehe.",
					"Ich brauche das heute noch.",
					f"Können Sie {scenario.lower()} erklären?",
					"Das hilft, bitte weiter.",
					"Können wir das jetzt lösen?",
				]
			else:
				cust_pool = [
					"Thanks.",
					"I see.",
					"I need this resolved today.",
					f"Can you explain {scenario.lower()}?",
					"That helps, please continue.",
					"Can we resolve this now?",
				]
			parts.append(f"{voice[1]} {pick(cust_pool)}")

	# Summary and resolution
	if lang == "DE":
		parts.append(f"{voice[0]} Zusammenfassung: Anliegen zu {intent} / {scenario} bearbeitet.")
	else:
		parts.append(f"{voice[0]} Summary: handled the {intent} / {scenario} request.")

	if not fcr or esc != "None":
		if lang == "DE":
			parts.append(f"{voice[0]} Wir eskalieren an {esc}.")
		else:
			parts.append(f"{voice[0]} We will escalate to {esc}.")

	# Farewell
	if lang == "DE":
		parts.append(f"{voice[0]} Vielen Dank für Ihren Anruf bei der MusterBank. Auf Wiederhören.")
	else:
		parts.append(f"{voice[0]} Thank you for calling MusterBank. Goodbye.")

	# Add explicit one-line summary marker to feed header extraction
	if lang == "DE":
		parts.append(f"ZUSAMMENFASSUNG: Anliegen '{intent}' / Szenario '{scenario}' wurde behandelt.")
	else:
		parts.append(f"SUMMARY: Handled '{intent}' / scenario '{scenario}'.")

	# Deduplicate accidental consecutive repeats
	filtered: list[str] = []
	for line in parts:
		if not filtered or filtered[-1] != line:
			filtered.append(line)
	return "\n".join(filtered)



def main(in_dir: str = "out", out_dir: str = "out_conversations", api_key: str | None = None, model: str = "gpt-5-chat-latest", limit: int | None = None, locale: str | None = None) -> None:
	client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY") or DEFAULT_OPENAI_API_KEY)
	# Resolve locale-specific resources with fallback
	loc = (locale or os.getenv("GEN_LOCALE") or "").strip().lower()
	loc_dir = Path("locales") / loc if loc else None
	tmpl_path = (loc_dir / "prompt_template.json") if loc and (loc_dir / "prompt_template.json").exists() else TEMPLATE_PATH
	labels_path = (loc_dir / "labels.json") if loc and (loc_dir / "labels.json").exists() else LABELS_PATH
	value_labels_path = (loc_dir / "value_labels.json") if loc and (loc_dir / "value_labels.json").exists() else VALUE_LABELS_PATH

	template = load_json(tmpl_path)
	labels = load_json(labels_path) if labels_path.exists() else {"en": {}, "de": {}}
	global VALUE_LABELS_DATA
	VALUE_LABELS_DATA = load_json(value_labels_path) if value_labels_path.exists() else {"de": {}}
	in_root = Path(in_dir)
	out_root = Path(out_dir)
	out_root.mkdir(parents=True, exist_ok=True)

	call_files = sorted(in_root.rglob("*-*.json"))
	if limit is not None:
		call_files = call_files[: max(0, int(limit))]
	for path in call_files:
		call = load_json(path)
		prompt = render_prompt(template, call, preferred_locale=loc if loc else None)
		# Call LLM only; no local synthesis fallback
		path_used = "llm"
		try:
			dialog_text = generate_dialog(client, model, prompt)
		except Exception:
			dialog_text = ""
		if not dialog_text.strip():
			print(f"LLM returned empty output for: {path}", file=sys.stderr)
			continue

		# Ensure holds for voice calls when Hold_time > 0: attempt a minimal repair pass via LLM
		channel = str(call.get("channel", "voice")).strip().lower()
		hold_time_val = float(call.get("Hold_time", 0) or 0)
		if channel == "voice" and hold_time_val > 0 and "[hold " not in dialog_text:
			repair_prompt = (
				"Revise the transcript below to include [hold Xs] steps totalling roughly "
				+ str(int(round(hold_time_val)))
				+ "s inserted naturally between turns. Keep Agent:/Customer: prefixes and content; do not add silence tags. Output only the revised transcript.\n\n--- TRANSCRIPT ---\n"
				+ dialog_text
			)
			try:
				dialog_text_repaired = generate_dialog(client, model, repair_prompt)
				if dialog_text_repaired.strip() and "[hold " in dialog_text_repaired:
					dialog_text = dialog_text_repaired
			except Exception:
				pass

		# Localized header labels
		lang = str(call.get("language", "DE"))
		loc_header = (loc if (labels and loc in labels) else ("de" if lang == "DE" else "en")) if isinstance(labels, dict) else "en"
		L = labels.get(loc_header, {}) if isinstance(labels, dict) else {}
		def lab(k: str) -> str:
			return str(L.get(k, k))

		# Compose header with localized values when DE
		def V(k: str, v: Any) -> Any:
			return localize_value(loc_header, k, v)

		headers = [
			f"{lab('generator_path')}: {path_used}",
			f"{lab('language')}: {V('language', call.get('language'))}",
			f"{lab('channel')}: {call.get('channel')}",
			f"{lab('date')}: {call.get('date')}",
			f"{lab('weekday')}: {V('weekday', call.get('weekday'))}",
			f"{lab('time_of_day_bucket')}: {V('time_of_day_bucket', call.get('time_of_day_bucket'))}",
			f"{lab('agent_name')}: {call.get('agent_name')}",
			f"{lab('agent_shift')}: {V('agent_shift', call.get('agent_shift'))}",
			f"{lab('customer_segment')}: {V('customer_segment', call.get('customer_segment'))}",
			f"{lab('intent')}: {V('intent', call.get('intent'))}",
			f"{lab('scenario')}: {V('scenario', call.get('scenario'))}",
			f"{lab('AWT')}: {call.get('AWT')}",
			f"{lab('Hold_time')}: {call.get('Hold_time')}",
			f"{lab('Transfers_count')}: {call.get('Transfers_count')}",
			f"{lab('Silence_ratio')}: {call.get('Silence_ratio')}",
			f"{lab('Silence_total_seconds')}: {call.get('Silence_total_seconds')}",
			f"{lab('Interruptions_count')}: {call.get('Interruptions_count')}",
			f"{lab('FCR')}: {V('FCR', call.get('FCR'))}",
			f"{lab('repeat_call_within_72h')}: {V('repeat_call_within_72h', call.get('repeat_call_within_72h'))}",
			f"{lab('escalation')}: {V('escalation', call.get('escalation'))}",
			f"{lab('complaint_category')}: {V('complaint_category', call.get('complaint_category'))}",
			f"{lab('NPS_score')}: {call.get('NPS_score')}",
			f"{lab('sentiment_score')}: {call.get('sentiment_score')}",
			f"{lab('product')}: {V('product', call.get('product'))}",
			f"{lab('amount_bucket')}: {V('amount_bucket', call.get('amount_bucket'))}",
			f"{lab('self_service_potential')}: {V('self_service_potential', call.get('self_service_potential'))}",
			f"{lab('automation_action_present')}: {V('automation_action_present', call.get('automation_action_present'))}",
			f"{lab('automation_action_type')}: {V('automation_action_type', call.get('automation_action_type'))}",
			f"{lab('Greeting')}: {V('Greeting', call.get('compliance_flags',{}).get('Greeting'))}",
			f"{lab('Empathy')}: {V('Empathy', call.get('compliance_flags',{}).get('Empathy'))}",
			f"{lab('Summary')}: {V('Summary', call.get('compliance_flags',{}).get('Summary'))}",
			f"{lab('Farewell')}: {V('Farewell', call.get('compliance_flags',{}).get('Farewell'))}",
			f"{lab('kb_article_used')}: {V('kb_article_used', call.get('kb_article_used'))}",
			f"{lab('language_switch')}: {V('language_switch', call.get('language_switch'))}",
			f"{lab('pii_disclosure_flag')}: {V('pii_disclosure_flag', call.get('pii_disclosure_flag'))}",
			f"{lab('script_adherence')}: {call.get('script_adherence')}",
			f"{lab('ANI')}: {call.get('ANI')}",
		]
		content = "\n".join(headers) + "\n\n" + "---- DIALOGUE ----\n" + (dialog_text if dialog_text else "(no content)") + "\n"
		# filename: agentname_datetime.txt
		date = str(call.get("date"))
		time_suffix = infer_time_suffix(call)
		agent = str(call.get("agent_name"))
		ani_raw = str(call.get("ANI") or "")
		ani_clean = ani_raw.lstrip("+")
		filename = f"{agent}_{date.replace('-','')}{time_suffix}_{ani_clean}.txt"
		(out_root / filename).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate conversations from call JSONs using OpenAI GPT-5")
    parser.add_argument("--in", dest="in_dir", default="out", help="Input root directory with day folders")
    parser.add_argument("--out", dest="out_dir", default="out_conversations", help="Output directory for .txt")
    parser.add_argument("--api-key", dest="api_key", default=None, help="OpenAI API key (otherwise use OPENAI_API_KEY env var)")
    parser.add_argument("--model", dest="model", default="gpt-5-chat-latest", help="OpenAI model name")
    parser.add_argument("--limit", dest="limit", type=int, default=None, help="Limit number of calls to process")
    parser.add_argument("--locale", dest="locale", default=None, help="Preferred locale for templates and labels (e.g., en, de, fr)")
    args = parser.parse_args()
    main(args.in_dir, args.out_dir, args.api_key, args.model, args.limit, args.locale)
