## SA datasets Generator — Полное руководство

[English Version](README.md) | [Deutsche Version](README.de.md)

Это репозиторий для генерации синтетического набора данных контакт-центра: метаданные звонков, тексты диалогов, синтез аудио + таймлайнов JSON и загрузка в SA.

Состав пайплайна:
- Генерация метаданных (распределение по дням, агентам, сменам, часовым корзинам) в `out/`.
- Локализация заголовков/значений для заголовка диалога (EN/DE).
- Генерация текстовых диалогов LLM → `out_conversations/`.
- Синтез аудио и формирование `.wav.json` таймлайнов → `audio_and_json_generator/results/`.
- Загрузка в SA с корректной типизацией числовых полей.

### Требования
- Python 3.11+
- pip и virtualenv (рекомендуется)
- Для синтеза: интернет и валидный OpenAI API key
- Для чтения MP3-холда (если используете mp3), нужен ffmpeg. Для WAV холда ffmpeg не обязателен.

Установка зависимостей:
```bash
pip install -r requirements.txt
```

## 1) Генерация метаданных (распределение)
Модуль `generator/cli.py` строит календарь, объёмы, распределяет звонки по агентам/сменам/часам, и сохраняет по дням JSON-файлы в `out/ГГГГ-ММ-ДД/`.

Пример запуска:
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

Что получится:
- В `out/_meta/` сохранится эффективный конфиг, схема `schema_call.json`, описания полей и шаблон промпта.
- В `out/2025-09-01/` (и т. д.) — пофайлово JSON звонков; каждый соответствует одной записи согласно схеме.

Настройка распределения:
- Основные параметры заданы в `config/base.yml` и `config/overrides.yml`: объёмы, доли каналов, доли смен, состав агентов/команд, вероятности сценариев, KPI и т. п.
- Можно варьировать outages через `--outages N` (перекрывает overrides для инцидентов).

## 2) Схема и поля (что есть в метаданных)
Актуальная схема экспортируется в `out/_meta/schema_call.json` и определяется в `generator/schema.py`.

Ключевые типы:
- Строки: `call_id`, `date`, `weekday`, `time_of_day_bucket`, `agent_name`, `team`, `agent_shift`, `customer_segment`, `channel`, `language`, `region`, `device_type`, `intent`, `scenario`, `escalation`, `complaint_category`, `product`, `amount_bucket`, `ANI`.
- Числа с плавающей точкой: `AWT`, `Hold_time`, `Silence_ratio`, `Silence_total_seconds`, `sentiment_score`, `script_adherence`.
- Целые числа: `Transfers_count`, `Interruptions_count`, `NPS_score`.
- Булевы: `FCR`, `repeat_call_within_72h`, `automation_action_present`, `kb_article_used`, `language_switch`, `pii_disclosure_flag`.
- Объект: `compliance_flags` с полями `Greeting`, `Empathy`, `Summary`, `Farewell` (значения: `pass`/`fail`).

Описания полей на EN/DE сохраняются в `out/_meta/field_descriptions.json`.

## 3) Локализация/перевод (заголовки и значения)
Локализация управляется файлами:
- Глобальные дефолты: `config/labels.json` и `config/value_labels.json`.
- Переопределения по локали: кладите файлы в `locales/<lang>/`:
  - `locales/<lang>/prompt_template.json` (поддерживает ключи `prompt_<lang>`)
  - `locales/<lang>/labels.json`
  - `locales/<lang>/value_labels.json`

Как это работает в генерации диалогов:
- Скрипт `generator/generate_conversations.py` пишет `.txt` с «шапкой», где ключи/значения локализуются через эти файлы.
- Предпочтительная локаль промпта: `--locale <lang>` или переменная `GEN_LOCALE=<lang>`. Если не задано, берётся из `language` звонка.

Важно: язык теперь сэмплируется из весов конфига; принудительного EN нет. Настройте доли языков через `geo.language` в конфиге.

## 4) Генерация текстовых диалогов (LLM)
Скрипт читает JSON звонков из `out/` и для каждого генерирует `.txt` c заголовком и телом диалога.

