"""Which data and agent the app uses.

By default everything comes from the agent backend (server.py): accounts, listings, the agent's
replies, recommendations, commute times, conversations and shortlists. AGENT_MODE=mock runs the
offline demo instead: static files and a scripted demo agent, no backend and no real accounts.

Settings come from the environment or app/.env (never committed):
    BACKEND_URL=http://127.0.0.1:8000
    DEMO_USERNAME=demo_user        # optional: a "Continue with demo account" button
    DEMO_PASSWORD=...
    AGENT_MODE=mock                # optional: the offline demo
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / '.env'


def _load_env_file():
    # KEY=VALUE lines; the real environment wins.
    try:
        lines = ENV_FILE.read_text(encoding='utf-8-sig').splitlines()
    except OSError:
        return
    for line in lines:
        key, sep, value = line.partition('=')
        if sep and key.strip() and not key.lstrip().startswith('#'):
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))


_load_env_file()


def offline():
    return os.getenv('AGENT_MODE', '').strip().lower() == 'mock'


def backend_url():
    # An empty BACKEND_URL= line in app/.env means the default too.
    return (os.getenv('BACKEND_URL') or 'http://127.0.0.1:8000').strip()


def demo_account():
    """(username, password) for the demo button, or None when not configured."""
    username, password = os.getenv('DEMO_USERNAME', '').strip(), os.getenv('DEMO_PASSWORD', '')
    return (username, password) if username and password else None


def create_adapters(client=None):
    """The rental data and the agent: the backend's, through the signed-in client, or offline ones."""
    if offline():
        from adapters.static_rental_api import StaticRentalApi
        from adapters.mock_agent_api import MockAgentApi

        rental = StaticRentalApi()
        return rental, MockAgentApi(rental)
    from adapters.http_rental_api import HttpRentalApi
    from adapters.http_agent_api import HttpAgentApi

    return HttpRentalApi(client), HttpAgentApi(client)
