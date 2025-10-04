#!/usr/bin/env python3

import argparse
import datetime
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Iterable, Tuple

import requests
import urllib3
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


SA_URL_DEFAULT = 'ADD_YOUR_SA_URL_HERE'
PROJECT_ID_DEFAULT = 'ADD_YOUR_PROJECT_ID_HERE'
PIPELINE_ID_DEFAULT = 'ADD_YOUR_PIPELINE_ID_HERE'
STORAGE_BACKEND_ID_DEFAULT = 'ADD_YOUR_STORAGE_BACKEND_ID_HERE'


FILENAME_RE = re.compile(r'^(?P<agent>[A-Za-z]+_[A-Za-z]+)_(?P<ts>\d{14})_(?P<ani>\d+)\.wav$')


def parse_filename(fname: str) -> Tuple[str, str, str]:
    m = FILENAME_RE.match(Path(fname).name)
    if not m:
        raise ValueError(f"Unexpected filename format: {fname}")
    return m.group('agent'), m.group('ts'), m.group('ani')


def ts_yyyymmddhhmmss_to_iso(ts: str) -> str:
    dt = datetime.datetime.strptime(ts, "%Y%m%d%H%M%S")
    return datetime.datetime.strftime(dt, "%Y-%m-%dT%H:%M:%SZ")


def clean_ani(ani: str) -> str:
    # Keep leading + and digits, otherwise digits only
    if ani.startswith('+'):
        return '+' + re.sub(r'\D', '', ani)
    return re.sub(r'\D', '', ani)


def agent_display_name(agent_name: str) -> str:
    return agent_name.replace('_', ' ')


def load_json(path: Path) -> Dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def infer_team_by_agent(out_root: Path) -> Dict[str, str]:
    """
    Build a mapping {agent_name -> team} by scanning small subset first, then broader 'out' dir if needed.
    """
    mapping: Dict[str, str] = {}

    def scan_dir(d: Path, limit: int = 200) -> None:
        count = 0
        if not d.exists():
            return
        for p in d.rglob('*.json'):
            try:
                with p.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                agent = data.get('agent_name')
                team = data.get('team')
                if isinstance(agent, str) and isinstance(team, str) and agent not in mapping:
                    mapping[agent] = team
                count += 1
                if count >= limit:
                    break
            except Exception:
                continue

    # Prefer the small subset
    scan_dir(out_root.parent / 'out_subset', limit=500)
    # Fallback to the main out dir
    if not mapping:
        scan_dir(out_root, limit=2000)
    return mapping


