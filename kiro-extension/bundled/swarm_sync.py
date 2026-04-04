#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
"""
Team Swarm Sync — Phase 1 feature (requires team mode).

Pushes distilled skill_opportunity strings from your local insights DB
to a shared S3 bucket so teammates inherit your best patterns.
Pulls skills from teammates into your local DB.

PRIVACY: This feature is ONLY active when mode.type = "team" in config.toml
and the user has explicitly configured an S3 bucket. It is completely
disabled in the default BYOK solo mode. Only skill_opportunity strings
are synced — never raw transcripts, source code, or API keys.

Usage:
  python3 swarm_sync.py --push    # push your distilled skills to team
  python3 swarm_sync.py --pull    # pull teammates' skills to local DB
  python3 swarm_sync.py --status  # show sync state
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"


def load_config() -> dict:
    config_path = Path.home() / ".kernora" / "config.toml"
    if not config_path.exists():
        return {}
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def require_team_mode(cfg: dict) -> bool:
    """Swarm sync only runs when the user has explicitly opted into team mode."""
    mode = cfg.get("mode", {}).get("type", "byok")
    if mode != "team":
        print(
            "⛔  Swarm sync is a team-mode feature.\n"
            "    Your current mode is: byok (solo — zero data leaves your machine)\n\n"
            "    To enable team sync, edit ~/.kernora/config.toml:\n"
            "      [mode]\n"
            "      type = \"team\"\n\n"
            "      [team]\n"
            "      s3_bucket = \"your-org-kernora-skills\"\n"
            "      s3_region  = \"us-east-1\""
        )
        return False
    bucket = cfg.get("team", {}).get("s3_bucket", "")
    if not bucket:
        print("⛔  team.s3_bucket is not set in ~/.kernora/config.toml")
        return False
    return True


def get_s3_client(cfg: dict):
    import boto3
    region = cfg.get("team", {}).get("s3_region", "us-east-1")
    return boto3.client("s3", region_name=region)


def push_to_swarm(cfg: dict):
    """Push locally distilled skills to the team S3 bucket."""
    if not require_team_mode(cfg):
        return

    bucket = cfg.get("team", {}).get("s3_bucket")
    s3 = get_s3_client(cfg)

    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT session_id, summary, skill_opportunity FROM insights "
            "WHERE skill_opportunity IS NOT NULL AND skill_opportunity != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        print("❌  DB not initialized. Run: python3 db.py")
        conn.close()
        return

    pushed = 0
    for r in rows:
        # Only sync the distilled skill — never the raw transcript
        payload = {
            "session_id": r["session_id"],
            "summary": r["summary"],
            "skill_opportunity": r["skill_opportunity"],
        }
        # SHA-256 deduplication key
        key_hash = hashlib.sha256(r["skill_opportunity"].encode()).hexdigest()[:16]
        s3_key = f"skills/{key_hash}.json"

        try:
            # Skip if already exists (idempotent)
            s3.head_object(Bucket=bucket, Key=s3_key)
        except Exception:
            s3.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=json.dumps(payload).encode(),
                ContentType="application/json",
            )
            pushed += 1

    conn.close()
    print(f"✓  Pushed {pushed} new skill(s) to s3://{bucket}/skills/")


def pull_from_swarm(cfg: dict):
    """Pull teammates' skills from S3 into local DB."""
    if not require_team_mode(cfg):
        return

    bucket = cfg.get("team", {}).get("s3_bucket")
    s3 = get_s3_client(cfg)

    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT 1 FROM insights LIMIT 1")
    except sqlite3.OperationalError:
        print("❌  DB not initialized. Run: python3 db.py")
        conn.close()
        return

    paginator = s3.get_paginator("list_objects_v2")
    pulled = 0

    for page in paginator.paginate(Bucket=bucket, Prefix="skills/"):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            data = json.loads(body)

            # Don't re-insert skills already in local DB
            exists = cursor.execute(
                "SELECT 1 FROM insights WHERE session_id = ?",
                (data["session_id"],)
            ).fetchone()

            if not exists:
                try:
                    cursor.execute(
                        "INSERT INTO insights (session_id, summary, skill_opportunity) "
                        "VALUES (?, ?, ?)",
                        (data["session_id"], data.get("summary", ""), data["skill_opportunity"])
                    )
                    pulled += 1
                except Exception:
                    pass

    conn.commit()
    conn.close()
    print(f"✓  Pulled {pulled} new skill(s) from s3://{bucket}/skills/")


def show_status(cfg: dict):
    mode = cfg.get("mode", {}).get("type", "byok")
    bucket = cfg.get("team", {}).get("s3_bucket", "(not set)")
    print(f"Mode:   {mode}")
    print(f"Bucket: {bucket}")

    if not DB_PATH.exists():
        print("DB:     not initialized")
        return

    conn = sqlite3.connect(DB_PATH, timeout=5)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM insights WHERE skill_opportunity IS NOT NULL AND skill_opportunity != ''"
        ).fetchone()[0]
        print(f"Local skills ready to push: {count}")
    except Exception:
        print("DB:     no insights table yet")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kernora Team Swarm Sync")
    parser.add_argument("--push", action="store_true", help="Push local skills to team S3 bucket")
    parser.add_argument("--pull", action="store_true", help="Pull team skills from S3 bucket")
    parser.add_argument("--status", action="store_true", help="Show current sync status")
    args = parser.parse_args()

    cfg = load_config()

    if args.status:
        show_status(cfg)
    elif args.push:
        push_to_swarm(cfg)
    elif args.pull:
        pull_from_swarm(cfg)
    else:
        parser.print_help()
