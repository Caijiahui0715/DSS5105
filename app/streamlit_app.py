import sys
from pathlib import Path
import streamlit as st

# The first Streamlit command, before imports that load cached source data.
st.set_page_config(page_title='NUS Rental Decision Agent',page_icon=':material/home:',layout='wide',initial_sidebar_state='collapsed')
APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0,str(APP_ROOT))

from state.session_store import initialize, refresh_snapshot, start_session, live, load, current, logout
from state import cookies
from adapters.configuration import create_adapters, offline, backend_url
from adapters.backend_client import BackendClient, BackendError, SessionExpired
from domain.models import ApiError
from content.i18n import t, describe
from components.navigation import navigation
from views import auth, home, profile, favorites

st.markdown('''<style>
:root {color-scheme:light;}
.stApp {background:#f7f8fa;color:#142c43;}
header[data-testid="stHeader"] {display:none;}
[data-testid="stSidebar"] {display:none;}
.stMainBlockContainer {padding:24px 24px 24px 96px;max-width:none;}
h1,h2,h3 {color:#122f4d;letter-spacing:-.025em;}
button[kind="primary"] {background:#173c5b;border-color:#173c5b;color:white;}
button:focus-visible,a:focus-visible {outline:3px solid #107a72!important;outline-offset:3px;}
[data-testid="stCaptionContainer"] {color:#516477;}
.st-key-global-rail {position:fixed;left:0;top:0;bottom:0;width:64px!important;padding:20px 9px;background:#edf2f5;border-right:1px solid #dce3e9;z-index:999;gap:14px!important;}
.st-key-global-rail button {height:44px;width:44px;padding:0;border:0;border-radius:10px;}
.st-key-global-rail button p {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
.st-key-global-rail button [data-testid="stIconMaterial"] {font-size:25px;}
.st-key-chat-history {position:fixed;left:64px;top:0;bottom:0;width:240px!important;padding:24px 14px;background:#edf2f5;border-right:1px solid #dce3e9;overflow-y:auto;z-index:100;}
.st-key-chat-history button {text-align:left;}
body:has(.st-key-chat-history) .stMainBlockContainer {padding-left:328px;}
body:has(.st-key-chat-thread) [data-testid="stMain"] {height:100dvh;overflow:hidden;}
.st-key-chat-header button {border:0;background:transparent;}
.st-key-chat-header button p {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
[data-testid="stLayoutWrapper"]:has(> .st-key-global-rail), [data-testid="stLayoutWrapper"]:has(> .st-key-chat-history) {display:contents;}
[data-testid="stLayoutWrapper"]:has(> .st-key-chat-thread), [data-testid="stLayoutWrapper"]:has(> .st-key-map-panel), [data-testid="stLayoutWrapper"]:has(> .st-key-listing-panel), .st-key-chat-thread, .st-key-map-panel, .st-key-listing-panel {min-height:0!important;max-height:none!important;}
[data-testid="stLayoutWrapper"]:has(> .st-key-chat-thread), .st-key-chat-thread {height:calc(100dvh - 240px)!important;flex-basis:calc(100dvh - 240px)!important;overflow-y:auto;}
.st-key-chat-thread h2 {padding-top:20vh;text-align:center;font-size:26px;}
.st-key-chat-thread {padding:8px 12px 24px;scrollbar-width:thin;}
.st-key-chat-thread [data-testid="stChatMessage"] {background:transparent;border-radius:0;padding:12px 0;gap:0;}
.st-key-chat-thread [data-testid="stChatMessage"] > :not([data-testid="stChatMessageContent"]) {display:none;}
.st-key-chat-thread [data-testid="stChatMessageContent"] {font-size:16px;line-height:1.75;min-width:0;}
.st-key-chat-thread [data-testid="stChatMessageContent"] p {font-size:16px;line-height:1.75;overflow-wrap:anywhere;}
.st-key-chat-thread [class*="st-key-chat-user-"] [data-testid="stChatMessage"] {margin-left:auto;width:fit-content;max-width:85%;padding:10px 18px;background:#e9edf1;border-radius:22px;align-items:center;}
.st-key-chat-thread [class*="st-key-chat-user-"] [data-testid="stChatMessageContent"] {margin:0;}
.st-key-chat-thread [class*="st-key-chat-user-"] [data-testid="stMarkdownContainer"] {margin-bottom:0;}
.st-key-chat-thread [class*="st-key-chat-user-"] [data-testid="stChatMessageContent"] {flex:1;width:auto;min-width:0;}
.st-key-chat-thread [data-testid="stChatMessage"], .st-key-chat-thread [data-testid="stChatMessageContent"], .st-key-chat-thread [data-testid="stChatMessageContent"] > [data-testid="stVerticalBlock"] {height:auto!important;flex-basis:auto!important;}
.st-key-chat-thread [class*="st-key-chat-user-"] [data-testid="stChatMessage"] {min-height:48px;}
.st-key-chat-thread [class*="st-key-chat-user-"] [data-testid="stMarkdownContainer"] p:last-child {margin-bottom:0;}
.st-key-chat-thread [class*="st-key-chat-assistant-"] [data-testid="stChatMessageContent"] {width:100%;padding:4px 6px;}
body:has(.st-key-chat-thread) [data-testid="stChatInput"] {border-radius:26px;background:#fff;border:1px solid #dce3e9;box-shadow:0 2px 8px #142c4308;margin-bottom:24px;}
body:has(.st-key-chat-thread) [data-testid="stChatInput"] textarea {font-size:16px;line-height:1.5;padding:14px 18px;}
body:has(.st-key-chat-thread) [data-testid="stChatInputSubmitButton"] {border-radius:50%;}
[data-testid="stLayoutWrapper"]:has(> .st-key-map-panel), .st-key-map-panel {height:350px!important;flex-basis:350px!important;overflow:hidden;}
[data-testid="stLayoutWrapper"]:has(> .st-key-listing-panel), .st-key-listing-panel {height:calc(100dvh - 454px)!important;flex-basis:calc(100dvh - 454px)!important;overflow-y:auto;}
.st-key-map-panel {padding:0!important;gap:0!important;}
.st-key-map-panel iframe {max-width:100%;display:block;}
.st-key-listing-panel h3 {font-size:21px;}
@media (max-width:1000px) {.st-key-chat-history {width:190px!important;} body:has(.st-key-chat-history) .stMainBlockContainer {padding-left:270px;} }
@media (max-width:760px) {
.stMainBlockContainer, body:has(.st-key-chat-history) .stMainBlockContainer {padding:16px 12px 16px 78px;}
.st-key-chat-history {width:240px!important;box-shadow:6px 0 20px #142c4320;}
body:has(.st-key-chat-thread) [data-testid="stMain"] {height:auto;overflow:auto;}
[data-testid="stHorizontalBlock"] {flex-wrap:wrap;} [data-testid="stColumn"] {min-width:100%!important;}
[data-testid="stLayoutWrapper"]:has(> .st-key-chat-thread), .st-key-chat-thread {height:55dvh!important;flex-basis:55dvh!important;}
[data-testid="stLayoutWrapper"]:has(> .st-key-map-panel), .st-key-map-panel {height:350px!important;flex-basis:350px!important;} [data-testid="stLayoutWrapper"]:has(> .st-key-listing-panel), .st-key-listing-panel {height:420px!important;flex-basis:420px!important;}
}
[data-testid="stLayoutWrapper"]:has(> .st-key-cookie-writer), .st-key-cookie-writer {position:absolute;width:0;height:0;overflow:hidden;}
@media (prefers-reduced-motion:reduce) {* {animation:none!important;transition:none!important;}}
</style>''',unsafe_allow_html=True)
initialize()


