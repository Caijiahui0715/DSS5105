import os
from adapters.static_rental_api import StaticRentalApi
from adapters.http_rental_api import HttpRentalApi
from adapters.mock_agent_api import MockAgentApi
from adapters.http_agent_api import HttpAgentApi

def create_adapters():
    rental = HttpRentalApi(os.getenv('RENTAL_API_BASE_URL')) if os.getenv('RENTAL_DATA_MODE', 'static') == 'http' else StaticRentalApi()
    agent = HttpAgentApi(os.getenv('AGENT_API_BASE_URL')) if os.getenv('AGENT_MODE', 'mock') == 'http' else MockAgentApi(rental)
    return rental, agent
