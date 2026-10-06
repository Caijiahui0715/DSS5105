from pathlib import Path
from streamlit.testing.v1 import AppTest
import pytest

ENTRY=Path(__file__).resolve().parents[1]/'streamlit_app.py'


@pytest.fixture(autouse=True)
def offline_photos(monkeypatch):
    from components import listing_card
    monkeypatch.setattr(listing_card, 'source_image', lambda url: None)

def button(app,label):
    return next(b for b in app.button if b.label==label)

def test_auth_password_discarded():
    app=AppTest.from_file(str(ENTRY),default_timeout=45).run()
    assert not app.exception
    app.text_input(key='login-name').set_value('Student')
    app.text_input(key='login-email').set_value('student@example.com')
    app.text_input(key='login-password').set_value('temporary-secret')
    button(app,'Sign in').click().run()
    assert not app.exception
    assert app.session_state.authenticated
    assert app.session_state.profile['name']=='Student'
    assert 'login-password' not in app.session_state
    assert all('temporary-secret' not in str(value) for value in app.session_state.values())

def test_home_rail_chat_selection_and_history(monkeypatch):
    app=AppTest.from_file(str(ENTRY),default_timeout=45).run()
    button(app,'Continue with demo account').click().run()
    assert not app.exception
    assert {b.label for b in app.button if (b.key or '').startswith('nav-')} == {'Home','Favorites','Profile'}
    assert not any(item.label=='Recommended listings' for item in app.selectbox)
    button(app,'Hide conversation history').click().run()
    assert not app.session_state.history_open
    assert not any(b.label=='New conversation' for b in app.button)
    button(app,'Toggle conversation history').click().run()
    assert app.session_state.history_open
    button(app,'Find a room under SGD 2,500 near NUS with MRT access.').click().run()
    assert not app.exception
    active=app.session_state.active_conversation
    assert len(app.session_state.conversations[active]['messages'])==2
    button(app,'Save').click().run()
    assert len(app.session_state.favorites)==1
    button(app,'Compare').click().run()
    assert len(app.session_state.compare)==1
    selector=app.selectbox(key='recommended-listing-selector')
    ids=[r.listing_id for r in app.session_state.conversations[active]['recommendations']]
    selector.select(ids[1]).run()
    assert app.session_state.selected_listing==ids[1]
    button(app,'Favorites').click().run()
    assert not app.exception
    button(app,'Profile').click().run()
    next(item for item in app.number_input if item.label.startswith('Maximum advertised')).set_value(1800)
    button(app,'Save profile').click().run()
    assert app.session_state.requirements.max_budget==1800
    button(app,'Home').click().run()
    button(app,'New conversation').click().run()
    assert app.session_state.active_conversation!=active
    assert app.session_state.selected_listing is None
    assert not any(item.label=='Recommended listings' for item in app.selectbox)
    app.button(key=f'recent-{active}').click().run()
    assert app.session_state.active_conversation==active
    assert not app.exception
    button(app,'Log out').click().run()
    assert not app.session_state.authenticated
    assert not app.session_state.favorites


def test_compare_limit_and_hidden_pages(monkeypatch):
    from components import listing_card
    monkeypatch.setattr(listing_card,'source_image',lambda url:None)
    app=AppTest.from_file(str(ENTRY),default_timeout=45).run()
    button(app,'Continue with demo account').click().run()
    # Existing secondary views stay implemented without cluttering the rail.
    for page in ['Recommendations','Rental Map','Conversation History','Evaluation']:
        app.session_state.page=page
        app.run()
        assert not app.exception, page
    app.session_state.page='Recommendations'
    app.run()
    for _ in range(4):
        button(app,'Compare').click().run()
    assert len(app.session_state.compare)==3
    app.session_state.page='Rental Map'
    app.run()
    app.selectbox(key='all-listing-selector').select('500253628').run()
    assert app.session_state.selected_listing=='500253628'
    assert not app.exception


def test_invalid_login_password_discarded():
    app=AppTest.from_file(str(ENTRY),default_timeout=45).run()
    app.text_input(key='login-password').set_value('short')
    button(app,'Sign in').click().run()
    assert not app.session_state.authenticated
    assert app.session_state.get('login-password','')==''
    assert app.error


