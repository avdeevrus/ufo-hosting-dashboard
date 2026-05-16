"""
UFO Hosting — Entrypoint мультистраничного приложения.

Запуск локально:    streamlit run src/app.py
Деплой в облако:    Streamlit Community Cloud (привязать GitHub-репо)

Структура (БЕЗ pages/ директории — иначе Streamlit Cloud конфликтует
с st.navigation и показывает дубли + название «app»):
  • _dashboard_main.py — главная страница (для руководителя)
  • _quality_page.py   — детальная аналитика Я.Директа
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

# Регистрируем страницы через st.navigation. ВАЖНО: pages/ директории
# быть НЕ ДОЛЖНО — иначе Streamlit Cloud параллельно с явной навигацией
# вытаскивает её автоматически и в сайдбаре появляется «app» + дубли.
dashboard_page = st.Page(
    "_dashboard_main.py",
    title="Дашборд окупаемости",
    icon="📊",
    url_path="dashboard",
    default=True,
)
# url_path в латинице — критично! Без него Streamlit формирует URL из title
# («/Качество рекламы»), кириллица URL-encoded ломает внутренние эндпоинты
# Streamlit Cloud / HF Spaces (_stcore/host-config, _stcore/health → 404).
quality_page = st.Page(
    "_quality_page.py",
    title="Качество рекламы",
    icon="🎯",
    url_path="quality",
)

nav = st.navigation([dashboard_page, quality_page])
nav.run()
