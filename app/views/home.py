import time
from datetime import datetime
from html import escape
import streamlit as st
from components.navigation import conversation_sidebar
from components.map_view import map_view, big_map
from components.listing_details import compact_details
from components.listing_card import heading, mrt_text, commute_text, link_note, image
from components.criteria_panel import criteria_form, drop_message, label, other_criteria
from content.en import PROMPTS, PROMPTS_ZH
from content.i18n import t, language, describe
from domain.criteria import criteria_message
from state.session_store import (current, live, busy, waiting_for_reply, wait_for_reply, stop_waiting, replied, read_profile, refresh_new_conversations, compare_message, NEW_TITLE,
                                 favorite_ids, toggle_favorite, toggle_compare, compare_ids)
from adapters.backend_client import SessionExpired, BackendError, TURN_TIMEOUT_SECONDS
from domain.models import ApiError


def as_markdown(text):
    """Chat text as Streamlit shows it: "S$" amounts are not LaTeX, and each line stays a line
    (the agent puts every listing fact on its own line; markdown would join them)."""
    return text.replace('$', '\\$').replace('\n', '  \n')


def send(message, agent, thread):
    """One message to the agent. The message shows at once in the thread, with the agent's progress under it."""
    conv = current()
    with thread:
        with st.container(key=f"chat-user-{len(conv['messages'])}"):
            with st.chat_message('user'):
                st.markdown(as_markdown(message))
        try:
            if live():
                # Read the conversation from the backend again unless this run sees the reply through:
                # a click while the agent works restarts the page, and the backend still finishes the turn.
                conv['loaded'] = False
                with st.status(t('Working on your request…', '正在处理你的请求…')) as status:
                    response = agent.respond(conv, message, language(), lambda text: status.update(label=text))
                    status.update(label=t('Done', '完成'), state='complete')
            else:
                with st.spinner(t('Searching static listings…', '正在搜索静态房源…')):
                    response = agent.respond(message, conv['requirements'], conv['preferences'], conv['messages'])
        except SessionExpired:
            raise
        except ApiError as exc:
            # The backend may have kept the message anyway; the conversation is read from it again.
            st.error(describe(exc))
            return
    conv['messages'].extend([{'role': 'user', 'text': message}, {'role': 'assistant', 'text': response.text, 'clarification': response.clarification, 'steps': response.steps}])
    conv['requirements'], conv['preferences'] = response.requirements, response.preferences
    # A turn without a search keeps the listings already in the panel.
    if response.recommendations is not None:
        conv['recommendations'], conv['preview'] = response.recommendations, response.preview
        st.session_state.selected_listing = response.recommendations[0].listing_id if response.recommendations else None
    if response.shortlist is not None:
        st.session_state.shortlist = response.shortlist
    if response.criteria is not None:
        conv['criteria'] = response.criteria
    # A comparison: the Compare bar shows it, and the listings chosen are those compared.
    if response.comparison is not None:
        conv['comparison'] = response.comparison
        conv['compare'] = list(response.comparison['listing_ids'])
        conv['compare_new'] = len(conv['compare']) >= 2
    conv['updated'] = datetime.now().isoformat(timespec='seconds')
    conv['loaded'] = True
    if live():
        # The reply may have saved to the long-term profile or switched memory or auto-save.
        refresh_new_conversations()
    st.rerun()


def ask(message):
    """A criteria change from the panel, sent to the agent like a typed message."""
    if message:
        st.session_state.pending_message = message
    else:
        st.session_state.notice = t('Nothing changed.', '没有改动。')
    st.rerun()


