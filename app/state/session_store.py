import time
from datetime import datetime
from uuid import uuid4
import streamlit as st
from adapters.backend_client import BackendClient, BackendError, TURN_TIMEOUT_SECONDS
from adapters.configuration import backend_url
from adapters.http_agent_api import recommendations
from content.i18n import t, language
from domain.criteria import EMPTY, empty, from_backend
from domain.models import RentalRequirements, RentalPreferences

NEW_TITLE = 'New conversation'
# Kept when signing out: the interface language and the remember-me cookie handling.
_KEPT_ON_SIGN_OUT = ('language', 'cookie-checked', 'cookie-action', 'auth-error')


def initialize():
    defaults = {'authenticated':False, 'profile':{'name':'Demo explorer','email':'demo@example.com'}, 'requirements':RentalRequirements(), 'preferences':RentalPreferences(), 'favorites':{}, 'compare':[], 'conversations':{}, 'active_conversation':None, 'selected_listing':None, 'page':'Home', 'notice':None, 'language':'en', 'client':None, 'faculty':None,
                # The signed-in account's shortlisted and excluded listings, shared by all its conversations.
                'shortlist':[], 'excluded':[]}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    # True while this run sends a message to the agent (set by Home, after the page is drawn).
    st.session_state.sending = False
    if st.session_state.active_conversation is None:
        new_conversation()


def live():
    """Signed in to the agent backend, rather than the offline demo."""
    return st.session_state.get('client') is not None


def _conversation(title, requirements, preferences, thread_id=None, loaded=True, updated=None):
    return {'title':title, 'messages':[], 'recommendations':None, 'requirements':requirements, 'preferences':preferences,
            'updated':updated or datetime.now().isoformat(timespec='seconds'),
            # The backend's id (None until the first message), whether its messages are here yet,
            # whether its listings are only a preview, and its saved criteria as the backend sends them
            # ({'preferences', 'sources', 'items'}) for the criteria panel.
            'thread_id':thread_id, 'loaded':loaded, 'preview':False, 'criteria':dict(EMPTY),
            # With the backend: the latest comparison table, the compare box (the listings to compare
            # next, in the table's order: those last compared until the user changes it), and whether
            # a table asked for in chat is new since the Compare bar was last opened.
            'comparison':None, 'compare':[], 'compare_new':False}


def new_conversation():
    key = str(uuid4())
    if live():
        conv = _conversation(NEW_TITLE, *empty())
        start_from_profile(conv)
    else:
        conv = _conversation(NEW_TITLE, st.session_state.requirements, st.session_state.preferences)
    st.session_state.conversations[key] = conv
    st.session_state.active_conversation = key


def read_profile():
    """The long-term profile with both switches, read from the backend and kept as
    st.session_state.long_term for the Home page's auto-save offer."""
    st.session_state.long_term = st.session_state.client.profile()
    return st.session_state.long_term


def start_from_profile(conv, profile=None):
    """A conversation not started yet shows what the backend will start it from: the long-term
    profile while memory is on, with the same first message; otherwise nothing. profile: as just
    read, else it is read now."""
    profile = profile or read_profile()
    if profile['opening']:
        conv['criteria'] = {**{key: profile[key] for key in ('preferences', 'sources', 'items')}, 'profile_changes': []}
        conv['messages'] = [{'role': 'assistant', 'text': profile['opening'][language()]}]
    else:
        conv['criteria'], conv['messages'] = dict(EMPTY), []
    conv['requirements'], conv['preferences'] = from_backend(conv['criteria']['preferences'])


def delete_conversation(key):
    """Delete a conversation on the backend (one already gone counts as deleted) and from the list.
    When it was open, a new conversation takes its place, as after signing in."""
    conv = st.session_state.conversations[key]
    try:
        st.session_state.client.delete_conversation(conv['thread_id'])
    except BackendError as error:
        if error.status != 404:
            raise
    del st.session_state.conversations[key]
    if st.session_state.active_conversation == key:
        blank = next((other for other, kept in st.session_state.conversations.items() if kept['thread_id'] is None), None)
        if blank:
            st.session_state.active_conversation = blank
        else:
            new_conversation()
        st.session_state.selected_listing = None
    st.session_state.notice = t('Conversation deleted.', '已删除这段对话。')


