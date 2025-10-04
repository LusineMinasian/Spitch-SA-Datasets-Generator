from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import jsonschema

CALL_SCHEMA: Dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "BankingCall",
	"type": "object",
	"required": [
		"call_id","date","weekday","time_of_day_bucket","agent_name","team","agent_shift",
		"customer_segment","channel","language","region","device_type",
		"intent","scenario",
		"AWT","Hold_time","Transfers_count","Silence_ratio","Interruptions_count",
		"FCR","repeat_call_within_72h","escalation","complaint_category",
		"NPS_score","sentiment_score",
		"self_service_potential","automation_action_present",
		"compliance_flags","script_adherence",
		"Silence_total_seconds"
	],
	"properties": {
		"call_id": {"type":"string","format":"uuid"},
		"date": {"type":"string","format":"date"},
		"weekday": {"type":"string","enum":["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]},
		"time_of_day_bucket": {"type":"string","enum":["Night","Morning","Afternoon","Evening"]},
		"agent_name": {"type":"string","enum":[
			"Monika_Mueller","Lukas_Schmidt","Anna_Ziegler","Peter_Keller",
			"Jasmin_Caggiano","Heidi_Vogt","Marco_Fischer","Laura_Brunner",
			"Karin_Herzog","Sven_Meier","Nina_Weber","Paul_Huber"
		]},
		"team": {"type":"string","enum":["Team A","Team B","Team C"]},
		"agent_shift": {"type":"string","enum":["Early","Mid","Late"]},
		"customer_segment": {"type":"string","enum":["Premium","Standard"]},
		"channel": {"type":"string","enum":["voice","text"]},
		"language": {"type":"string","pattern":"^[A-Za-z]{2}(-[A-Za-z]{2})?$"},
		"region": {"type":"string","enum":["ZH","BE","GE","VD","TI"]},
		"device_type": {"type":"string","enum":["iOS","Android","Desktop"]},
		"intent": {"type":"string"},
		"scenario": {"type":"string"},
		"AWT": {"type":"number","minimum":0},
		"Hold_time": {"type":"number","minimum":0},
		"Transfers_count": {"type":"integer","minimum":0,"maximum":3},
		"Silence_ratio": {"type":"number","minimum":0,"maximum":100},
		"Silence_total_seconds": {"type":"number","minimum":0},
		"Interruptions_count": {"type":"integer","minimum":0},
		"FCR": {"type":"boolean"},
		"repeat_call_within_72h": {"type":"boolean"},
		"escalation": {"type":"string","enum":["None","Supervisor","Backoffice","IT Ticket"]},
		"complaint_category": {"type":"string","enum":["WaitTime","Rude","WrongInfo","TechnicalIssue","Fees"]},
		"NPS_score": {"type":"integer","minimum":0,"maximum":10},
		"sentiment_score": {"type":"number","minimum":-1,"maximum":1},
		"product": {"type":["string","null"]},
		"amount_bucket": {
			"anyOf": [
				{"type":"string","enum":["<100","100–1000","1000–5000",">5000"]},
				{"type":"null"}
			]
		},
		"self_service_potential": {"type":"string","enum":["Low","Medium","High"]},
		"automation_action_present": {"type":"boolean"},
		"automation_action_type": {
			"anyOf": [
				{"type":"string","enum":["reset password","check balance","transfer status"]},
				{"type":"null"}
			]
		},
		"ANI": {"type":"string","pattern":"^\\+49\\d{9,12}$"},
		"compliance_flags": {
			"type":"object",
			"required":["Greeting","Empathy","Summary","Farewell"],
			"properties":{
				"Greeting":{"type":"string","enum":["pass","fail"]},
				"Empathy":{"type":"string","enum":["pass","fail"]},
				"Summary":{"type":"string","enum":["pass","fail"]},
				"Farewell":{"type":"string","enum":["pass","fail"]}
			}
		},
		"kb_article_used":{"type":"boolean"},
		"language_switch":{"type":"boolean"},
		"pii_disclosure_flag":{"type":"boolean"},
		"script_adherence":{"type":"number","minimum":0,"maximum":100}
	}
}


def validate_against_schema(call: Dict[str, Any]) -> None:
	jsonschema.validate(instance=call, schema=CALL_SCHEMA)


def save_schema(path: Path) -> None:
	import orjson
	path.write_bytes(orjson.dumps(CALL_SCHEMA, option=orjson.OPT_INDENT_2))


FIELD_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
	"call_id": {
		"en": "Unique identifier (UUID) of the call record.",
		"de": "Eindeutige Kennung (UUID) des Anrufsatzes."
	},
	"date": {
		"en": "Call date in ISO format (YYYY-MM-DD).",
		"de": "Anrufdatum im ISO-Format (JJJJ-MM-TT)."
	},
	"weekday": {
		"en": "Three-letter weekday of the call (Mon..Sun).",
		"de": "Wochentag des Anrufs (Mon..Sun)."
	},
	"time_of_day_bucket": {
		"en": "Time-of-day bucket: Night, Morning, Afternoon, or Evening.",
		"de": "Tageszeitfenster: Night, Morning, Afternoon oder Evening."
	},
	"agent_name": {
		"en": "Name of the handling agent.",
		"de": "Name des bearbeitenden Agents."
	},
	"team": {
		"en": "Agent team assignment.",
		"de": "Teamzugehörigkeit des Agents."
	},
	"agent_shift": {
		"en": "Shift during which the call was handled: Early, Mid, Late.",
		"de": "Schicht des Anrufs: Early, Mid, Late."
	},
	"customer_segment": {
		"en": "Customer segment (Premium or Standard).",
		"de": "Kundensegment (Premium oder Standard)."
	},
	"channel": {
		"en": "Interaction channel: voice (audio) or text (chat/messaging).",
		"de": "Kanal: voice (Audio) oder text (Chat/Nachrichten)."
	},
	"language": {
		"en": "Customer language (ISO 639-1 code).",
		"de": "Kundensprache (ISO 639-1 Code)."
	},
	"region": {
		"en": "Customer region/canton code.",
		"de": "Region/Kanton des Kunden."
	},
	"device_type": {
		"en": "Device type used by customer (iOS, Android, Desktop).",
		"de": "Vom Kunden genutztes Gerät (iOS, Android, Desktop)."
	},
	"intent": {
		"en": "Customer intent/topic of the contact.",
		"de": "Kundenanliegen/Thema des Kontakts."
	},
	"scenario": {
		"en": "Operational scenario describing the situation in the call.",
		"de": "Operatives Szenario, das die Situation im Anruf beschreibt."
	},
	"AWT": {
		"en": "Average waiting time in seconds.",
		"de": "Durchschnittliche Wartezeit in Sekunden."
	},
	"Hold_time": {
		"en": "Total time on hold in seconds.",
		"de": "Gesamte Haltezeit in Sekunden."
	},
	"Transfers_count": {
		"en": "Number of transfers within the call.",
		"de": "Anzahl der Weiterleitungen im Anruf."
	},
	"Silence_ratio": {
		"en": "Percentage of detected silence segments in the call (0–100).",
		"de": "Prozentsatz an Stille im Anruf (0–100)."
	},
	"Silence_total_seconds": {
		"en": "Total detected silence in seconds across the call.",
		"de": "Gesamte erkannte Stille in Sekunden im Anruf."
	},
	"Interruptions_count": {
		"en": "Number of agent/customer interruptions.",
		"de": "Anzahl der Unterbrechungen (Agent/Kunde)."
	},
	"FCR": {
		"en": "First Contact Resolution (true if resolved in this contact).",
		"de": "Erstlösungsquote (true, wenn im ersten Kontakt gelöst)."
	},
	"repeat_call_within_72h": {
		"en": "Customer contacted again within 72 hours.",
		"de": "Kunde kontaktierte erneut innerhalb von 72 Stunden."
	},
	"escalation": {
		"en": "Escalation level (None/Supervisor/Backoffice/IT Ticket).",
		"de": "Eskaltionsstufe (None/Supervisor/Backoffice/IT Ticket)."
	},
	"complaint_category": {
		"en": "Complaint type if expressed by customer.",
		"de": "Beschwerdekategorie (falls geäußert)."
	},
	"NPS_score": {
		"en": "Net Promoter Score from 0 to 10.",
		"de": "Net-Promoter-Score von 0 bis 10."
	},
	"sentiment_score": {
		"en": "Sentiment score in range [-1, 1].",
		"de": "Stimmungsscore im Bereich [-1, 1]."
	},
	"product": {
		"en": "Product relevant to the interaction (nullable).",
		"de": "Produkt im Kontext der Interaktion (nullable)."
	},
	"amount_bucket": {
		"en": "Amount bucket for financial operations (nullable).",
		"de": "Betragsklasse für Finanzoperationen (nullable)."
	},
	"self_service_potential": {
		"en": "Estimated potential for self-service: Low/Medium/High.",
		"de": "Eingeschätztes Self-Service-Potenzial: Low/Medium/High."
	},
	"automation_action_present": {
		"en": "Whether an automation action was present.",
		"de": "Ob eine Automationsaktion vorhanden war."
	},
	"automation_action_type": {
		"en": "Type of automation action if present (nullable).",
		"de": "Typ der Automationsaktion (falls vorhanden, nullable)."
	},
	"ANI": {
		"en": "Automatic Number Identification (E.164).",
		"de": "Automatic Number Identification (E.164)."
	},
	"compliance_flags": {
		"en": "Compliance checks per stage: Greeting/Empathy/Summary/Farewell.",
		"de": "Compliance-Prüfungen pro Phase: Greeting/Empathy/Summary/Farewell."
	},
	"kb_article_used": {
		"en": "Whether a knowledge base article was used.",
		"de": "Ob ein Wissensdatenbank-Artikel genutzt wurde."
	},
	"language_switch": {
		"en": "Whether a language switch occurred during the call.",
		"de": "Ob ein Sprachwechsel während des Anrufs stattfand."
	},
	"pii_disclosure_flag": {
		"en": "Whether personally identifiable information was disclosed.",
		"de": "Ob personenbezogene Daten offengelegt wurden."
	},
	"script_adherence": {
		"en": "Script adherence percentage (0–100).",
		"de": "Skripttreue in Prozent (0–100)."
	},
}