def criteria_panel(api):
    """This conversation's criteria above its listings. Changes go to the agent as a message and stay
    in this conversation; saving them to the long-term profile is a separate step."""
    conv = current()
    # What this conversation changed that the long-term profile does not have yet, as of the last
    # reply; shown above the panel so it is seen while the panel is closed.
    if unsaved := conv['criteria'].get('profile_changes'):
        names = ('、' if language() == 'zh' else ', ').join(row['label'][language()] for row in unsaved)
        st.caption(t(f"{len(unsaved)} change{'s' if len(unsaved) > 1 else ''} not saved to your long-term profile ({names}); save it below.",
                     f"有 {len(unsaved)} 项改动还没存到长期资料（{names}），可以在下面保存。"))
    with st.expander(t("This conversation's criteria", '本次对话的条件'), icon=':material/tune:'):
        st.caption(t('Changes here are sent to the agent as a message. They stay in this conversation until you save them to your long-term profile.',
                     '这里的修改会作为一条消息发给 agent，只改这段对话；存为长期资料后，长期资料才会跟着改。'))
        working = busy(conv)
        criteria_form(api, conv['criteria'], 'conversation', t('Send the changes to the agent', '把修改发给 agent'),
                      lambda before, after: ask(criteria_message(before, after, language())), disabled=working)
        other_criteria(conv['criteria'], 'conversation', lambda item: ask(drop_message(item)), disabled=working)
        st.divider()
        save_controls(conv)


def save_controls(conv):
    """Save this conversation's criteria to the long-term profile, after seeing what that changes."""
    client = st.session_state.client
    if conv['thread_id'] is None:
        st.caption(t('Once the conversation starts, its criteria can be saved to your long-term profile.', '对话开始后，可以把它的条件存为长期资料。'))
        return
    key = f"profile-preview-{conv['thread_id']}"
    if st.button(t('Save to long-term profile', '存为长期资料'), icon=':material/bookmark_add:', key='save-profile-preview'):
        st.session_state[key] = client.profile_changes(conv['thread_id'])
    preview = st.session_state.get(key)
    if not preview:
        return
    lang = language()
    if not preview['changes']:
        st.info(t('Your long-term profile already has these criteria; nothing to save.', '长期资料里已经是这些条件，没有要保存的改动。'))
        del st.session_state[key]
        return
    st.markdown(t('**Saving changes your long-term profile like this:**', '**保存后，长期资料会这样改：**'))
    st.markdown('\n'.join(f"- {label(row)}{'：' if lang == 'zh' else ': '}{row['before'][lang]} → {row['after'][lang]}" for row in preview['changes']))
    off = preview['memory'] == 'off'
    if off:
        st.warning(t('Long-term memory is off. Switch it on and save?', '长期记忆已关闭，要打开并保存吗？'))
    confirm, cancel = st.columns(2)
    if confirm.button(t('Switch on and save', '打开并保存') if off else t('Save', '确认保存'), type='primary', key='save-profile-confirm'):
        client.save_profile(conv['thread_id'], switch_on=off)
        del st.session_state[key]
        conv['criteria'] = {**conv['criteria'], 'profile_changes': []}
        refresh_new_conversations()
        st.session_state.notice = t('Saved to your long-term profile. New conversations start from it.', '已存为长期资料，新对话会按它开始。')
        st.rerun()
    if cancel.button(t('Cancel', '取消'), key='save-profile-cancel'):
        del st.session_state[key]
        st.rerun()


