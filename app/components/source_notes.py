import streamlit as st
from content.i18n import t


def source_notes(listing):
    f = listing.facts
    label = t('Refreshed advertised rent', '重新检查后的广告月租') if f.get('rentSource') == 'refreshed_advertised' else t('Original advertised rent fallback; refreshed price unavailable', '没有重新检查的价格，显示原广告月租')
    st.caption(label + t(' · additional costs not confirmed', ' · 其他费用未确认'))
    checked = f.get('enrichedAt') or t('Not provided', '未提供')
    st.caption(t(f'Active at snapshot · checked {checked} (timezone unconfirmed)', f'快照时有效 · 检查于 {checked}（时区未确认）'))
    st.caption(t('Link status at that snapshot does not confirm availability now.', '快照时的链接状态不代表现在还能租。'))