def save_field_descriptions(path: Path) -> None:
	import orjson
	path.write_bytes(orjson.dumps(FIELD_DESCRIPTIONS, option=orjson.OPT_INDENT_2))


PROMPT_TEMPLATE: Dict[str, Any] = {
	"placeholders": [
		"date","weekday","time_of_day_bucket","channel","language","region",
		"agent_name","agent_shift","customer_segment",
		"intent","scenario",
		"AWT","Hold_time","Transfers_count","Silence_ratio","Silence_total_seconds","Interruptions_count",
		"FCR","repeat_call_within_72h","escalation","complaint_category",
		"NPS_score","sentiment_score",
		"product","amount_bucket",
		"self_service_potential","automation_action_present","automation_action_type",
		"compliance_flags.Greeting","compliance_flags.Empathy","compliance_flags.Summary","compliance_flags.Farewell",
		"kb_article_used","language_switch","pii_disclosure_flag","script_adherence","ANI"
	],
	"prompt_en": """
You are a conversation generator for MusterBank (a Swiss retail bank). Produce a realistic, topic-focused transcript based on the metadata below.
Quality requirements (critical):
- Be specific: reflect intent {{intent}} and scenario {{scenario}} with concrete banking steps (authentication without PII, clarifying questions, next actions, confirmation).
- Natural variation: avoid repeating the same sentences; vary wording and sentence length; include mild disfluencies sparingly.
- Structure: greeting → clarification → investigation (with [hold {{duration}}s] if needed) → resolution or escalation → summary → farewell.
- Channel style: {{channel}}. For voice, use spoken turns; for text, short chat messages.
- Length: 15–25 turns for voice; 14–24 messages for text.
- Silence: distribute [silence Xs] between turns to roughly sum to {{Silence_total_seconds}} (each 1–6s; more if NPS is low or scenario difficult).
- KPIs: reflect AWT={{AWT}} via initial [wait {{AWT}}s]; include [hold Xs] totalling ~{{Hold_time}}; if Transfers_count>0, insert a transfer moment; use Interruptions_count to influence overlap tone (without explicit overlaps in text).
- Compliance flags: Greeting={{compliance_flags.Greeting}}, Empathy={{compliance_flags.Empathy}}, Summary={{compliance_flags.Summary}}, Farewell={{compliance_flags.Farewell}} — make them evident in the dialogue.
- Safety: no real account numbers or PII. ANI={{ANI}} may be mentioned as caller ID only.
- Tone: align to {{customer_segment}} and sentiment {{sentiment_score}} (from NPS={{NPS_score}}). If FCR={{FCR}}=false or escalation={{escalation}}≠None, include an escalation consistent with {{escalation}}.
- Product context (if present): {{product}} {{amount_bucket}}. Region {{region}}.
Output:
- Only the transcript lines prefixed with "Agent:" and "Customer:" (for text, same prefixes). Include [silence Xs] and [hold Xs] where appropriate.
- Begin with "[wait {{AWT}}s]" before the first human line.
""".strip(),
	"prompt_de": """
Du bist ein Generator für Gespräche der MusterBank (Schweizer Retailbank). Erzeuge ein realistisches, themenbezogenes Transkript basierend auf den Metadaten.
Qualitätsanforderungen (wichtig):
- Konkretheit: Anliegen {{intent}} und Szenario {{scenario}} mit konkreten Bankschritten (Authentifizierung ohne PII, Klärungsfragen, nächste Schritte, Bestätigung).
- Natürliche Variation: Wiederholungen vermeiden; Formulierungen und Satzlängen variieren; dezente Füllwörter sparsam.
- Struktur: Begrüßung → Klärung → Bearbeitung (mit [hold {{duration}}s] falls nötig) → Lösung oder Eskalation → Zusammenfassung → Verabschiedung.
- Kanalstil: {{channel}}. Bei voice gesprochene Turns; bei text kurze Chat-Nachrichten.
- Länge: 15–25 Turns (voice); 14–24 Nachrichten (text).
- Stille: [silence Xs] zwischen Turns verteilen, insgesamt etwa {{Silence_total_seconds}} (je 1–6s; mehr bei niedrigem NPS oder schwierigem Szenario).
- KPIs: AWT={{AWT}} via "[wait {{AWT}}s]"; [hold Xs] insgesamt ~{{Hold_time}}; bei Transfers_count>0 Transfermoment einbauen; Interruptions_count beeinflusst Ton (ohne echte Überschneidungen im Text).
- Compliance: Greeting={{compliance_flags.Greeting}}, Empathy={{compliance_flags.Empathy}}, Summary={{compliance_flags.Summary}}, Farewell={{compliance_flags.Farewell}} deutlich erkennbar machen.
- Sicherheit: keine echten Kontonummern oder PII. ANI={{ANI}} nur als Anrufer-ID erwähnen.
- Ton: an {{customer_segment}} und Stimmung {{sentiment_score}} (aus NPS={{NPS_score}}) anpassen. Wenn FCR={{FCR}} false oder escalation={{escalation}}≠None, passende Eskalation einbauen.
- Produktkontext (falls vorhanden): {{product}} {{amount_bucket}}. Region {{region}}.
Ausgabe:
- Nur Transkriptzeilen mit Präfix "Agent:" und "Customer:" (für text ebenso). Füge [silence Xs] und [hold Xs] passend ein.
- Beginne mit "[wait {{AWT}}s]" vor der ersten Zeile.
""".strip()
}


def save_prompt_template(path: Path) -> None:
	import orjson
	path.write_bytes(orjson.dumps(PROMPT_TEMPLATE, option=orjson.OPT_INDENT_2))