def auto_save_offer(conv):
    """Above the chat input, once this conversation has criteria: offer to save the criteria changed
    in conversations to the long-term profile automatically, while it is off and until the user
    closes the offer for good. After switching it on here, how to stop, until closed."""
    client = st.session_state.client
    if done := st.session_state.get('auto-save-done'):
        # A row that keeps the buttons their own width; the text takes the rest and wraps.
        with st.container(key='auto-save-done', horizontal=True, wrap=False, vertical_alignment='center', gap='small'):
            st.markdown(auto_save_confirmation(**done))
            if st.button(t('Close', '关闭'), icon=':material/close:', key='auto-save-done-close', help=t('Close', '关闭')):
                del st.session_state['auto-save-done']
                st.rerun()
        return
    profile = st.session_state.get('long_term') or read_profile()
    if conv['thread_id'] is None or not conv['criteria']['preferences'] or not profile.get('auto_save_offer'):
        return
    with st.container(key='auto-save-offer', horizontal=True, wrap=False, vertical_alignment='center', gap='small'):
        st.markdown(t('Save the criteria you change in conversations to your long-term profile automatically?', '以后对话里改的条件，自动存到长期资料吗？'))
        if st.button(t('Auto-save', '自动保存'), key='auto-save-on', type='primary', disabled=busy(conv)):
            result = client.auto_save_from(conv['thread_id'])
            conv['criteria'] = {**conv['criteria'], 'profile_changes': []}
            st.session_state['auto-save-done'] = {'saved': len(result['changes']), 'memory_on': profile['memory'] == 'undecided'}
            refresh_new_conversations()
            st.rerun()
        if st.button(t('Do not ask again', '不再提示'), icon=':material/close:', key='auto-save-close', help=t('Do not ask again', '不再提示')):
            st.session_state.long_term = client.close_auto_save_offer()
            st.rerun()


def auto_save_confirmation(saved, memory_on):
    """saved: how many changes switching auto-save on saved at once; memory_on: it switched memory on too."""
    return t(
        'Auto-save is on' + (' and so is long-term memory' if memory_on else '') + ': criteria you change in conversations are now saved to your long-term profile'
        + (f" (the {saved} change{'s' if saved > 1 else ''} made so far {'were' if saved > 1 else 'was'} saved)" if saved else '')
        + '. To stop, switch off “Auto-save” on the Profile page, or say “turn off auto-save” in the chat.',
        '已开启自动保存' + ('和长期记忆' if memory_on else '') + '：之后对话里改的条件会自动存进长期资料' + (f'（刚才的 {saved} 项改动已存）' if saved else '')
        + '。想停止，在个人资料页关掉“自动保存”，或者在对话里说“关闭自动保存”。',
    )


def map_dialog(api, conv):
    """The enlarged map in a wide window. A click on a listing shows a card under the map, with
    Save, Compare and Details, and the window stays open."""
    recommended = [rec.listing_id for rec in conv['recommendations'] or []]
    # Orange: the listing selected on Home. A pick does not redraw the map, which keeps its zoom.
    highlight = st.session_state.selected_listing

    def body():
        picked = big_map(api, recommended, favorite_ids(), compared_on_map(conv), highlight)
        if picked:
            st.session_state['map-picked'] = picked
        if picked := st.session_state.get('map-picked'):
            map_card(api, conv, picked, recommended)

    st.dialog(t('Map', '地图'), width='large')(body)()


def map_card(api, conv, listing_id, recommended):
    """The listing picked on the enlarged map: its photo, what it is, and what to do with it,
    including opening the original listing."""
    listing = api.details(listing_id)
    if listing is None:
        st.info(t('This listing is no longer in the data.', '这套房源已不在当前数据里。'))
        return
    rec = next((rec for rec in conv['recommendations'] or [] if rec.listing_id == listing_id), None)
    f = listing.facts
    with st.container(border=True, key='map-card'):
        photo, about = st.columns([2, 3])
        with photo:
            image(listing, width='stretch')
        with about:
            st.markdown(f"**{escape(f['displayTitle'])}** · {listing_id}")
            st.markdown(t(f"SGD {f['effectiveRentMonthlySgd']:,.0f} / month", f"每月 {f['effectiveRentMonthlySgd']:,.0f} 新元"))
            if rec:
                heading(rec)
            else:
                st.caption(t('Not in this search’s recommendations (a favorite)', '不在本次推荐里（收藏的房源）'))
            st.caption(mrt_text(listing, rec))
            st.caption(commute_text(listing, rec))
            link_note(rec)
        saved, comparing = listing_id in favorite_ids(), listing_id in compare_ids()
        link, save, compare, details = st.columns(4)
        link.link_button(t('Open ↗', '打开 ↗'), f['listingUrl'], help=t('Open the original listing in a new tab', '在新标签页打开原始房源'), width='stretch')
        if save.button(t('Unsave', '取消收藏') if saved else t('Save', '收藏'), key='map-card-save', width='stretch'):
            toggle_favorite(listing_id)
            st.rerun(scope='fragment')
        if compare.button(t('Remove compare', '移出比较') if comparing else t('Compare', '比较'), key='map-card-compare', width='stretch', disabled=busy(conv)):
            toggle_compare(listing_id)
            # A second or third listing asks the agent, from Home; otherwise the window stays.
            st.rerun(scope='app' if st.session_state.get('pending_message') else 'fragment')
        if details.button(t('Details', '查看详情'), key='map-card-details', type='primary', width='stretch'):
            st.session_state.selected_listing = listing_id
            if listing_id not in recommended:
                st.session_state.page = 'Favorites'
            st.rerun()


