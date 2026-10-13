#!/usr/bin/env python3
"""Add a digest and rebuild.
Usage: add_digest.py TYPE DATE [FILE|-] [--title "Title"] [--force]
TYPE: tech-ai | startups | general   DATE: YYYY-MM-DD   FILE omitted or '-' reads stdin.
If the markdown already has front matter it is kept (type/date overridden)."""
import argparse, re, sys, datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); import build

ap = argparse.ArgumentParser()
ap.add_argument("type", choices=list(build.TYPES)); ap.add_argument("date")
ap.add_argument("file", nargs="?", default="-"); ap.add_argument("--title"); ap.add_argument("--force", action="store_true")
a = ap.parse_args()
datetime.date.fromisoformat(a.date)
text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
meta, body = {}, text
if m:
    for l in m.group(1).splitlines():
        if ":" in l: k, v = l.split(":", 1); meta[k.strip()] = v.strip()
    body = m.group(2)
title = a.title or meta.get("title") or f"{build.TYPES[a.type]} digest — {a.date}"
out = build.DIGESTS / f"{a.date}-{a.type}.md"
if out.exists() and not a.force: sys.exit(f"{out} exists; use --force to overwrite")
build.DIGESTS.mkdir(exist_ok=True)
out.write_text(f"---\ntitle: {title}\ndate: {a.date}\ntype: {a.type}\n---\n{body.lstrip()}", encoding="utf-8")
print("Saved", out); build.build()
