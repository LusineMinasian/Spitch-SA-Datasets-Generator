## SA datasets Generator — Vollständige Anleitung

[Русская версия](README.ru.md) | [English Version](README.en.md)

Dieses Repository erzeugt einen synthetischen Contact-Center-Datensatz: Anruf-Metadaten, Textdialoge, synthetisiertes Audio + JSON-Zeitachsen sowie einen Uploader zu SA.

Pipeline-Überblick:
- Generierung von Metadaten (Verteilung nach Tagen, Agents, Schichten, Tageszeit-Buckets) in `out/`.
- Lokalisierung von Kopfzeilen/ Werten (EN/DE).
- Generierung von Dialogen via LLM nach `out_conversations/`.
- Audiosynthese und `.wav.json`-Zeitachsen nach `audio_and_json_generator/results/`.
- Upload nach SA mit korrekter numerischer Typisierung.

### Anforderungen
- Python 3.11+
- pip und virtualenv (empfohlen)
- Internet und gültiger OpenAI API Key für Synthese
- ffmpeg nur nötig, wenn MP3-Holdmusik genutzt wird; WAV funktioniert ohne ffmpeg

Installation:
```bash
pip install -r requirements.txt
```

## 1) Metadaten generieren (Verteilung)
`generator/cli.py` erstellt Kalender, Volumina, Splits nach Agents/Schichten/Zeit-Buckets und speichert pro Tag JSON-Dateien in `out/JJJJ-MM-TT/`.

Beispiel:
```bash
python -m generator.cli \
  --start 2025-09-01 \
  --end 2025-09-03 \
  --out out \
  --seed 12345 \
  --validate \
  --config-base config/base.yml \
  --config-overrides config/overrides.yml
```

Ausgaben:
- `out/_meta/`: Effektive Konfiguration, `schema_call.json`, Feldbeschreibungen, Prompt-Template.
- `out/2025-09-01/`: Pro-Anruf JSONs gemäß Schema.

Feinabstimmung:
- Hauptparameter in `config/base.yml` und `config/overrides.yml` (Volumina, Kanalanteile, Schichten, Teamstruktur, Szenarien, KPIs ...).
- `--outages N` überschreibt schnell die Anzahl der Incidents im Kalender.

## 2) Schema und Felder
Das Schema liegt in `out/_meta/schema_call.json` (definiert in `generator/schema.py`).

Wichtige Typen:
- Strings: `call_id`, `date`, `weekday`, `time_of_day_bucket`, `agent_name`, `team`, `agent_shift`, `customer_segment`, `channel`, `language`, `region`, `device_type`, `intent`, `scenario`, `escalation`, `complaint_category`, `product`, `amount_bucket`, `ANI`.
- Fließkommazahlen: `AWT`, `Hold_time`, `Silence_ratio`, `Silence_total_seconds`, `sentiment_score`, `script_adherence`.
- Ganzzahlen: `Transfers_count`, `Interruptions_count`, `NPS_score`.
- Booleans: `FCR`, `repeat_call_within_72h`, `automation_action_present`, `kb_article_used`, `language_switch`, `pii_disclosure_flag`.
- Objekt: `compliance_flags` mit `Greeting`, `Empathy`, `Summary`, `Farewell` (`pass`/`fail`).

Feldbeschreibungen (EN/DE) stehen in `out/_meta/field_descriptions.json`.

## 3) Lokalisierung/Übersetzung
Lokalisierungsdateien:
- Globale Defaults: `config/labels.json` und `config/value_labels.json`.
- Locale-spezifische Overrides unter `locales/<lang>/`:
  - `locales/<lang>/prompt_template.json` (Schlüssel wie `prompt_<lang>`)
  - `locales/<lang>/labels.json`
  - `locales/<lang>/value_labels.json`

Bei der Dialoggenerierung:
- `generator/generate_conversations.py` schreibt eine Kopfzeile, in der Schlüssel/Werte über diese Dateien lokalisiert werden.
- Bevorzugte Prompt-Lokale: `--locale <lang>` oder Umgebungsvariable `GEN_LOCALE=<lang>`. Andernfalls Fallback auf `language` des Anrufs.

Hinweis: Die Sprache wird jetzt anhand von Konfigurationsgewichten gesampelt; kein erzwungenes EN. Konfigurieren Sie Sprachanteile unter `geo.language`.

## 4) Dialoge generieren (LLM)
Liest JSONs aus `out/` und erzeugt `.txt` mit lokalisierter Kopfzeile und Dialog.

