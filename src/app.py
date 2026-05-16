"""
UFO Hosting — Entrypoint мультистраничного приложения.

Запуск локально:    streamlit run src/app.py
Деплой в облако:    Streamlit Community Cloud (привязать GitHub-репо)

Структура:
  • _dashboard_main.py        — главная страница (для руководителя)
  • pages/1_🎯_Качество_рекламы.py  — детальная аналитика Я.Директа
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="UFO Hosting · Дашборд",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Sys path для импортов из соседних модулей
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Регистрируем страницы через st.navigation, чтобы у главной было
# красивое имя «📊 Дашборд окупаемости» (по умолчанию Streamlit взял бы «App»).
dashboard_page = st.Page(
    "_dashboard_main.py",
    title="Дашборд окупаемости",
    icon="📊",
    default=True,
)
quality_page = st.Page(
    "pages/1_🎯_Качество_рекламы.py",
    title="Качество рекламы",
    icon="🎯",
)

nav = st.navigation([dashboard_page, quality_page])
nav.run()
