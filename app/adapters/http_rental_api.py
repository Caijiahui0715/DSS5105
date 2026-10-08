"""Listings from the agent backend: the same data, rents and commute times the agent ranks with."""
import streamlit as st
from adapters.backend_client import BackendClient
from adapters.backend_mapper import BackendMapper

# The backend checks its database for new data every few minutes.
REFRESH_SECONDS = 300


@st.cache_data(ttl=REFRESH_SECONDS, show_spinner=False)
def _listings(base_url, _client):
    # Listings are the same for every account, so the cache is shared; the client is not hashed.
    return [_listing(row) for row in _client.listings()]


@st.cache_data(ttl=REFRESH_SECONDS, show_spinner=False)
def _details(base_url, listing_id, _client):
    found = _client.listing(listing_id)
    return found and _listing(found['listing'], found.get('source_evidence') or {})


def _listing(row, evidence=None):
    # The backend's rent_monthly_sgd is already the rechecked rent where V2 has one;
    # BackendMapper expects the advertised rent there and works the effective rent out itself.
    row = {**row, 'rent_monthly_sgd': row.get('rent_monthly_sgd_card', row.get('rent_monthly_sgd'))}
    metadata = {'availability_status': row.get('availability_status'), 'review_flags': row.get('review_flags') or []}
    return BackendMapper.listing(row, metadata, {'district': row.get('district')}, evidence or {})


class HttpRentalApi:
    def __init__(self, client):
        self.client = client

    def all_listings(self):
        """Every listing, without photos and page text (details() has them)."""
        return _listings(self.client.base_url, self.client)

    def details(self, listing_id):
        """One listing with its source record (photos, page text, field evidence), or None."""
        return _details(self.client.base_url, listing_id, self.client) if listing_id else None

    @property
    def sources(self):
        """Choices for the criteria forms, in the shape of the static data's districts."""
        options = criteria_options(self.client.base_url)
        return {'districts': [{'district_code': d['code'], 'district': d['name']} for d in options['districts']],
                'property_types': options['property_types']}

    def recommendations(self, requirements, preferences):
        # The agent recommends; this API only serves listings.
        return []


@st.cache_data(ttl=REFRESH_SECONDS, show_spinner=False)
def criteria_options(base_url):
    """Districts that have listings, and property types; no account needed, so sign-up can use them."""
    return BackendClient(base_url).options()
