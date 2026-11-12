from pathlib import Path

import pytest

from latex2md import pandoc_available

FIXTURES = Path(__file__).parent / "fixtures"

requires_pandoc = pytest.mark.skipif(not pandoc_available(), reason="pandoc not installed")


@pytest.fixture
def sample_md() -> str:
    return (FIXTURES / "sample.md").read_text(encoding="utf-8")


@pytest.fixture
def sample_tex() -> str:
    return (FIXTURES / "sample.tex").read_text(encoding="utf-8")
