#!/usr/bin/env python3
"""Download the arXiv regression corpus listed in tests/corpus/manifest.json.

Every e-print is fetched by versioned id (``2402.18824v1``), so its sha256 is
stable, and is checked against the manifest before it is kept in the
(gitignored) cache. Only papers whose arXiv licence is CC BY 4.0 or CC0 may
be listed; ``--check-licences`` re-reads each abs page, and ``--add ID``
verifies the licence, downloads the e-print, converts it and prints a
manifest entry with measured expectations.

    python scripts/fetch_corpus.py                  # fill the cache
    python scripts/fetch_corpus.py --check-licences
    python scripts/fetch_corpus.py --add 2402.18824v1

arXiv asks automated clients to pace requests, so there is a pause between
downloads.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

MANIFEST = ROOT / "tests" / "corpus" / "manifest.json"
DEFAULT_CACHE = ROOT / "tests" / "corpus" / "cache"
ALLOWED_LICENCES = (
    "http://creativecommons.org/licenses/by/4.0/",
    "http://creativecommons.org/publicdomain/zero/1.0/",
)
USER_AGENT = "latex2md-corpus-fetch (https://github.com/lattuce-ai/latex2md)"
PAUSE_SECONDS = 3.0
MAX_EPRINT_BYTES = 100 * 1024 * 1024
_ID_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})v\d+$")
_LICENCE_RE = re.compile(r'class="abs-license">\s*<a href="([^"]+)"')


def cache_dir() -> Path:
    return Path(os.environ.get("LATEX2MD_CORPUS_CACHE") or DEFAULT_CACHE)


def cache_path(paper_id: str) -> Path:
    return cache_dir() / f"{paper_id.replace('/', '_')}.eprint"


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _get(url: str, *, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"{url} is larger than {limit} bytes")
    return data


def licence_of(paper_id: str) -> str | None:
    """The licence URL linked from the arXiv abs page, or None."""
    page = _get(f"https://arxiv.org/abs/{paper_id}", limit=5 * 1024 * 1024).decode("utf-8", errors="replace")
    match = _LICENCE_RE.search(page)
    return match.group(1) if match else None


def download(paper_id: str) -> bytes:
    if not _ID_RE.match(paper_id):
        raise ValueError(f"{paper_id!r} is not a versioned arXiv id such as 2402.18824v1")
    return _get(f"https://arxiv.org/e-print/{paper_id}", limit=MAX_EPRINT_BYTES)


def fetch_all(manifest: dict) -> int:
    failures = 0
    cache_dir().mkdir(parents=True, exist_ok=True)
    for index, paper in enumerate(manifest["papers"]):
        path = cache_path(paper["id"])
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == paper["sha256"]:
            print(f"cached   {paper['id']}")
            continue
        if index:
            time.sleep(PAUSE_SECONDS)
        data = download(paper["id"])
        digest = hashlib.sha256(data).hexdigest()
        if digest != paper["sha256"]:
            print(f"MISMATCH {paper['id']}: sha256 {digest} != manifest {paper['sha256']}", file=sys.stderr)
            failures += 1
            continue
        path.write_bytes(data)
        print(f"fetched  {paper['id']} ({len(data)} bytes)")
    return 1 if failures else 0


def check_licences(manifest: dict) -> int:
    failures = 0
    for index, paper in enumerate(manifest["papers"]):
        if index:
            time.sleep(PAUSE_SECONDS)
        licence = licence_of(paper["id"])
        ok = licence == paper["licence"] and licence in ALLOWED_LICENCES
        print(f"{'ok  ' if ok else 'FAIL'} {paper['id']}: {licence}")
        failures += not ok
    return 1 if failures else 0


def add(paper_id: str, pandocs: list[str]) -> int:
    from corpus_stats import expectations, measure

    from latex2md import convert_latex_archive_to_md

    licence = licence_of(paper_id)
    if licence not in ALLOWED_LICENCES:
        print(f"{paper_id}: licence {licence!r} is not CC BY 4.0 or CC0; not adding it", file=sys.stderr)
        return 1
    time.sleep(PAUSE_SECONDS)
    data = download(paper_id)
    cache_dir().mkdir(parents=True, exist_ok=True)
    cache_path(paper_id).write_bytes(data)
    measured = []
    for pandoc in pandocs or [os.environ.get("LATEX2MD_PANDOC", "")]:
        if pandoc:
            os.environ["LATEX2MD_PANDOC"] = pandoc
        measured.append(measure(convert_latex_archive_to_md(data).text))
    entry = {
        "id": paper_id,
        "licence": licence,
        "licence_checked": datetime.datetime.now(datetime.UTC).date().isoformat(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "measured": [m.as_dict() for m in measured],
        "expect": expectations(measured),
    }
    print(json.dumps(entry, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-licences", action="store_true", help="re-read each paper's licence on arxiv.org")
    parser.add_argument("--add", metavar="ID", help="verify, download and measure a new versioned arXiv id")
    parser.add_argument("--pandoc", action="append", default=[], help="with --add: measure with these pandoc binaries")
    args = parser.parse_args(argv)
    if args.add:
        return add(args.add, args.pandoc)
    manifest = load_manifest()
    if args.check_licences:
        return check_licences(manifest)
    return fetch_all(manifest)


if __name__ == "__main__":
    raise SystemExit(main())