def sign_in_from_cookie():
    """Remember me: a token saved in this browser signs in without the form, once per session."""
    token = cookies.saved_token()
    if not token:
        return
    client = BackendClient(backend_url(), token)
    try:
        start_session(client, client.me())
    except SessionExpired:
        st.session_state['cookie-action'] = 'delete'
    except BackendError as error:
        st.session_state['auth-error'] = describe(error)


try:
    if not st.session_state.authenticated and not offline():
        sign_in_from_cookie()
    cookies.apply()
    if not st.session_state.authenticated:
        auth.render()
        st.stop()
    rental_api,agent_api = create_adapters(st.session_state.client)
    # The rail first, so a failure below still leaves a way to another page or to log out.
    navigation()
    if live():
        load(current())
    else:
        refresh_snapshot(rental_api)
    if st.session_state.notice:
        st.toast(st.session_state.notice)
        st.session_state.notice = None
    page = st.session_state.page
    if page == 'Home':
        home.render(rental_api,agent_api)
    elif page == 'Profile':
        profile.render(rental_api)
    elif page == 'Favorites':
        favorites.render(rental_api)
    elif offline() and page in ('Recommendations', 'Rental Map', 'Conversation History', 'Evaluation'):
        # Secondary views kept for later work; they run on the offline demo's own scoring, so
        # they are not loaded with the agent backend.
        from views import recommendations, rental_map, history, evaluation
        if page == 'Recommendations': recommendations.render(rental_api)
        elif page == 'Rental Map': rental_map.render(rental_api)
        elif page == 'Conversation History': history.render()
        else: evaluation.render(rental_api)
    else:
        st.error(t('Page not found. Use the navigation to return Home.', '找不到这个页面，请用左侧导航回到首页。'))
except SessionExpired:
    logout(expired=True)
except (ValueError,ApiError) as exc:
    st.error(describe(exc))
    if offline():
        st.info(t('Check source data or select static/mock adapters. No source files were changed.', '请检查数据文件。没有改动任何源文件。'))
