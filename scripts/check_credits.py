#!/usr/bin/env python3
"""Print OpenRouter credit balance and this key's usage. Makes no model calls and costs nothing.

The key is read from .env inside this process and sent only to openrouter.ai. It is never printed.
Only numeric fields are printed, never the key or its label.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
key = (dotenv_values(ROOT / ".env").get("OPENROUTER_API_KEY") or "").strip()
if not key:
    sys.exit("OPENROUTER_API_KEY is missing or blank in .env")


def get(path: str) -> dict | None:
    req = urllib.request.Request(f"https://openrouter.ai/api/v1/{path}", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("data", {})
    except urllib.error.HTTPError as e:
        print(f"{path}: HTTP {e.code} (not available with this key)")
        return None


credits = get("credits")
if credits is not None:
    total, used = credits.get("total_credits"), credits.get("total_usage")
    print(f"Account credits: total ${total:.2f}, used ${used:.2f}, remaining ${total - used:.2f}")

k = get("key")
if k is not None:
    for field in ("limit", "limit_remaining", "usage", "usage_daily", "usage_monthly"):
        if field in k:
            print(f"This key {field}: {k[field]}")
