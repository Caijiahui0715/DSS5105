from domain.models import ApiError

class HttpRentalApi:
    """Safe placeholder. No outbound calls before the proposed contract is agreed."""
    def __init__(self, base_url=None):
        self.base_url = base_url
        raise ApiError('Backend HTTP integration is not implemented yet. Set RENTAL_DATA_MODE=static for the demonstration.')

    def all_listings(self):
        raise ApiError('Backend API is not connected. Use static mode for this demonstration.')

    def details(self, listing_id):
        return self.all_listings()

    def recommendations(self, requirements, preferences):
        return self.all_listings()
