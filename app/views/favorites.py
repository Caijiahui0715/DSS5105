import streamlit as st
from components.listing_card import card
from components.listing_details import details
from components.comparison import comparison
from content.i18n import t
from domain.models import Recommendation
from state.session_store import current, live, favorite_ids, toggle_favorite


def demo_recommendations(api, ids):
    """Offline demo: current recommendations plus a demo evaluation of each other favorite."""
    from views.recommendations import active_recommendations
    from domain.recommendation import evaluate
    from data.demo_enrichment import demo_score
    index = {rec.listing_id:rec for rec in active_recommendations(api)}
    conv = current()
    for listing_id in ids:
        listing = api.details(listing_id)
        if listing is not None and listing_id not in index:
            score,breakdown,reasons,tradeoffs,unknown = demo_score(listing,conv['requirements'],conv['preferences'])
            index[listing_id] = Recommendation(listing_id,0,score,'Outside current eligible recommendations',evaluate(listing,conv['requirements']),reasons,tradeoffs,unknown,breakdown)
    return index


def render(api):
    st.title(t('Favorites', '收藏'))
    if live():
        st.caption(t('Your favorites, the same in every conversation. The agent sees them too, so you can ask it to compare them; new searches leave them out and say when one still matches.',
                     '这些是你的收藏，所有对话共用。agent 也能看到，可以让它帮你比较；新的搜索不会重复推荐它们，符合条件时会提一句。'))
    else:
        st.caption(t('Saved listings persist only during the active Streamlit session.', '收藏只在本次会话中保留。'))
    ids = favorite_ids()
    if not ids:
        st.info(t('No saved listings yet. Save an option from the listing panel on Home.', '还没有收藏。可以在首页的房源面板里收藏。'))
        return
    # The agent's latest results give each favorite its rank and status, where it is among them.
    index = {rec.listing_id: rec for rec in current()['recommendations'] or []} if live() else demo_recommendations(api, ids)
    comparison(api,list(index.values()))
    for listing_id in ids:
        saved = None if live() else st.session_state.favorites[listing_id]
        if saved:
            st.caption(t(f'Saved at {saved} (session time)', f'收藏于 {saved}（本次会话时间）'))
        listing = api.details(listing_id)
        if listing is None:
            st.warning(t(f'Listing {listing_id} is outside the current active snapshot. It is not offered as a recommendation.',
                         f'房源 {listing_id} 已不在当前数据里，不会再被推荐。'))
            if st.button(t('Remove unavailable favorite', '移除失效的收藏'), key=f'remove-unavailable-{listing_id}'):
                toggle_favorite(listing_id)
                st.rerun()
            continue
        card(listing,index.get(listing_id),f'fav-{listing_id}')
    selected = st.session_state.selected_listing
    if selected:
        details(api.details(selected),index.get(selected),'fav-selected')
