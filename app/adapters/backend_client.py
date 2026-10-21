"""Calls to the agent backend (server.py at the repository root), standard library only.

Every call after signing in sends the account's token as `Authorization: Bearer <token>`.
A reply arrives as Server-Sent Events: progress lines while the agent works, then the reply.
"""
import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from domain.models import ApiError

# A turn checks listing links and may call the model several times.
TURN_TIMEOUT_SECONDS = 300
PAGE_SIZE = 200


class BackendError(ApiError):
    """A failed backend call. status is None when the backend could not be reached;
    detail is the backend's own message, when it sent one."""

    def __init__(self, detail, status=None):
        super().__init__(detail)
        self.detail, self.status = detail, status


class SessionExpired(BackendError):
    """The token is missing, expired or revoked: sign in again."""


class BackendClient:
    def __init__(self, base_url, token=None, opener=urlopen):
        self.base_url, self.token, self._open = base_url.rstrip('/'), token, opener

    def sign_in(self, username, password):
        """Keeps the token for later calls; returns the account (username, faculty) and the token."""
        account = self._json('POST', '/api/token', {'username': username, 'password': password})
        self.token = account['token']
        return account

    def register(self, username, password, faculty=None):
        self._json('POST', '/api/register', {'username': username, 'password': password, 'faculty': faculty})
        return self.sign_in(username, password)

    def sign_out(self):
        """Revokes the token on the backend; a backend that is down cannot keep using it either way."""
        try:
            self._json('POST', '/api/logout', {})
        except BackendError:
            pass
        self.token = None

    def me(self):
        return self._json('GET', '/api/me')

    def set_faculty(self, faculty):
        return self._json('PUT', '/api/me/faculty', {'faculty': faculty})

    def faculties(self):
        return self._json('GET', '/api/faculties')

    def options(self):
        """Districts with listings and property types, for the criteria forms."""
        return self._json('GET', '/api/options')

    def listings(self):
        rows, total = [], None
        while total is None or len(rows) < total:
            page = self._json('GET', f'/api/listings?limit={PAGE_SIZE}&offset={len(rows)}')
            total = page['total']
            if not page['listings']:
                break
            rows += page['listings']
        return rows

    def listing(self, listing_id):
        """{'listing', 'source_evidence'}, or None when the listing is not in the data."""
        try:
            return self._json('GET', f'/api/listings/{quote(listing_id, safe="")}')
        except BackendError as error:
            if error.status == 404:
                return None
            raise

    def conversations(self):
        return self._json('GET', '/api/conversations')

    def new_conversation(self, language=None):
        """A new conversation; while long-term memory is on it starts from the kept criteria, with a
        first message in language ('zh' or 'en')."""
        return self._json('POST', '/api/conversations', {'language': language} if language else {})['id']

    def conversation(self, thread_id):
        """The saved criteria (preferences, sources, items), the latest search's listings and the account's shortlist."""
        return self._json('GET', f'/api/conversations/{quote(thread_id, safe="")}')

    def delete_conversation(self, thread_id):
        """Deletes the conversation and what the agent kept of it; waits for a reply in progress."""
        return self._json('DELETE', f'/api/conversations/{quote(thread_id, safe="")}')

    def messages(self, thread_id):
        return self._json('GET', f'/api/conversations/{quote(thread_id, safe="")}/messages')

    # The long-term profile: the criteria new conversations start from while memory is on.
    def profile(self):
        """{memory: on/off/undecided, auto_save, auto_save_offer, saved_on, preferences, sources, budget, items, opening}."""
        return self._json('GET', '/api/me/profile')

    def edit_profile(self, changes):
        """changes: the agent's criteria to change, each to its new value or None to drop it."""
        return self._json('PUT', '/api/me/profile', {'changes': changes})

    def set_memory(self, on):
        return self._json('PUT', '/api/me/memory', {'on': on})

    def set_auto_save(self, on):
        return self._json('PUT', '/api/me/auto-save', {'on': on})

    def close_auto_save_offer(self):
        return self._json('DELETE', '/api/me/auto-save/offer')

    def delete_profile(self):
        return self._json('DELETE', '/api/me/profile')

    def profile_changes(self, thread_id):
        """What saving this conversation's criteria would change in the long-term profile."""
        return self._json('GET', f'/api/conversations/{quote(thread_id, safe="")}/profile')

    # Saving waits for a reply the agent is still writing in the same conversation.
    def save_profile(self, thread_id, switch_on=False):
        path = f'/api/conversations/{quote(thread_id, safe="")}/profile'
        return self._json('POST', path, {'switch_on': switch_on}, TURN_TIMEOUT_SECONDS)

    def auto_save_from(self, thread_id):
        """Switch automatic saving on and save what this conversation changed so far: {changes, profile}."""
        path = f'/api/conversations/{quote(thread_id, safe="")}/auto-save'
        return self._json('POST', path, None, TURN_TIMEOUT_SECONDS)

    # The account's shortlist and exclusions, shared by all its conversations: {shortlist, excluded}.
    def my_listings(self):
        return self._json('GET', '/api/me/listings')

    def shortlist_add(self, listing_id):
        return self._json('POST', '/api/me/shortlist', {'listing_id': listing_id})

    def shortlist_remove(self, listing_id):
        return self._json('DELETE', f'/api/me/shortlist/{quote(listing_id, safe="")}')

    def restore(self, listing_id):
        """Searches show an excluded listing again."""
        return self._json('DELETE', f'/api/me/excluded/{quote(listing_id, safe="")}')

    def delete_my_data(self):
        """Every conversation, the long-term profile, listings and the faculty; signs out everywhere."""
        return self._json('DELETE', '/api/me/data')

    def send(self, thread_id, message, language):
        """Yields (event, data) pairs: 'progress' {'zh', 'en'}, then 'reply' or 'error'."""
        path = f'/api/conversations/{quote(thread_id, safe="")}/messages'
        with self._call('POST', path, {'message': message, 'language': language}, TURN_TIMEOUT_SECONDS) as response:
            event = None
            for raw in _reading(response):
                line = raw.decode('utf-8').rstrip('\r\n')
                if line.startswith('event: '):
                    event = line[len('event: '):]
                elif line.startswith('data: ') and event:
                    yield event, json.loads(line[len('data: '):])
                    event = None

    def _json(self, method, path, body=None, timeout=30):
        with self._call(method, path, body, timeout) as response:
            return json.loads(b''.join(_reading(response)) or b'null')

    def _call(self, method, path, body=None, timeout=30):
        headers = {'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        data = None if body is None else json.dumps(body).encode('utf-8')
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            return self._open(request, timeout=timeout)
        except HTTPError as error:
            detail = _detail(error)
            raise (SessionExpired if error.code == 401 else BackendError)(detail, error.code) from None
        except (URLError, OSError, HTTPException) as error:
            reason = getattr(error, 'reason', error)
            # A backend that answers too slowly is up but busy; one that does not answer is down.
            raise BackendError(str(reason), 504 if isinstance(reason, TimeoutError) else None) from None


def _reading(response):
    """The response's lines; a connection that breaks or times out midway is a backend error."""
    try:
        yield from response
    except (OSError, HTTPException) as error:
        raise BackendError(f'the connection broke: {error}', 504) from None


def _detail(error):
    try:
        detail = json.loads(error.read())['detail']
    except (ValueError, KeyError, TypeError, OSError):
        detail = None
    # FastAPI's validation errors are a list; only plain messages are worth showing.
    return detail if isinstance(detail, str) else f'HTTP {error.code}'
