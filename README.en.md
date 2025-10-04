## SA datasets Generator — Complete Guide

[Русская версия](README.ru.md) | [Deutsche Version](README.de.md)

This repository generates a synthetic contact-center dataset: call metadata, textual dialogues, synthesized audio + JSON timelines, and an uploader to SA.

Pipeline overview:
- Generate call metadata (distributed by days, agents, shifts, and time buckets) into `out/`.
- Localize header labels/values (EN/DE).
- Generate dialogues via LLM into `out_conversations/`.
- Synthesize audio and produce `.wav.json` timelines into `audio_and_json_generator/results/`.
- Upload to SA with correct numeric typing.

### Requirements
- Python 3.11+
- pip and virtualenv (recommended)
- Internet and a valid OpenAI API key for synthesis
- ffmpeg needed only if you use MP3 hold music; WAV works without ffmpeg

Install dependencies:
```bash
pip install -r requirements.txt
```

## 1) Generate metadata (distribution)
`generator/cli.py` builds a calendar, volumes, splits by agents/shifts/time buckets, and writes per-day JSON files to `out/YYYY-MM-DD/`.

Example:
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

Outputs:
- `out/_meta/`: effective config, `schema_call.json`, field descriptions, prompt template.
- `out/2025-09-01/`: per-call JSON files compliant with the schema.

Tuning distribution:
- Main parameters are in `config/base.yml` and `config/overrides.yml` (volumes, channel shares, shifts, team structure, scenarios, KPIs...).
- `--outages N` quickly overrides incident count in the calendar.

## 2) Schema and fields
The schema is exported to `out/_meta/schema_call.json` (defined in `generator/schema.py`).

Key types:
- Strings: `call_id`, `date`, `weekday`, `time_of_day_bucket`, `agent_name`, `team`, `agent_shift`, `customer_segment`, `channel`, `language`, `region`, `device_type`, `intent`, `scenario`, `escalation`, `complaint_category`, `product`, `amount_bucket`, `ANI`.
- Floats: `AWT`, `Hold_time`, `Silence_ratio`, `Silence_total_seconds`, `sentiment_score`, `script_adherence`.
- Integers: `Transfers_count`, `Interruptions_count`, `NPS_score`.
- Booleans: `FCR`, `repeat_call_within_72h`, `automation_action_present`, `kb_article_used`, `language_switch`, `pii_disclosure_flag`.
- Object: `compliance_flags` with `Greeting`, `Empathy`, `Summary`, `Farewell` (`pass`/`fail`).

Field descriptions (EN/DE) are stored in `out/_meta/field_descriptions.json`.

## 3) Localization/translation
Localization files:
- Global defaults: `config/labels.json` and `config/value_labels.json`.
- Per-locale overrides in `locales/<lang>/`:
  - `locales/<lang>/prompt_template.json` (keys like `prompt_<lang>`)
  - `locales/<lang>/labels.json`
  - `locales/<lang>/value_labels.json`

In dialogue generation:
- `generator/generate_conversations.py` writes a header where keys/values are localized via those files.
- Preferred prompt locale can be set with `--locale <lang>` or `GEN_LOCALE=<lang>`. Otherwise, it falls back to the call’s `language`.

Note: language is now sampled from config weights; no forced EN. Configure language shares under `geo.language` in your config.

## 4) Generate dialogues (LLM)
Reads JSON calls from `out/` and produces `.txt` files with a localized header and the dialogue body.

Set API key:
```bash
# PowerShell (Windows)
$env:OPENAI_API_KEY="sk-..."
# bash/zsh
export OPENAI_API_KEY="sk-..."
```

Run:
```bash
python generator/generate_conversations.py \
  --in out \
  --out out_conversations \
  --model gpt-5-chat-latest \
  --limit 100
```

Output: `Agent_YYYYMMDDHHMMSS_ANI.txt` files in `out_conversations/`.

## 5) Audio + JSON timelines
Converts `.txt` → `.wav` + `.wav.json` via `audio_and_json_generator/generate_audio_and_json.py`.

Tips:
- Use the provided hold WAV: `--hold audio_and_json_generator/hold.wav`.
- Voices: `--voice_female`, `--voice_male`, `--voice_customer` (nova, shimmer, fable, coral, alloy, ash, onyx, echo, sage).

Examples:
```bash
# Directory with .txt files
python audio_and_json_generator/generate_audio_and_json.py \
  --in_dir out_conversations \
  --out_dir audio_and_json_generator/results \
  --hold audio_and_json_generator/hold.wav

# Single .txt
python audio_and_json_generator/generate_audio_and_json.py \
  --in_file out_conversations/Anna_Ziegler_20250901114452_49065294508435.txt \
  --out_dir audio_and_json_generator/results \
  --hold audio_and_json_generator/hold.wav
```

Notes:
- For `channel=text`, `.wav` is skipped; `.wav.json` is still produced.
- Header values are now parsed and stored as typed values (int/float/bool/str). No numeric duplication is needed downstream.

## 6) Upload to SA (typed numbers)
`upload_to_SA/upload_from_results.py` uploads `.wav` + `.wav.json` pairs from `audio_and_json_generator/results`.

Configure via CLI:
```bash
python upload_to_SA/upload_from_results.py \
  --dir audio_and_json_generator/results \
  --sa-url "https://<your-SA>/api/upload" \
  --project-id "<project>" \
  --pipeline-id "<pipeline>" \
  --dry-run
```
Or environment variables:
```bash
$env:SA_URL="https://<your-SA>/api/upload"
$env:SA_PROJECT_ID="<project>"
$env:SA_PIPELINE_ID="<pipeline>"
$env:SA_CONNECT_TIMEOUT="10"
$env:SA_READ_TIMEOUT="300"
```
Or by editing defaults in `upload_to_SA/upload_from_results.py`:
- `SA_URL_DEFAULT`, `PROJECT_ID_DEFAULT`, `PIPELINE_ID_DEFAULT`, `STORAGE_BACKEND_ID_DEFAULT`.

Payload details:
- multipart with `storageBackendId`, `pipelineId`, `data` (JSON string), `indexName`, `channelMap`, and files `stt_data` (your `.wav.json`) and optional `audio`.
- `custom.*` flattens simple fields from `C1`; heavy arrays are excluded.

Numeric typing:
- Numeric-looking strings are coerced to numbers; integers remain integers, floats remain floats. `_num` duplicates are no longer sent.

## 7) Important script nuances
Highlights:
- Determinism by `--seed`, prompt repair for holds, stereo panning C1/C2, overlap logic for interruptions.
- Audio generator now parses header values as typed scalars; uploader preserves types without `_num` duplication.

## 8) Quick end-to-end
```bash
python -m generator.cli --start 2025-09-01 --end 2025-09-02 --out out --seed 42 --validate
python generator/generate_conversations.py --in out --out out_conversations --model gpt-5-chat-latest
python audio_and_json_generator/generate_audio_and_json.py --in_dir out_conversations --out_dir audio_and_json_generator/results --hold audio_and_json_generator/hold.wav
python upload_to_SA/upload_from_results.py --dir audio_and_json_generator/results --dry-run
```


