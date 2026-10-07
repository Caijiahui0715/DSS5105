import pytest
from pathlib import Path
from adapters.backend_mapper import safe_image_urls
from data.source_loader import read_sources

def test_counts(sources):
    assert len(sources['listings']) == 376
    assert len(sources['metadata']) == 376
    assert len(sources['districts']) == 28
    assert sources['snapshot']['removed_count'] == 217
    assert sources['snapshot']['inferred_coordinates_count'] == 16

@pytest.mark.parametrize('value,expected',[(None,()),('broken',()),('{}',()),('["javascript:bad", null, 1]',()),('["https://example.com/image.jpg"]',('https://example.com/image.jpg',)),(['https://example.com/a','file:///secret'],('https://example.com/a',))])
def test_safe_images(value,expected):
    assert safe_image_urls(value) == expected

def test_missing_required_data():
    with pytest.raises(ValueError,match='Unable to load required rental data'):
        read_sources(Path(__file__).resolve().parent/'nonexistent-source-directory')