def await_reply(conv):
    """A reply this page stopped waiting for: a click while the agent works restarts the page, and
    the backend still finishes the turn. Ask the backend every 2 seconds and show the reply once it
    is there; after as long as a turn may take, say to send the message again."""
    wait_for_reply(conv)
    if time.time() - conv['waiting_since'] > TURN_TIMEOUT_SECONDS:
        st.info(t('No reply to this message arrived. Send it again.', '这条消息没有收到回复，请重新发送。'))
        st.button(t('Refresh', '刷新'), key='refresh-reply')
        return
    st.info(t('The agent is still working on this message; its reply will appear here.', 'agent 还在处理这条消息，回复好了会自动显示在这里。'))

    @st.fragment(run_every=2)
    def check():
        try:
            messages = st.session_state.client.messages(conv['thread_id'])
        except BackendError:
            return  # Asked again in 2 seconds.
        if replied(conv, messages):
            # The whole page reads the conversation again and shows the reply.
            conv['loaded'] = False
            st.rerun()

    check()


def compared_on_map(conv):
    """The listings of the conversation's comparison still chosen, in the table's order, while there
    are at least two: the map numbers them and frames them with the faculty."""
    comparison = conv['comparison'] or {'listing_ids': []}
    shown = [listing_id for listing_id in comparison['listing_ids'] if listing_id in conv['compare']]
    return shown if len(shown) >= 2 else []


def compare_bar(conv):
    """Between the map and the listings while listings are chosen to compare: one button that opens
    the comparison. It pulses with a "new" mark when a comparison arrives, until opened."""
    chosen = conv['compare']
    if not chosen:
        return
    new = conv['compare_new']
    with st.container(key='compare-bar-new' if new else 'compare-bar'):
        label = t(f'Compare ({len(chosen)})', f'比较（{len(chosen)} 套）') + (f" · **{t('New', '新')}**" if new else '')
        # Grey while the agent replies: a click then would restart the page mid-reply.
        working = busy(conv)
        if st.button(label, icon=':material/compare_arrows:', key='compare-open', width='stretch', disabled=working,
                     help=t('Opens once the agent has replied', '等 agent 回复后才能打开') if working else t('Open the comparison', '打开比较')):
            conv['compare_new'] = False
            comparison_dialog(conv)


