from data.source_loader import load_sources
from domain.recommendation import recommend, evaluate

class StaticRentalApi:
    def __init__(self):
        self.sources = load_sources()
        self.index = {listing.id: listing for listing in self.sources['listings']}

    def all_listings(self):
        return list(self.index.values())

    def details(self, listing_id):
        return self.index.get(listing_id)

    def recommendations(self, requirements, preferences):
        return recommend(self.all_listings(), requirements, preferences)

    def classify(self, requirements):
        result = {'pass': [], 'needs_confirmation': [], 'fail': []}
        for listing in self.all_listings():
            evaluation = evaluate(listing, requirements)
            result[evaluation.status].append({'listing': listing, 'evaluation': evaluation})
        return result
