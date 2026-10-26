import streamlit as st
from components.listing_card import card
from components.listing_details import details, full_details
from components.comparison import comparison
from components.compare_box import compare_box
from views.home import compare_buttons
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
        st.caption(t('Your favorites, the same in every conversation. The agent sees them too, so you can also ask it about them in chat; new searches leave them out and say when one still matches.',
                     '这些是你的收藏，所有对话共用。agent 也能看到，也可以在对话里问它；新的搜索不会重复推荐它们，符合条件时会提一句。'))
    else:
        st.caption(t('Saved listings persist only during the active Streamlit session.', '收藏只在本次会话中保留。'))
    ids = favorite_ids()
    # Comparison is independent of saved favorites and must remain visible without them.
    comparison_ids = list(dict.fromkeys([*ids, *st.session_state.compare]))
    index = {rec.listing_id: rec for rec in current()['recommendations'] or []} if live() else demo_recommendations(api, comparison_ids)
    # With the backend, the agent compares the listings in the compare box; offline, a table here.
    if not live():
        comparison(api,list(index.values()))
    elif ids or current()['compare']:
        compare_section(api)
    if not ids:
        st.info(t('No saved listings yet. Save an option from the listing panel on Home.', '还没有收藏。可以在首页的房源面板里收藏。'))
        return
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
        rec = index.get(listing_id)
        # With the backend, each card folds its full details; offline, the selected favorite's show below.
        more = (lambda listing=listing, rec=rec, key=f'fav-{listing_id}': full_details(listing, rec, key)) if live() else None
        card(listing, rec, f'fav-{listing_id}', more)
    selected = st.session_state.selected_listing
    if not live() and selected in ids:
        details(api.details(selected),index.get(selected),'fav-selected')


def compare_section(api):
    """Above the favorites: the compare box, and Compare, which asks the agent from Home."""
    with st.container(border=True, key='compare-section'):
        st.subheader(t('Compare', '比较'))
        st.caption(t('Drag listings into the compare box, or press “Add to compare” on a card. The order in the box is the order of the table’s columns; nothing is compared until you press Compare.',
                     '把房源拖进比较框，或者在卡片上点“放进比较框”。框里的顺序就是比较表的列顺序，按“开始比较”才会比较。'))
        compare_box(api)
        compare_buttons(current(), prefix='fav-', clear=True)