API Key setzen:
```bash
# PowerShell (Windows)
$env:OPENAI_API_KEY="sk-..."
# bash/zsh
export OPENAI_API_KEY="sk-..."
```

Start:
```bash
python generator/generate_conversations.py \
  --in out \
  --out out_conversations \
  --model gpt-5-chat-latest \
  --limit 100
```

Ergebnis: `Agent_YYYYMMDDHHMMSS_ANI.txt` in `out_conversations/`.

## 5) Audio + JSON-Zeitachsen
Konvertiert `.txt` → `.wav` + `.wav.json` via `audio_and_json_generator/generate_audio_and_json.py`.

Tipps:
- Nutzen Sie das mitgelieferte Hold-WAV: `--hold audio_and_json_generator/hold.wav`.
- Stimmen: `--voice_female`, `--voice_male`, `--voice_customer` (nova, shimmer, fable, coral, alloy, ash, onyx, echo, sage).

Beispiele:
```bash
# Ordner mit .txt
python audio_and_json_generator/generate_audio_and_json.py \
  --in_dir out_conversations \
  --out_dir audio_and_json_generator/results \
  --hold audio_and_json_generator/hold.wav

# Einzelne .txt
python audio_and_json_generator/generate_audio_and_json.py \
  --in_file out_conversations/Anna_Ziegler_20250901114452_49065294508435.txt \
  --out_dir audio_and_json_generator/results \
  --hold audio_and_json_generator/hold.wav
```

Hinweise:
- Für `channel=text` wird `.wav` übersprungen, `.wav.json` dennoch erstellt.
- Kopfzeilenwerte werden jetzt typisiert nach `C1` übernommen (int/float/bool/str). Der Uploader nutzt diese Typen unmittelbar, ohne Duplikate.

## 6) Upload zu SA (typisierte Zahlen)
`upload_to_SA/upload_from_results.py` lädt Paare aus `audio_and_json_generator/results`.

Konfiguration via CLI:
```bash
python upload_to_SA/upload_from_results.py \
  --dir audio_and_json_generator/results \
  --sa-url "https://<Ihr-SA>/api/upload" \
  --project-id "<project>" \
  --pipeline-id "<pipeline>" \
  --dry-run
```
oder per Umgebungsvariablen:
```bash
$env:SA_URL="https://<Ihr-SA>/api/upload"
$env:SA_PROJECT_ID="<project>"
$env:SA_PIPELINE_ID="<pipeline>"
$env:SA_CONNECT_TIMEOUT="10"
$env:SA_READ_TIMEOUT="300"
```
oder Defaults in `upload_to_SA/upload_from_results.py` bearbeiten:
- `SA_URL_DEFAULT`, `PROJECT_ID_DEFAULT`, `PIPELINE_ID_DEFAULT`, `STORAGE_BACKEND_ID_DEFAULT`.

Payload:
- multipart mit `storageBackendId`, `pipelineId`, `data` (JSON-String), `indexName`, `channelMap`, Dateien `stt_data` (Ihr `.wav.json`) und optional `audio`.
- `custom.*` enthält flache Kopien einfacher Felder aus `C1`; schwere Arrays werden ausgelassen.

Numerische Typisierung:
- Numerisch aussehende Strings werden zu Zahlen geparst; Ganzzahlen bleiben Ganzzahlen, Fließkommazahlen bleiben Fließkommazahlen.
- `_num`-Duplikate werden nicht mehr gesendet.

## 7) Wichtige Skriptbesonderheiten
Highlights:
- Determinismus via `--seed`, Prompt-Reparatur für Holds, Stereo-Pan C1/C2, Überschneidungslogik, `dry-run` und Retries beim Upload.
- Audio-Generator parst Kopfzeilenwerte als typisierte Skalare; der Uploader übernimmt diese Typen ohne `_num`-Duplikate.

## 8) Schneller End-to-End-Ablauf
```bash
python -m generator.cli --start 2025-09-01 --end 2025-09-02 --out out --seed 42 --validate
python generator/generate_conversations.py --in out --out out_conversations --model gpt-5-chat-latest
python audio_and_json_generator/generate_audio_and_json.py --in_dir out_conversations --out_dir audio_and_json_generator/results --hold audio_and_json_generator/hold.wav
python upload_to_SA/upload_from_results.py --dir audio_and_json_generator/results --dry-run
```


