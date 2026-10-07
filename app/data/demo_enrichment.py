"""All demonstration-only estimates and response templates live here.

Positions are deliberately illustrative, not geocoded addresses. The NUS point
is also a demo campus anchor, not a verified faculty destination.
"""
NUS_POSITION = (1.2966, 103.7764)
MAP_NOTICE = 'Map positions come from V2 data. Inferred locations are approximate. The NUS anchor and commute estimates remain illustrative.'
DEMO = {
    '500250282': {'commute': 25},
    '500253628': {'commute': 28},
    '25039291': {'commute': 36},
    '60151196': {'commute': 45},
}
DEFAULT_WEIGHTS = {'Budget fit': 30, 'Demo commute': 30, 'MRT accessibility': 15, 'Property preference': 15, 'Other known preferences': 10}
AGENT_INTRO = 'I used the supplied static listings and your session preferences. This is a deterministic demo Agent, not a production AI service.'
RELIABILITY_REPLY = 'The supplied listing data cannot establish landlord or agent reliability. Please verify independently; I cannot make a reliability recommendation.'
WELCOME_MESSAGE = 'Welcome. What is your rental budget, and would you prefer a room or an entire unit?'
MISSING_BUDGET_QUESTION = 'What is your maximum monthly budget? I used your profile budget for these provisional results.'
MISSING_SCOPE_QUESTION = 'Do you need an entire unit or shared accommodation? No rental-scope filter was applied yet.'
INVALID_BUDGET_REPLY = 'Please provide a monthly budget above SGD 0.'

def agent_summary(count):
    return f'{AGENT_INTRO}\n\nFound {count} non-failing candidates. Unknown required facts remain Needs confirmation.'

def demo_score(listing, requirements, preferences):
    f = listing.facts
    budget = requirements.max_budget
    rent = f['effectiveRentMonthlySgd']
    commute = DEMO.get(listing.id, {}).get('commute')
    mrt = f.get('mrtDistanceM')
    breakdown = {
        'Budget fit': min(1.0, max(0.0, 1 - rent / budget * .5)) if budget and rent is not None else None,
        'Demo commute': max(0.0, 1 - commute / (preferences.commute_minutes * 2)) if commute is not None and preferences.commute_minutes else None,
        'MRT accessibility': max(0.0, 1 - mrt / (preferences.mrt_distance * 2)) if mrt is not None and preferences.mrt_distance else None,
        'Property preference': (1.0 if f['propertyType'] == preferences.property_type else 0.0) if preferences.property_type != 'No preference' else None,
    }
    requested = [('furnishing', preferences.furnishing), ('privateBathroom', preferences.private_bathroom), ('cookingPolicy', preferences.cooking), ('airConditioning', preferences.air_conditioning), ('petsPolicy', preferences.pets)]
    values = [(1.0 if f[key] == wanted else 0.0) for key, wanted in requested if wanted != 'No preference']
    if preferences.districts:
        values.append(1.0 if f['districtCode'] in preferences.districts else 0.0)
    breakdown['Other known preferences'] = sum(values)/len(values) if values else None
    # Unknown components contribute zero, not a silently imputed perfect score.
    score = round(sum((value or 0) * DEFAULT_WEIGHTS[key] for key, value in breakdown.items()))
    reasons, tradeoffs = [], []
    if budget and rent is not None and rent <= budget:
        reasons.append(f'Latest recorded advertised rent SGD {rent:,.0f} is within your budget.')
    if f['districtCode'] in preferences.districts:
        reasons.append(f"Matches preferred district {f['districtCode']}.")
    if mrt is not None:
        reasons.append(f'Advertised MRT distance: {mrt:,.0f} m; not independently verified.')
    if commute is not None:
        reasons.append(f'Estimated demo commute: {commute} min; illustrative only.')
        if preferences.commute_minutes is not None and commute > preferences.commute_minutes:
            tradeoffs.append('Demo commute exceeds your preferred duration.')
    if f['rentPriceType'] in ('starting_from', 'guide_price'):
        tradeoffs.append('Advertised starting/guide price may differ from the final rent.')
    if listing.metadata['reviewFlags']:
        tradeoffs.append('Data needs review; recorded flags require checking, not automatic rejection.')
    tradeoffs.append('Active at the recorded snapshot, not guaranteed available now; rent excludes unconfirmed extra costs.')
    unknown = [key for key in ('furnishing', 'privateBathroom', 'cookingPolicy', 'airConditioning', 'petsPolicy') if f[key] in (None, 'unknown')]
    unknown += [key for key, value in breakdown.items() if value is None]
    unknown.append('Property condition: no reliable condition assessment supplied')
    return score, breakdown, reasons, tradeoffs, unknown