def comparison_dialog(conv):
    """The comparison in a wide window: the table, one column per listing compared, with the key
    differences; or, before two are compared, what is still needed."""
    lang = language()
    chosen = conv['compare']
    comparison = conv['comparison'] or {'listing_ids': [], 'left_out': []}
    shown = [listing_id for listing_id in comparison['listing_ids'] if listing_id in chosen]
    removed = [listing_id for listing_id in comparison['listing_ids'] if listing_id not in chosen]
    separator = '、' if lang == 'zh' else ', '

    def body():
        if len(chosen) == 1:
            # Why the last comparison was not made, when it left only this one.
            notes = ' '.join(item['note'][lang] for item in comparison['left_out']) if comparison['listing_ids'] == chosen else ''
            st.info(f"{notes} {t('Choose one more listing to compare.', '再选一套就开始比较。')}".strip())
            return
        if busy(conv) and len(shown) < len(chosen):
            st.info(t('The agent is comparing them; the table appears here once it replies.', 'agent 正在比较，回复后表格会出现在这里。'))
            return
        # Listings removed since, or chosen but not compared (a reply that failed): compare them now.
        if removed or set(shown) != set(chosen):
            note = t(f'This comparison also covers {separator.join(removed)}, which you removed.', f'这次比较还包括已移出的 {separator.join(removed)}。') if removed else t('These listings are not compared yet.', '这几套还没有比较。')
            st.caption(note)
            if st.button(t('Compare again', '重新比较'), key='compare-again', icon=':material/refresh:'):
                ask(compare_message(chosen))
        if len(shown) < 2:
            return
        st.markdown(f"**{t('Key differences', '关键差异')}**{'：' if lang == 'zh' else ': '}{as_markdown(comparison['summary'][lang]) or t('none stand out', '没有明显差异')}")
        for item in comparison['left_out']:
            st.caption(item['note'][lang])
        # An HTML table wraps long values; "$" is written as an entity so it is not read as maths.
        cell = lambda text: escape(str(text)).replace('$', '&#36;')
        # Numbered as on the map.
        head = ''.join(f"<th>{number}. {cell(comparison['titles'].get(listing_id) or listing_id)}<br><small>{listing_id}</small></th>" for number, listing_id in enumerate(shown, 1))
        body_rows = ''.join(
            f"<tr><th scope='row'>{cell(row['label'][lang])}</th>" + ''.join(f"<td>{cell(row['values'][listing_id][lang])}</td>" for listing_id in shown) + '</tr>'
            for row in comparison['rows']
        )
        st.markdown(f"<table class='comparison-table'><thead><tr><th></th>{head}</tr></thead><tbody>{body_rows}</tbody></table>", unsafe_allow_html=True)
        st.caption(t(f"Compared on {comparison['date']}; whether each meets your criteria is as of then. Availability is not checked in real time.",
                     f"{comparison['date']} 比较；是否符合条件按当时的条件判断。房源是否还能租没有实时核实。"))

    st.dialog(t('Compare listings', '比较房源'), width='large')(body)()


