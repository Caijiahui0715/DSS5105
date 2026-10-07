from dataclasses import replace
import pytest
from domain.models import RentalRequirements, RentalPreferences
from domain.recommendation import evaluate,recommend
from data.demo_enrichment import DEFAULT_WEIGHTS
from adapters.mock_agent_api import MockAgentApi

@pytest.mark.parametrize('changes,requirements,status',[
    ({'effectiveRentMonthlySgd':None},RentalRequirements(2500,None,None),'needs_confirmation'),
    ({'effectiveRentMonthlySgd':2500},RentalRequirements(2500,None,None),'pass'),
    ({'effectiveRentMonthlySgd':2501},RentalRequirements(2500,None,None),'fail'),
    ({'rentalScope':'unknown'},RentalRequirements(None,'room',None),'needs_confirmation'),
    ({'rentalScope':'entire_unit'},RentalRequirements(None,'room',None),'fail'),
    ({'bedrooms':None},RentalRequirements(None,None,2),'needs_confirmation'),
    ({'bedrooms':2},RentalRequirements(None,None,2),'pass'),
    ({'effectiveRentMonthlySgd':9999,'bedrooms':None},RentalRequirements(2500,None,2),'fail'),
])
def test_three_state(sources,changes,requirements,status):
    listing=sources['listings'][0]
    listing=replace(listing,facts={**listing.facts,**changes})
    assert evaluate(listing,requirements).status == status

def test_ranking_and_unknowns(sources):
    assert sum(DEFAULT_WEIGHTS.values())==100
    results=recommend(sources['listings'],RentalRequirements(),RentalPreferences())
    assert results
    assert all(0<=r.score<=100 and r.evaluation.status!='fail' and r.is_demo_score for r in results)
    assert [r.rank for r in results]==list(range(1,len(results)+1))
    assert all(r.breakdown['Property preference'] is None for r in results)
    seen_confirmation=False
    for r in results:
        if r.evaluation.status=='needs_confirmation':seen_confirmation=True
        elif seen_confirmation:pytest.fail('Pass must rank before unconfirmed')

class LocalApi:
    def __init__(self,listings):self.listings=listings
    def recommendations(self,req,pref):return recommend(self.listings,req,pref)

def test_agent_queries(sources):
    agent=MockAgentApi(LocalApi(sources['listings']))
    response=agent.respond('Find a two-bedroom rental under SGD 4,000.',RentalRequirements(),RentalPreferences(),[])
    assert response.requirements.max_budget==4000
    assert response.requirements.min_bedrooms==2
    assert response.requirements.rental_scope is None
    assert response.clarification
    response=agent.respond('Is this landlord reliable?',RentalRequirements(),RentalPreferences(),[])
    assert not response.recommendations
    assert 'cannot establish' in response.text

def test_review_flags_do_not_change_constraints(sources):
    listing=sources['listings'][0]
    baseline=evaluate(listing,RentalRequirements(None,None,None))
    flagged=replace(listing,metadata={**listing.metadata,'reviewFlags':['review']})
    assert evaluate(flagged,RentalRequirements(None,None,None))==baseline

def test_unknown_requested_preference_cannot_get_full_points(sources):
    from data.demo_enrichment import demo_score
    listing=sources['listings'][0]
    assert listing.facts['furnishing']=='unknown'
    pref=RentalPreferences(districts=[listing.facts['districtCode']],furnishing='fully_furnished')
    _,breakdown,_,_,_=demo_score(listing,RentalRequirements(),pref)
    assert breakdown['Other known preferences']==0.5
