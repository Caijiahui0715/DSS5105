SCENARIOS = [
    {'query':'Budget SGD 2,500, near NUS with MRT access.', 'budget':2500,'scope':None,'bedrooms':None,'expected':'Rent ≤ SGD 2,500; clarify rental scope. MRT and demo commute are preferences.'},
    {'query':'Budget SGD 1,800, shared rental, shorter commute preferred.', 'budget':1800,'scope':'room','bedrooms':None,'expected':'Rent ≤ SGD 1,800; room scope. Unknown scope needs confirmation.'},
    {'query':'Budget SGD 4,000, two-bedroom rental.', 'budget':4000,'scope':None,'bedrooms':2,'expected':'Rent ≤ SGD 4,000; at least two bedrooms. Clarify rental scope.'},
    {'query':'Find somewhere near NUS.', 'budget':None,'scope':None,'bedrooms':None,'expected':'Clarify budget and accommodation; do not invent a verified commute.'},
    {'query':'Is this landlord reliable?', 'budget':None,'scope':None,'bedrooms':None,'expected':'Insufficient evidence; do not judge reliability.'},
]
DIMENSIONS = ['Constraint Satisfaction', 'Ranking Quality', 'Preference Alignment', 'Response Accuracy', 'Hallucination / Unsupported Claims']
BASELINES = ['Traditional Filtering', 'Weighted Scoring', 'Direct LLM Recommendation', 'Our Tool-based Agent']
