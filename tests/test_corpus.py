"""Regression test on real arXiv papers (opt-in).

Run ``python scripts/fetch_corpus.py`` first, then ``LATEX2MD_CORPUS=1 pytest
tests/test_corpus.py``. The e-prints are checked against the manifest's
sha256 and are not stored in git; see tests/corpus/manifest.json for the
papers and their licences.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest
from conftest import requires_pandoc

from latex2md import convert_latex_archive_to_md

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from corpus_stats import measure
from fetch_corpus import ALLOWED_LICENCES, cache_path, load_manifest

MANIFEST = load_manifest()
ENABLED = os.environ.get("LATEX2MD_CORPUS") == "1"


def _cached(paper: dict) -> bytes | None:
    path = cache_path(paper["id"])
    if not path.is_file():
        return None
    data = path.read_bytes()
    return data if hashlib.sha256(data).hexdigest() == paper["sha256"] else None


def test_manifest_schema():
    """Always runs: every listed paper has a permitted licence and a hash."""
    assert MANIFEST["schema"] == 1
    for paper in MANIFEST["papers"]:
        assert paper["licence"] in ALLOWED_LICENCES, paper["id"]
        assert re.fullmatch(r"[0-9a-f]{64}", paper["sha256"]), paper["id"]
        assert re.search(r"v\d+$", paper["id"]), "use versioned ids so the sha256 is stable"
        low, high = paper["expect"]["headings"]
        assert 0 < low <= high
    assert len({paper["id"] for paper in MANIFEST["papers"]}) == len(MANIFEST["papers"])


@requires_pandoc
@pytest.mark.skipif(not ENABLED, reason="set LATEX2MD_CORPUS=1 (after scripts/fetch_corpus.py) to run")
@pytest.mark.parametrize("paper", MANIFEST["papers"], ids=lambda paper: paper["id"])
def test_corpus_paper(paper):
    data = _cached(paper)
    if data is None:
        pytest.skip(f"{paper['id']} is not in the cache; run scripts/fetch_corpus.py")
    result = convert_latex_archive_to_md(data)
    stats = measure(result.text)
    expect = paper["expect"]
    low, high = expect["headings"]
    assert low <= stats.headings <= high
    assert stats.display_equations >= expect["min_display_equations"]
    assert stats.tables >= expect["min_tables"]
    assert stats.references >= expect["min_references"]
    # No LaTeX environments outside math and code, no HTML, no pandoc divs.
    assert stats.leaks == ()
    assert json.dumps(result.text)  # output is valid text
