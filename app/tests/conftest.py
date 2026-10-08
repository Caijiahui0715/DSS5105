import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# These tests run the offline demo: static files and the scripted agent, no backend.
os.environ['AGENT_MODE'] = 'mock'

@pytest.fixture(scope='session')
def sources():
    from data.source_loader import read_sources
    return read_sources()
