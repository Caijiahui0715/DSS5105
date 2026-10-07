from domain.models import ConstraintEvaluation, Recommendation
from data.demo_enrichment import demo_score

def evaluate(listing, requirements):
    f = listing.facts
    checks = {}
    for name, value, wanted, predicate in (
        ('Maximum budget', f['effectiveRentMonthlySgd'], requirements.max_budget, lambda a,b: a <= b),
        ('Rental scope', f['rentalScope'], requirements.rental_scope, lambda a,b: a == b),
        ('Minimum bedrooms', f['bedrooms'], requirements.min_bedrooms, lambda a,b: a >= b),
    ):
        if wanted is None:
            continue
        status = 'needs_confirmation' if value is None or value == 'unknown' else ('pass' if predicate(value, wanted) else 'fail')
        checks[name] = {'status': status, 'reason': 'Needs confirmation' if status == 'needs_confirmation' else ('Requirement met' if status == 'pass' else 'Requirement not met')}
    statuses = [item['status'] for item in checks.values()]
    status = 'fail' if 'fail' in statuses else 'needs_confirmation' if 'needs_confirmation' in statuses else 'pass'
    return ConstraintEvaluation(status, checks)

def recommend(listings, requirements, preferences):
    results = []
    for listing in listings:
        assessment = evaluate(listing, requirements)
        if assessment.status == 'fail':
            continue
        score, breakdown, reasons, tradeoffs, unknown = demo_score(listing, requirements, preferences)
        level = 'Strong demo match' if score >= 65 else 'Potential demo match' if score >= 40 else 'Limited evidence match'
        if assessment.status == 'needs_confirmation':
            tradeoffs.insert(0, 'A required field is unknown. Confirm it before treating this listing as eligible.')
        results.append(Recommendation(listing.id, 0, score, level, assessment, reasons, tradeoffs, unknown, breakdown))
    results.sort(key=lambda r: (r.evaluation.status != 'pass', -r.score, r.listing_id))
    for index, result in enumerate(results, 1):
        result.rank = index
    return results