def refresh_new_conversations():
    """After the long-term profile or a switch may have changed (on a page, or in chat: a reply can
    save automatically), read it again; conversations not started yet follow it."""
    profile = read_profile()
    for conv in st.session_state.conversations.values():
        if conv['thread_id'] is None:
            start_from_profile(conv, profile)


def current():
    return st.session_state.conversations[st.session_state.active_conversation]


def title(conv):
    return conv['title'] if conv['title'] not in ('', NEW_TITLE) else t('New conversation', '新对话')


def start_session(client, account):
    """Signed in: the account's conversations from the backend, newest first, and a new one to start in."""
    threads = client.conversations()
    listings = client.my_listings()
    st.session_state.update(authenticated=True, client=client, faculty=account.get('faculty'),
                            profile={'name':account['username'], 'email':''}, conversations={}, active_conversation=None,
                            favorites={}, compare=[], selected_listing=None, page='Home',
                            shortlist=listings['shortlist'], excluded=listings['excluded'])
    for thread in reversed(threads):
        st.session_state.conversations[thread['id']] = _conversation(
            thread['title'] or NEW_TITLE, *empty(), thread_id=thread['id'], loaded=False, updated=thread.get('updated_at'))
    new_conversation()


def load(conv):
    """A backend conversation's messages, criteria, latest listings and shortlist. Fetched again
    on each run while its last message has no reply yet: a reply interrupted on this page (by a
    click while the agent worked) is still finished by the backend."""
    if conv['loaded'] or conv['thread_id'] is None:
        return
    client = st.session_state.client
    try:
        snapshot = client.conversation(conv['thread_id'])
    except BackendError as error:
        if error.status != 404:
            raise
        # Deleted elsewhere, such as on the backend's own page.
        del st.session_state.conversations[st.session_state.active_conversation]
        new_conversation()
        st.session_state.notice = t('That conversation no longer exists.', '这段对话已经不存在了。')
        return
    conv['messages'] = client.messages(conv['thread_id'])
    conv['criteria'] = {key: snapshot[key] for key in ('preferences', 'sources', 'items', 'profile_changes')}
    conv['requirements'], conv['preferences'] = from_backend(snapshot['preferences'])
    conv['recommendations'] = recommendations(snapshot['recommendations'])
    conv['preview'] = bool((snapshot['recommendations'] or {}).get('preview'))
    conv['comparison'] = snapshot.get('comparison')
    conv['compare'] = list((conv['comparison'] or {}).get('listing_ids') or [])
    st.session_state.shortlist = snapshot['shortlist']
    conv['loaded'] = not waiting_for_reply(conv)
    # The reply to Compare, read here when a click restarted the page meanwhile: a new table opens.
    if conv['loaded'] and (asked := conv.pop('compare_asked', None)) and conv['comparison'] and conv['comparison'] != asked[0]:
        conv['compare_show'] = True


def busy(conv):
    """The agent is working on this conversation: a message this run is sending, or one without a
    reply yet. Buttons that would ask it something else wait."""
    return st.session_state.get('sending', False) or waiting_for_reply(conv)


def waiting_for_reply(conv):
    return bool(conv['messages']) and conv['messages'][-1]['role'] == 'user'


def wait_for_reply(conv, sending=False):
    """The agent works on the conversation's latest message (sending: one this run sends, not among
    its messages yet). Until the reply is seen or a turn's time is up, the history shows a spinner on
    it, even after the page leaves it. A wait already noted is kept, unless a message is sent."""
    if sending or 'waiting_since' not in conv:
        conv['waiting_since'] = time.time()
        # How many messages the conversation has once the reply is there.
        conv['reply_count'] = len(conv['messages']) + (2 if sending else 1)


def stop_waiting(conv):
    conv.pop('waiting_since', None)
    conv.pop('reply_count', None)


def replying(conv):
    since = conv.get('waiting_since')
    return live() and since is not None and time.time() - since <= TURN_TIMEOUT_SECONDS


def replied(conv, messages):
    """messages, the conversation's as the backend has them, include the reply waited for."""
    return len(messages) >= conv.get('reply_count', 0) and bool(messages) and messages[-1]['role'] == 'assistant'


@st.cache_data(ttl=3600, show_spinner=False)
def faculties(base_url=None):
    return BackendClient(base_url or backend_url()).faculties()


def current_faculty():
    """The signed-in account's faculty ({name, zh, campus, code, latitude, longitude}), or None."""
    name = st.session_state.get('faculty')
    return next((faculty for faculty in faculties() if faculty['name'] == name), None) if name else None


