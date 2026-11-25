"""Generate YouTube Shorts titles, descriptions, and tags for SupoClip clips."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import requests


DEFAULT_CHANNEL = "@ByteMasala"
GEMINI_MODEL = "gemini-2.5-flash"


def load_env(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def fetch_clips_from_postgres(
    *, host: str, port: int, user: str, password: str, database: str, limit: int
) -> list[dict[str, Any]]:
    sql = (
        "SELECT COALESCE(json_agg(row_json), '[]'::json)::text "
        "FROM ("
        "  SELECT (to_jsonb(g) || jsonb_build_object('transcript', left(COALESCE(g.text, ''), 1200))) - 'text' AS row_json "
        "  FROM generated_clips g "
        f"  ORDER BY g.created_at DESC LIMIT {int(limit)}"
        ") t;"
    )
    env = dict(os.environ, PGPASSWORD=password)
    out = subprocess.check_output(
        [
            "psql",
            "-h",
            host,
            "-p",
            str(port),
            "-U",
            user,
            "-d",
            database,
            "-t",
            "-A",
            "-c",
            sql,
        ],
        env=env,
        text=True,
    ).strip()
    return json.loads(out or "[]")


def generate_metadata_with_gemini(
    clip: dict[str, Any], *, api_key: str, channel: str
) -> dict[str, Any]:
    prompt = f"""Generate YouTube Shorts upload metadata for this video clip.

Channel: {channel}
Filename: {clip.get("filename")}
Duration (sec): {clip.get("duration")}
Clip Hook Title: {clip.get("hook_title") or ""}
Mood Category: {clip.get("mood_category") or "other"}
Why it is engaging: {clip.get("reasoning") or ""}
Transcript:
{clip.get("transcript") or "(no transcript)"}

Return valid JSON only with these exact keys:
- "title": Catchy YouTube Shorts title under 90 characters, ending with #Shorts (match transcript language if Hindi/Hinglish or English).
- "description": 2-4 line engaging YouTube description mentioning {channel}, relevant emojis, and 5-7 hashtags including #Shorts.
- "tags": Array of 8-12 relevant YouTube search tags (lowercase strings).
"""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    resp = requests.post(
        url,
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(raw)


def format_markdown(items: list[dict[str, Any]]) -> str:
    lines = ["# YouTube Shorts Metadata\n"]
    for idx, item in enumerate(items, 1):
        meta = item["metadata"]
        tags = ", ".join(meta.get("tags") or [])
        lines.extend(
            [
                f"## {idx}. {item['filename']} ({item.get('duration', 0):.1f}s | Score: {item.get('virality_score', 0)})",
                f"**Title:** `{meta.get('title', '')}`\n",
                "**Description:**",
                "```text",
                meta.get("description", ""),
                "```\n",
                f"**Tags:** `{tags}`\n",
                "---\n",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--pg-user", default="postgres")
    parser.add_argument("--pg-password", default="postgres")
    parser.add_argument("--pg-db", default="supoclip")
    args = parser.parse_args()

    repo = Path(args.repo_root)
    env = load_env(repo / ".env")
    api_key = os.getenv("GOOGLE_API_KEY") or env.get("GOOGLE_API_KEY", "")
    if not api_key:
        print("Error: GOOGLE_API_KEY is not set in environment or .env", file=sys.stderr)
        return 1

    clips = fetch_clips_from_postgres(
        host=args.pg_host,
        port=args.pg_port,
        user=args.pg_user,
        password=args.pg_password,
        database=args.pg_db,
        limit=args.limit,
    )
    if not clips:
        print("No generated clips found in database.")
        return 0

    results = []
    for i, clip in enumerate(clips, 1):
        print(f"[{i}/{len(clips)}] Generating metadata for {clip['filename']}...")
        meta = generate_metadata_with_gemini(clip, api_key=api_key, channel=args.channel)
        results.append(
            {
                "filename": clip["filename"],
                "duration": clip.get("duration") or 0,
                "virality_score": clip.get("virality_score") or 0,
                "mood_category": clip.get("mood_category") or "",
                "metadata": meta,
            }
        )

    out_dir = repo / "backend" / "temp" / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "youtube_metadata.json"
    md_path = out_dir / "youtube_metadata.md"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    md_text = format_markdown(results)
    md_path.write_text(md_text, encoding="utf-8")
    print(f"\nSaved:\n- {md_path}\n- {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
