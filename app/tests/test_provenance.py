import copy
from domain.models import RentalRequirements,RentalPreferences
from domain.recommendation import recommend
from data.demo_enrichment import DEMO

def test_provenance_and_separation(sources):
    before=copy.deepcopy(sources)
    recommend(sources['listings'],RentalRequirements(),RentalPreferences())
    assert sources==before
    ids={listing.id for listing in sources['listings']}
    assert set(DEMO)<=ids
    assert len(DEMO)<20
    for listing in sources['listings']:
        assert set(listing.provenance.values())<= {'source','derived','mock','unavailable'}
        assert not {'commute','score'} & listing.facts.keys()
        assert {'latitude','longitude'} <= listing.facts.keys()
        assert listing.provenance['coordinates'] in ('source','derived')
        assert listing.provenance['score']=='mock'
        assert all('coordinates' not in entry for entry in DEMO.values())