def flatten_for_custom(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract lightweight fields for custom.* from our result JSON.
    We take top-level of C1 except heavy transcript arrays.
    """
    out: Dict[str, Any] = {}
    c1 = data.get('C1', {})
    if isinstance(c1, dict):
        for key, value in c1.items():
            if key == 'metadata':
                # Skip heavy arrays like smoothed
                continue
            # Coerce numeric-looking strings to proper int/float; keep native types
            if isinstance(value, str):
                v = value.strip()
                # Prefer int when possible
                if re.fullmatch(r"[-]?\d+", v):
                    try:
                        out[key] = int(v)
                        continue
                    except Exception:
                        pass
                if re.fullmatch(r"[-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", v):
                    try:
                        out[key] = float(v)
                        continue
                    except Exception:
                        pass
            if isinstance(value, (str, int, float, bool)):
                out[key] = value
        # Do not derive or include call_summary
    return out


def derive_ts_compact_from_json_or_mtime(json_path: Path, c1: Dict[str, Any]) -> str:
    # Try direct keys first
    for key in ("ts_compact", "ts", "start_ts", "start_time_compact", "start_time"):
        val = c1.get(key)
        if isinstance(val, str) and re.fullmatch(r"\d{14}", val):
            return val
    # Search any string field for a 14-digit timestamp
    for v in c1.values():
        if isinstance(v, str):
            m = re.search(r"(\d{14})", v)
            if m:
                return m.group(1)
    # Fallback to file mtime
    dt = datetime.datetime.utcfromtimestamp(json_path.stat().st_mtime)
    return datetime.datetime.strftime(dt, "%Y%m%d%H%M%S")


def build_payload(
    session_id: str,
    start_ts_compact: str,
    ani: str,
    operator_name: str,
    group_name: str | None,
    channel_value: str | None,
    original_filename: str,
    custom_fields: Dict[str, Any],
    project_id: str,
    pipeline_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    direction = "in"
    disconnect_reason = "far_hangup"

    data_dict: Dict[str, Any] = {
        "session_id": session_id,
        "start_date": ts_yyyymmddhhmmss_to_iso(start_ts_compact),
        "ani": ani,
        "direction": direction,
        "disconnect_reason": disconnect_reason,
        "segments.call_center_attributes.operator": operator_name,
        "segments.call_center_attributes.operator_name": operator_name,
        "original_filename": original_filename,
    }

    if group_name:
        data_dict["segments.call_center_attributes.group"] = group_name
        data_dict["segments.call_center_attributes.group_name"] = group_name

    # Channel: keep as provided (voice/text) when known
    if channel_value:
        data_dict["channel"] = channel_value

    # Attach remaining fields under custom.*
    for k, v in custom_fields.items():
        data_dict[f"custom.{k}"] = v

    up_data = {
        'storageBackendId': STORAGE_BACKEND_ID_DEFAULT,
        'pipelineId': pipeline_id,
        'data': json.dumps(data_dict, ensure_ascii=False).encode('utf8'),
        'indexName': project_id,
        'channelMap': [],
    }

    return data_dict, up_data


def iter_pairs(results_dir: Path) -> Iterable[Tuple[Path | None, Path]]:
    # Iterate by JSON to support text-only uploads (no audio)
    for j in sorted(results_dir.glob('*.wav.json')):
        wav_candidate = j.with_suffix('')  # strip .json -> .wav
        wav_path = wav_candidate if wav_candidate.exists() else None
        yield wav_path, j


def upload_pair(
    wav_path: Path | None,
    json_path: Path,
    agent_to_team: Dict[str, str],
    sa_url: str,
    project_id: str,
    pipeline_id: str,
    dry_run: bool = False,
    connect_timeout: float = 10.0,
    read_timeout: float = 300.0,
) -> int:
    # Derive base name like *.wav from the json filename
    base_wav_name = Path(json_path.name[:-5])  # remove trailing .json
    data = load_json(json_path)

    c1 = data.get('C1', {}) if isinstance(data, dict) else {}

    agent_from_json = c1.get('agent_name') if isinstance(c1, dict) else None
    agent_from_name = None
    ani_from_name = None
    ts_from_name = None
    try:
        parsed_agent, parsed_ts, parsed_ani = parse_filename(base_wav_name.name)
        agent_from_name, ts_from_name, ani_from_name = parsed_agent, parsed_ts, parsed_ani
    except Exception:
        pass
    agent = str(agent_from_json or agent_from_name or c1.get('agent') or c1.get('operator') or 'Unknown_Agent')
    operator_name = agent_display_name(agent)

    # ANI: prefer JSON
    ani_json = (c1.get('ANI') or c1.get('ani') or c1.get('caller') or c1.get('from')) if isinstance(c1, dict) else None
    ani_source = str(ani_json) if ani_json else (ani_from_name or '')
    ani = clean_ani(ani_source)

    channel = c1.get('channel') if isinstance(c1, dict) else None
    team = agent_to_team.get(agent)

    # Timestamp compact
    ts_compact = ts_from_name or derive_ts_compact_from_json_or_mtime(json_path, c1 if isinstance(c1, dict) else {})

    # Session id: use filename stem to preserve uniqueness
    session_id = base_wav_name.stem

    custom_fields = flatten_for_custom(data)

    # Decide channel to send
    channel_value = str(channel) if channel else ("voice" if wav_path else None)

    data_dict, up_data = build_payload(
        session_id=session_id,
        start_ts_compact=ts_compact,
        ani=ani,
        operator_name=operator_name,
        group_name=team,
        channel_value=channel_value,
        original_filename=base_wav_name.name,
        custom_fields=custom_fields,
        project_id=project_id,
        pipeline_id=pipeline_id,
    )

    files: Dict[str, Any] = {
        'stt_data': json_path.open('rb'),
    }
    if wav_path and channel_value != 'text':
        files['audio'] = wav_path.open('rb')

    if dry_run:
        # Close opened files immediately in dry-run
        print(f"DRY-RUN: {base_wav_name.name} => start_date={data_dict.get('start_date')} ani={data_dict.get('ani')} operator={data_dict.get('segments.call_center_attributes.operator')} group={data_dict.get('segments.call_center_attributes.group', '')} channel={data_dict.get('channel', '')} with_audio={bool('audio' in files)}")
        for f in files.values():
            try:
                f.close()
            except Exception:
                pass
        return 200

    try:
        response = requests.post(sa_url, data=up_data, files=files, verify=False, timeout=(connect_timeout, read_timeout))
        status = response.status_code
    finally:
        for f in files.values():
            try:
                f.close()
            except Exception:
                pass
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description='Upload wav + json pairs from results to SA')
    parser.add_argument('--dir', default=str(Path('audio_and_json_generator') / 'results'), help='Directory with .wav and .wav.json')
    parser.add_argument('--sa-url', default=os.getenv('SA_URL', SA_URL_DEFAULT))
    parser.add_argument('--project-id', default=os.getenv('SA_PROJECT_ID', PROJECT_ID_DEFAULT))
    parser.add_argument('--pipeline-id', default=os.getenv('SA_PIPELINE_ID', PIPELINE_ID_DEFAULT))
    parser.add_argument('--limit', type=int, default=0, help='Upload at most N files (0 = no limit)')
    parser.add_argument('--dry-run', action='store_true', help='Do not POST, just validate and print')
    parser.add_argument('--connect-timeout', type=float, default=float(os.getenv('SA_CONNECT_TIMEOUT', 10)), help='Connect timeout seconds')
    parser.add_argument('--read-timeout', type=float, default=float(os.getenv('SA_READ_TIMEOUT', 300)), help='Read timeout seconds')
    parser.add_argument('--retries', type=int, default=3, help='Retries per file on network/HTTP failure')
    parser.add_argument('--sleep-between', type=float, default=2.0, help='Seconds to sleep between retries')
    parser.add_argument('--log-dir', type=str, default=str(Path('upload_to_SA') / 'logs'), help='Directory for success/failure logs')
    parser.add_argument('--reverse', action='store_true', help='Process files in reverse order')
    args = parser.parse_args()

    results_dir = Path(args.dir)
    if not results_dir.exists():
        raise SystemExit(f"Directory not found: {results_dir}")

    agent_to_team = infer_team_by_agent(Path('out'))

    # Prepare logging
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts_log = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    successes: list[str] = []
    failures: list[tuple[str, str]] = []

    # Build ordered list of JSONs with optional reverse
    json_paths = sorted(results_dir.glob('*.wav.json'), reverse=bool(args.reverse))

    count = 0
    ok = 0
    for json_path in json_paths:
        wav_candidate = json_path.with_suffix('')
        wav_path = wav_candidate if wav_candidate.exists() else None
        base_name = json_path.name[:-5]
        try:
            last_error: str | None = None
            status: int | None = None
            for attempt in range(1, max(1, args.retries) + 1):
                try:
                    status = upload_pair(
                        wav_path=wav_path,
                        json_path=json_path,
                        agent_to_team=agent_to_team,
                        sa_url=args.sa_url,
                        project_id=args.project_id,
                        pipeline_id=args.pipeline_id,
                        dry_run=args.dry_run,
                        connect_timeout=args.connect_timeout,
                        read_timeout=args.read_timeout,
                    )
                    if status in (200, 201, 202):
                        ok += 1
                        successes.append(base_name)
                        break
                    else:
                        last_error = f"HTTP {status}"
                except Exception as e:
                    last_error = str(e)
                if attempt < max(1, args.retries):
                    time.sleep(max(0.0, args.sleep_between))
            count += 1
            if status not in (200, 201, 202):
                print(f"Upload failed for {base_name}: {last_error}")
                failures.append((base_name, last_error or 'unknown error'))
        except Exception as e:
            print(f"Error processing {base_name}: {e}")
            failures.append((base_name, str(e)))

        if args.limit and count >= args.limit:
            break

    # Write logs
    succ_path = log_dir / f'success_{ts_log}.txt'
    fail_path = log_dir / f'failures_{ts_log}.txt'
    try:
        if successes:
            succ_path.write_text("\n".join(successes), encoding='utf-8')
        if failures:
            fail_path.write_text("\n".join(f"{name}\t{reason}" for name, reason in failures), encoding='utf-8')
    except Exception:
        pass

    if args.dry_run:
        print(f"Validated {count} pairs (dry-run)")
    else:
        print(f"Uploaded {ok}/{count} files. Failures: {len(failures)}. Logs: {succ_path} ; {fail_path}")


if __name__ == '__main__':
    main()


