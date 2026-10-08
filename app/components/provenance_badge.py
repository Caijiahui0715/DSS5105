import streamlit as st
from content.i18n import t
from domain.provenance import label, display

def fact(name, value, provenance='source'):
    st.markdown(f'**{name}**')
    st.write(display(value))
    st.caption(label('unavailable' if value in (None, 'unknown', '') else provenance))

def explanation():
    st.caption(t('Source data = supplied facts · Derived value = calculation · Demo estimate = illustrative · Not available = not supplied',
                 '来源数据 = 原始信息 · 派生值 = 计算得出 · 演示估计 = 仅作示意 · 无数据 = 未提供'))
