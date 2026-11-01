import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))


@pytest.fixture
def comfy():
    pytest.importorskip("aiohttp")
    from mock_comfy import MockComfy

    server = MockComfy().start()
    yield server
    server.stop()
