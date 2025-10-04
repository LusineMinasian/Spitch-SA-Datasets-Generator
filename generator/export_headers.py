import argparse
import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

import orjson

LABELS_PATH = Path("config/labels.json")


def load_json(path: Path) -> Any:
    return orjson.loads(path.read_bytes())


def save_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def infer_time_suffix(call: Dict[str, Any]) -> str:
    bucket = str(call.get("time_of_day_bucket", ""))
    seed_bytes = repr((call.get("date"), call.get("agent_name"), bucket, call.get("call_id"))).encode("utf-8")
    seed = int.from_bytes(hashlib.blake2b(seed_bytes, digest_size=8).digest(), "big")
    # Simple deterministic HH:MM:SS within reasonable spread
    h = 12 + (seed % 8)  # 12..19
    m = (seed // 7) % 60
    s = (seed // 13) % 60
    return f"{h:02d}{m:02d}{s:02d}"


def label_map(language: str) -> Dict[str, str]:
    labels = load_json(LABELS_PATH) if LABELS_PATH.exists() else {"en": {}, "de": {}}
    loc = "de" if language == "DE" else "en"
    return labels.get(loc, {})


def lab(L: Dict[str, str], k: str) -> str:
    return str(L.get(k, k))


def export_headers_for_day(in_dir: Path, out_dir: Path) -> int:
    count = 0
    for call_path in sorted(in_dir.glob("*.json")):
        call = load_json(call_path)
        lang = str(call.get("language", "DE"))
        L = label_map(lang)

        headers = [
            f"{lab(L,'generator_path')}: synth",
            f"{lab(L,'language')}: {call.get('language')}",
            f"{lab(L,'channel')}: {call.get('channel')}",
            f"{lab(L,'date')}: {call.get('date')}",
            f"{lab(L,'weekday')}: {call.get('weekday')}",
            f"{lab(L,'time_of_day_bucket')}: {call.get('time_of_day_bucket')}",
            f"{lab(L,'agent_name')}: {call.get('agent_name')}",
            f"{lab(L,'agent_shift')}: {call.get('agent_shift')}",
            f"{lab(L,'customer_segment')}: {call.get('customer_segment')}",
            f"{lab(L,'intent')}: {call.get('intent')}",
            f"{lab(L,'scenario')}: {call.get('scenario')}",
            f"{lab(L,'AWT')}: {call.get('AWT')}",
            f"{lab(L,'Hold_time')}: {call.get('Hold_time')}",
            f"{lab(L,'Transfers_count')}: {call.get('Transfers_count')}",
            f"{lab(L,'Silence_ratio')}: {call.get('Silence_ratio')}",
            f"{lab(L,'Silence_total_seconds')}: {call.get('Silence_total_seconds')}",
            f"{lab(L,'Interruptions_count')}: {call.get('Interruptions_count')}",
            f"{lab(L,'FCR')}: {call.get('FCR')}",
            f"{lab(L,'repeat_call_within_72h')}: {call.get('repeat_call_within_72h')}",
            f"{lab(L,'escalation')}: {call.get('escalation')}",
            f"{lab(L,'complaint_category')}: {call.get('complaint_category')}",
            f"{lab(L,'NPS_score')}: {call.get('NPS_score')}",
            f"{lab(L,'sentiment_score')}: {call.get('sentiment_score')}",
            f"{lab(L,'product')}: {call.get('product')}",
            f"{lab(L,'amount_bucket')}: {call.get('amount_bucket')}",
            f"{lab(L,'self_service_potential')}: {call.get('self_service_potential')}",
            f"{lab(L,'automation_action_present')}: {call.get('automation_action_present')}",
            f"{lab(L,'automation_action_type')}: {call.get('automation_action_type')}",
            f"{lab(L,'Greeting')}: {call.get('compliance_flags',{}).get('Greeting')}",
            f"{lab(L,'Empathy')}: {call.get('compliance_flags',{}).get('Empathy')}",
            f"{lab(L,'Summary')}: {call.get('compliance_flags',{}).get('Summary')}",
            f"{lab(L,'Farewell')}: {call.get('compliance_flags',{}).get('Farewell')}",
            f"{lab(L,'kb_article_used')}: {call.get('kb_article_used')}",
            f"{lab(L,'language_switch')}: {call.get('language_switch')}",
            f"{lab(L,'pii_disclosure_flag')}: {call.get('pii_disclosure_flag')}",
            f"{lab(L,'script_adherence')}: {call.get('script_adherence')}",
            f"{lab(L,'ANI')}: {call.get('ANI')}",
        ]
        content = "\n".join(headers) + "\n\n" + "---- DIALOGUE ----\n(metadata only)\n"

        dt = str(call.get("date"))
        agent = str(call.get("agent_name"))
        ani_raw = str(call.get("ANI") or "")
        ani_clean = ani_raw.lstrip("+")
        time_suffix = infer_time_suffix(call)
        filename = f"{agent}_{dt.replace('-','')}{time_suffix}_{ani_clean}.txt"
        save_text(out_dir / filename, content)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Export header-only conversation files with localized labels")
    parser.add_argument("--in", dest="in_root", default="out", help="Root directory with daily call JSONs")
    parser.add_argument("--out", dest="out_dir", default="out_conversations", help="Output directory for .txt")
    parser.add_argument("--start", dest="start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", dest="end", required=True, help="End date YYYY-MM-DD (inclusive)")
    args = parser.parse_args()

    in_root = Path(args.in_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    y1, m1, d1 = map(int, args.start.split("-"))
    y2, m2, d2 = map(int, args.end.split("-"))
    cur = date(y1, m1, d1)
    end = date(y2, m2, d2)

    total = 0
    while cur <= end:
        day_dir = in_root / cur.isoformat()
        if day_dir.exists():
            total += export_headers_for_day(day_dir, out_dir)
        cur += timedelta(days=1)

    print(f"Exported {total} header files to {out_dir}")


if __name__ == "__main__":
    main()