def registration_app():
    app = AppTest.from_file(str(ENTRY), default_timeout=45).run()
    app.text_input(key='register-name').set_value('Student')
    app.text_input(key='register-email').set_value('student@example.com')
    app.text_input(key='register-password').set_value('temporary-secret')
    return app


def test_registration_cannot_skip_hard_requirements():
    app = registration_app()
    button(app, 'Skip soft preferences and create profile').click().run()
    assert not app.exception
    assert not app.session_state.authenticated
    assert 'cannot be skipped' in app.error[0].value
    # Values survive a failed submission; only the password is discarded.
    app.number_input(key='register-budget').set_value(1800)
    app.selectbox(key='register-scope').select('room')
    app.text_input(key='register-password').set_value('temporary-secret')
    button(app, 'Create demo profile').click().run()
    assert not app.session_state.authenticated
    assert app.number_input(key='register-budget').value == 1800
    assert app.session_state.get('register-password', '') == ''
    app.selectbox(key='register-bedrooms').select('No minimum')
    app.text_input(key='register-password').set_value('temporary-secret')
    app.multiselect(key='register-districts').select('D05')
    app.number_input(key='register-commute').set_value(30)
    button(app, 'Skip soft preferences and create profile').click().run()
    assert not app.exception
    assert app.session_state.authenticated
    req, pref = app.session_state.requirements, app.session_state.preferences
    assert (req.max_budget, req.rental_scope, req.min_bedrooms) == (1800, 'room', None)
    assert pref.districts == [] and pref.commute_minutes is None and pref.mrt_distance is None
    active = app.session_state.conversations[app.session_state.active_conversation]
    assert active['requirements'] == req and active['preferences'] == pref
    app.chat_input(key='rental-chat-input').set_value('Show matching listings').run()
    assert not app.exception
    active = app.session_state.conversations[app.session_state.active_conversation]
    assert active['recommendations']
    assert all(r.evaluation.status != 'fail' for r in active['recommendations'])
    assert all(r.breakdown['Demo commute'] is None and r.breakdown['MRT accessibility'] is None for r in active['recommendations'])
    button(app, 'Profile').click().run()
    button(app, 'Save profile').click().run()
    assert not app.exception
    assert app.session_state.preferences.commute_minutes is None


def test_registration_saves_selected_preferences():
    app = registration_app()
    app.number_input(key='register-budget').set_value(4000)
    app.selectbox(key='register-scope').select('entire_unit')
    app.selectbox(key='register-bedrooms').select(2)
    app.multiselect(key='register-districts').select('D05')
    app.number_input(key='register-commute').set_value(30)
    app.selectbox(key='register-furnishing').select('fully_furnished')
    button(app, 'Create demo profile').click().run()
    assert not app.exception
    assert app.session_state.authenticated
    assert app.session_state.requirements.min_bedrooms == 2
    assert app.session_state.preferences.districts == ['D05']
    assert app.session_state.preferences.commute_minutes == 30
    assert app.session_state.preferences.furnishing == 'fully_furnished'
    assert all('temporary-secret' not in str(value) for value in app.session_state.values())


def test_snapshot_refresh_handles_old_favorites_and_conversations():
    from types import SimpleNamespace
    app = AppTest.from_file(str(ENTRY), default_timeout=45).run()
    button(app, 'Continue with demo account').click().run()
    removed_id = '23999583'
    app.session_state.favorites = {removed_id:'2026-09-09'}
    app.session_state.compare = [removed_id]
    app.session_state.selected_listing = removed_id
    app.session_state['rental-source-version'] = 'old-snapshot'
    conv = app.session_state.conversations[app.session_state.active_conversation]
    conv['recommendations'] = [SimpleNamespace(listing_id=removed_id)]
    app.session_state.page = 'Favorites'
    app.run()
    assert not app.exception
    assert app.session_state.compare == []
    assert app.session_state.selected_listing is None
    conv = app.session_state.conversations[app.session_state.active_conversation]
    assert conv['recommendations']
    assert removed_id not in {rec.listing_id for rec in conv['recommendations']}
    assert removed_id in app.session_state.favorites
    assert any('outside the current active snapshot' in warning.value for warning in app.warning)
    button(app, 'Remove unavailable favorite').click().run()
    assert not app.session_state.favorites