Подготовка ключа:
```bash
$env:OPENAI_API_KEY="sk-..."   # PowerShell (Windows)
# или
export OPENAI_API_KEY="sk-..."  # bash/zsh
```

Запуск:
```bash
python generator/generate_conversations.py \
  --in out \
  --out out_conversations \
  --model gpt-5-chat-latest \
  --limit 100
```

Результат: файлы `Agent_YYYYMMDDHHMMSS_ANI.txt` в `out_conversations/` с шапкой и текстом диалога.

## 5) Аудио + JSON-таймлайны
Преобразование `.txt` → `.wav` + `.wav.json` делает `audio_and_json_generator/generate_audio_and_json.py`.

Рекомендации:
- В репозитории есть `audio_and_json_generator/hold.wav`. По умолчанию скрипт ждёт `hold.mp3`, поэтому укажите `--hold audio_and_json_generator/hold.wav`.
- Голоса: можно выбрать `--voice_female`, `--voice_male`, `--voice_customer` (поддерживаются: nova, shimmer, fable, coral, alloy, ash, onyx, echo, sage).

Примеры:
```bash
# Папка со всеми .txt
python audio_and_json_generator/generate_audio_and_json.py \
  --in_dir out_conversations \
  --out_dir audio_and_json_generator/results \
  --hold audio_and_json_generator/hold.wav

# Один файл .txt
python audio_and_json_generator/generate_audio_and_json.py \
  --in_file out_conversations/Anna_Ziegler_20250901114452_49065294508435.txt \
  --out_dir audio_and_json_generator/results \
  --hold audio_and_json_generator/hold.wav
```

Примечания:
- Для `channel=text` `.wav` не создаётся; но `.wav.json` создаётся.
- Значения шапки теперь парсятся и сохраняются типизированными (int/float/bool/str). Дублирование `_num` больше не требуется.

## 6) Загрузка в SA (типизированные числа)
`upload_to_SA/upload_from_results.py` отправляет пары `.wav` + `.wav.json` из `audio_and_json_generator/results`.

Настройка через CLI:
```bash
python upload_to_SA/upload_from_results.py \
  --dir audio_and_json_generator/results \
  --sa-url "https://<ваш-SA>/api/upload" \
  --project-id "<project>" \
  --pipeline-id "<pipeline>" \
  --dry-run
```
Через переменные окружения:
```bash
$env:SA_URL="https://<ваш-SA>/api/upload"
$env:SA_PROJECT_ID="<project>"
$env:SA_PIPELINE_ID="<pipeline>"
$env:SA_CONNECT_TIMEOUT="10"
$env:SA_READ_TIMEOUT="300"
```
Или правкой дефолтов в `upload_to_SA/upload_from_results.py`:
- `SA_URL_DEFAULT`, `PROJECT_ID_DEFAULT`, `PIPELINE_ID_DEFAULT`, `STORAGE_BACKEND_ID_DEFAULT`.

Состав payload:
- multipart с `storageBackendId`, `pipelineId`, `data` (JSON-строка), `indexName`, `channelMap` и файлами `stt_data` (ваш `.wav.json`) и опционально `audio`.
- `custom.*` — плоские простые поля из `C1`, без тяжёлых массивов.

Числовая типизация:
- Строки, похожие на числа, приводятся к числам; целые остаются целыми, дробные — дробными. Дубликаты `_num` больше не отправляются.

## 7) Важные особенности
- Детерминированность по `--seed`, «ремонт» hold-тегов, стереопанорама C1/C2, логика перекрытий.
- Аудиогенератор теперь парсит шапку как типизированные скаляры; загрузчик сохраняет типы без дубликатов `_num`.

## 8) Быстрая шпаргалка (end-to-end)
```bash
python -m generator.cli --start 2025-09-01 --end 2025-09-02 --out out --seed 42 --validate
python generator/generate_conversations.py --in out --out out_conversations --model gpt-5-chat-latest
python audio_and_json_generator/generate_audio_and_json.py --in_dir out_conversations --out_dir audio_and_json_generator/results --hold audio_and_json_generator/hold.wav
python upload_to_SA/upload_from_results.py --dir audio_and_json_generator/results --dry-run
```


