import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

@pytest.fixture(scope='session')
def sources():
    from data.source_loader import read_sources
    return read_sources()