def refresh_snapshot(api):
    version = api.sources.get('source_version')
    if version == st.session_state.get('rental-source-version'):
        return
    ids = {listing.id for listing in api.all_listings()}
    for conv in st.session_state.conversations.values():
        if conv['recommendations'] is not None:
            conv['recommendations'] = api.recommendations(conv['requirements'], conv['preferences'])
    st.session_state.compare = [listing_id for listing_id in st.session_state.compare if listing_id in ids]
    if st.session_state.selected_listing not in ids:
        st.session_state.selected_listing = None
    st.session_state['rental-source-version'] = version

def navigate(page):
    st.session_state.page = page
    st.rerun()


def favorite_ids():
    """Saved listings: the account's shortlist on the backend, or this session's in the offline demo."""
    return list(st.session_state.shortlist) if live() else list(st.session_state.favorites)


def toggle_favorite(listing_id):
    if live():
        client = st.session_state.client
        if listing_id in st.session_state.shortlist:
            listings = client.shortlist_remove(listing_id)
            st.session_state.notice = t('Removed from your favorites.', '已取消收藏。')
        else:
            listings = client.shortlist_add(listing_id)
            st.session_state.notice = t('Saved to your favorites, in every conversation. The agent can see it too.', '已收藏，所有对话都能看到，agent 也能看到。')
        st.session_state.shortlist, st.session_state.excluded = listings['shortlist'], listings['excluded']
    elif listing_id in st.session_state.favorites:
        del st.session_state.favorites[listing_id]
        st.session_state.notice = t('Favorite removed.', '已取消收藏。')
    else:
        st.session_state.favorites[listing_id] = datetime.now().isoformat(timespec='seconds')
        st.session_state.notice = t('Saved for this session.', '已收藏（仅本次会话）。')

def compare_ids():
    """The listings chosen to compare: this conversation's with the backend, this session's offline."""
    return list(current()['compare']) if live() else list(st.session_state.compare)


def compare_message(ids):
    """The chat message asking the agent to compare listings."""
    return t(f"Compare {', '.join(ids[:-1])} and {ids[-1]}.", f"比较 {'、'.join(ids[:-1])} 和 {ids[-1]}")


def toggle_compare(listing_id):
    """Put a listing in the compare box or take it out, up to three. With the backend nothing is asked
    until Compare is pressed (start_compare). Offline, the Favorites page shows the chosen listings
    in a table."""
    ids = current()['compare'] if live() else st.session_state.compare
    if listing_id in ids:
        ids.remove(listing_id)
        if live():
            st.session_state.notice = t('Taken out of the compare box.', '已移出比较框。')
    elif len(ids) >= 3:
        st.session_state.notice = (t('The compare box holds up to three listings. Take one out first.', '比较框最多放 3 套，请先拿出一套。') if live()
                                   else t('Compare up to three listings. Remove one before adding another.', '最多比较三套房源，请先移除一套。'))
    else:
        ids.append(listing_id)
        if live():
            st.session_state.notice = t(f'In the compare box ({len(ids)} of 3). Press Compare to compare them.', f'已放进比较框（{len(ids)}/3 套），按“开始比较”才会比较。')


def start_compare(conv):
    """Ask the agent to compare the listings in the compare box, from Home. The table it replies with
    opens by itself, once (see Home's compare bar)."""
    # The comparison before, to tell the reply's from it when the page reads the reply again.
    conv['compare_asked'] = (conv['comparison'],)
    send_from_home(compare_message(conv['compare']))


def send_from_home(message):
    """Send the agent a message from Home. From another page, Home is shown first and the message
    goes in the run after, so nothing of that page is left on screen while the agent works."""
    if st.session_state.page == 'Home':
        st.session_state.pending_message = message
    else:
        st.session_state.deferred_message = message
        st.session_state.page = 'Home'

def logout(expired=False):
    """Signs out; with the backend, also revokes the token and forgets the remember-me cookie."""
    client = st.session_state.get('client')
    if client is not None:
        if not expired:
            client.sign_out()
        st.session_state['cookie-action'] = 'delete'
    if expired:
        st.session_state['auth-error'] = t('Your sign-in has ended. Sign in again.', '登录已过期，请重新登录。')
    kept = {key: st.session_state[key] for key in _KEPT_ON_SIGN_OUT if key in st.session_state}
    for key in list(st.session_state):
        del st.session_state[key]
    st.session_state.update(kept)
    st.rerun()