def render(api, agent):
    conv = current()
    recs = conv['recommendations'] or []
    eligible_ids = [rec.listing_id for rec in recs]
    if not recs:
        st.session_state.selected_listing = None
    elif st.session_state.selected_listing not in eligible_ids:
        st.session_state.selected_listing = recs[0].listing_id
    center, right = st.columns([2.2, 1.5], gap='medium')
    with center:
        with st.container(key='chat-header'):
            if st.button(t('Toggle conversation history', '显示或隐藏对话记录'), icon=':material/menu:', help=t('Show or hide conversation history', '显示或隐藏对话记录'), key='toggle-history'):
                st.session_state.history_open = not st.session_state.get('history_open', True)
                st.rerun()
        thread = st.container(height=580, border=False, key='chat-thread')
        with thread:
            if not conv['messages']:
                st.markdown(t('## How can I help with your rental search?', '## 想找什么样的房子？'))
            for index, message in enumerate(conv['messages']):
                with st.container(key=f"chat-{message['role']}-{index}"):
                    with st.chat_message(message['role']):
                        st.markdown(as_markdown(message['text']))
                        if message.get('clarification'):
                            st.warning(message['clarification'])
                        if message.get('steps'):
                            with st.expander(t('How this reply was made', '这条回复是怎么得出的')):
                                st.markdown('\n'.join(f'- {as_markdown(step)}' for step in message['steps']))
            if live() and waiting_for_reply(conv):
                await_reply(conv)
            else:
                stop_waiting(conv)
        if live():
            auto_save_offer(conv)
        # A typed message, or one from another control or page (criteria, Compare, sign-up). It is
        # sent at the end, once the whole page is drawn: nothing from the page before is left faded
        # while the agent works, and the buttons that would ask it something else wait.
        outgoing = st.chat_input(t('Message the rental Agent', '给找房 agent 发消息'), key='rental-chat-input') or st.session_state.pop('pending_message', None)
        st.session_state.sending = bool(outgoing)
    with right:
        if live():
            criteria_panel(api)
        # The map fills its panel: 350px high with a 1px border (see streamlit_app.py).
        with st.container(height=350, border=True, key='map-panel'):
            map_view(api, key='home-map', height=348, listing_ids=eligible_ids, compact=True, compared_ids=compared_on_map(conv) if live() else ())
            # Laid over the map's top-right corner (see streamlit_app.py).
            if live() and st.button(t('Enlarge map', '放大地图'), icon=':material/open_in_full:', key='map-expand', help=t('Enlarge map', '放大地图')):
                st.session_state.pop('map-picked', None)
                map_dialog(api, conv)
        if live():
            compare_bar(conv)
        with st.container(height=420, border=True, key='listing-panel'):
            if not recs:
                st.caption(t('Your recommended listings will appear here.', '推荐的房源会显示在这里。'))
                st.markdown(t('**Try a rental request**', '**试试这样问**'))
                for i, prompt in enumerate(PROMPTS_ZH if language() == 'zh' else PROMPTS):
                    if st.button(prompt, key=f'prompt-{i}', width='stretch'):
                        outgoing = prompt
                if conv['recommendations'] == []:
                    st.caption(t('No recommended listings for this request. Try clarifying your needs; hard constraints are not silently relaxed.',
                                 '这次没有推荐的房源。可以把需求说得更具体；硬性条件不会被悄悄放宽。'))
            else:
                if conv.get('preview'):
                    st.caption(t('Preview only: your saved criteria have not changed.', '仅为预览：你保存的条件没有改变。'))
                index = {rec.listing_id: rec for rec in recs}
                def select_listing():
                    st.session_state.selected_listing = st.session_state['recommended-listing-selector']
                def label(value):
                    title = index[value].facts.get('title') or api.details(value).facts['displayTitle']
                    return f'#{index[value].rank} · {title} · {value}'
                st.session_state['recommended-listing-selector'] = st.session_state.selected_listing
                st.selectbox(t('Recommended listings', '推荐的房源'), eligible_ids, key='recommended-listing-selector', format_func=label, on_change=select_listing)
                selected = st.session_state.selected_listing
                compact_details(api.details(selected), index[selected])
    if outgoing:
        st.session_state.sending = True  # also for a suggested request, chosen after the input
        # Named and moved up the list now, as the backend does: a click while the agent works ends this
        # run before the reply, and the conversation should not stay "New conversation".
        if conv['title'] in ('', NEW_TITLE):
            conv['title'] = outgoing[:55]
        conv['updated'] = datetime.now().isoformat(timespec='seconds')
        if live():
            wait_for_reply(conv, sending=True)
    # The history is fixed at the left, so it is drawn last: it shows what this run sends.
    if st.session_state.get('history_open', True):
        conversation_sidebar()
    if st.session_state.get('deferred_message'):
        send_once_shown()
    if outgoing:
        send(outgoing, agent, thread)


def send_once_shown():
    """A message from another page: this run only draws Home, and finishing it clears that page
    from the screen; a moment later the message is sent in a new run, as if typed here."""
    st.session_state['deferred-ready'] = False

    @st.fragment(run_every=0.3)
    def later():
        # The first call is part of this run; the timer's next one comes after it has finished.
        if not st.session_state.get('deferred-ready'):
            st.session_state['deferred-ready'] = True
            return
        st.session_state.pending_message = st.session_state.pop('deferred_message', None)
        st.rerun()

    later()
