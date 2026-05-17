"""
UFO Hosting — Главная страница: управленческий дашборд окупаемости.

Запускается через app.py (st.navigation). НЕ запускать напрямую.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import streamlit as st

# st.set_page_config задаётся в app.py — это entrypoint навигации.

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import os
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    from data_loader import (
        ADS_DIR, ORDERS_DIR,
        ads_monthly_totals, load_ads, load_orders,
    )
    import metrics as M
    from yandex_direct import get_credentials as yd_creds
    import storage
except Exception as e:
    st.error("Ошибка инициализации приложения")
    st.code(traceback.format_exc())
    st.stop()


# ============================================================
#                       Защита паролем
# ============================================================

import hashlib as _hashlib


def _password_token(pwd: str) -> str:
    """Хэш для URL-токена. SHA-256 + соль, первые 24 символа."""
    salted = ("ufo-hosting-dashboard-2026:" + pwd).encode("utf-8")
    return _hashlib.sha256(salted).hexdigest()[:24]


def _check_password() -> bool:
    """Password-gate с persistence через URL-token.

    Если в Space Secrets нет APP_PASSWORD — приложение открыто всем (default).
    Если есть — при первом входе пользователь вводит пароль; после успешного
    ввода токен дописывается в URL (?t=<hash>), чтобы при следующем заходе
    на ту же ссылку login пропускался автоматически.
    Кнопка «Выйти» в сайдбаре сбрасывает session и убирает токен из URL.
    """
    expected = os.environ.get("APP_PASSWORD")
    if not expected:
        return True

    expected_token = _password_token(expected)

    # Уже залогинены в этой сессии
    if st.session_state.get("auth_ok"):
        return True

    # Проверка persistent токена в URL
    url_token = st.query_params.get("t")
    if url_token == expected_token:
        st.session_state["auth_ok"] = True
        return True

    # Login-экран
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] { display: none !important; }
        .main .block-container { max-width: 420px !important; margin: 6rem auto !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div style="text-align:center; margin-bottom:1.5rem;">
            <h2 style="margin:0;">UFO Hosting</h2>
            <div style="color:#57606a; font-size:0.9rem; margin-top:0.4rem;">Дашборд окупаемости рекламы</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    pwd = st.text_input("Пароль доступа", type="password", key="login_pwd")
    remember = st.checkbox("Запомнить меня на этом устройстве", value=True, key="login_remember")
    if pwd:
        if pwd == expected:
            st.session_state["auth_ok"] = True
            if remember:
                # Persistent токен в URL — при возврате по ссылке login пропускается
                st.query_params["t"] = expected_token
            st.rerun()
        else:
            st.error("Неверный пароль", icon="🔒")
    st.caption("Доступ ограничен. Получите пароль у владельца дашборда.")
    return False


if not _check_password():
    st.stop()


# ============================================================
#                       Progress-индикатор
# ============================================================
# Виден сразу после ввода пароля — пользователь не смотрит на пустой экран,
# пока бэкенд парсит CSV/XLSX и считает метрики. Обновляется на каждом этапе
# и автоматически убирается в конце скрипта.
_progress_placeholder = st.empty()


def _progress(stage: str, pct: int) -> None:
    """Обновляет видимый прогресс-бар. pct: 0-100."""
    _progress_placeholder.progress(pct / 100, text=f"⏳ {stage}")


def _progress_done() -> None:
    """Убирает прогресс-бар. Вызывается когда вся загрузка завершена."""
    _progress_placeholder.empty()


_progress("Запускаю дашборд…", 5)


# ============================================================
#                       Стили
# ============================================================

PALETTE = {
    "bg": "#ffffff",
    "panel": "#f6f8fa",
    "border": "#d0d7de",
    "text": "#0d1117",
    "muted": "#57606a",
    "primary": "#1f6feb",   # синий — главный
    "green": "#1a7f37",     # доход / успех
    "red": "#cf222e",       # расход / потери
    "orange": "#d97706",    # внимание
    "purple": "#8250df",    # дополнительный
}

st.markdown(
    f"""
    <style>
    .stApp {{
        background: {PALETTE['bg']};
    }}
    /* Сжимаем боковые отступы у main, чтобы убрать «море белого» */
    .main .block-container,
    section.main > div > div > div.block-container,
    [data-testid="stMainBlockContainer"] {{
        padding-top: 1.1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.6rem !important;
        padding-right: 1.6rem !important;
        max-width: none !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
    }}
    /* Сужаем sidebar чуть для большего useful space */
    [data-testid="stSidebar"][aria-expanded="true"] {{
        min-width: 260px !important; max-width: 280px !important;
    }}
    [data-testid="stSidebar"] .block-container {{
        padding-top: 1.1rem !important; padding-left: 1rem !important;
        padding-right: 1rem !important;
    }}

    /* Заголовок */
    h1 {{
        font-weight: 700; letter-spacing: -0.4px; color: {PALETTE['text']};
    }}
    .ufo-hero-text {{
        padding: 0.2rem 0 0 0;
    }}
    .ufo-hero-text h1 {{
        margin: 0; font-size: 1.65rem; color: {PALETTE['text']}; letter-spacing: -0.4px;
    }}
    .ufo-hero-text .ufo-sub {{
        color: {PALETTE['muted']}; font-size: 0.82rem; margin-top: 0.25rem;
        letter-spacing: 0.15px;
    }}
    .ufo-hero-range {{
        color: {PALETTE['muted']}; font-size: 0.78rem;
        padding: 0.1rem 0 0.95rem 0;
        margin-bottom: 1.1rem;
        border-bottom: 1px solid {PALETTE['border']};
    }}

    /* KPI плитки — плотнее */
    .kpi-card {{
        background: #ffffff;
        border: 1px solid {PALETTE['border']};
        border-radius: 10px;
        padding: 0.85rem 1rem;
        height: 100%;
        transition: border-color 0.15s ease;
    }}
    .kpi-card:hover {{ border-color: #8c959f; }}
    .kpi-card .kpi-label {{
        color: {PALETTE['muted']}; font-size: 0.7rem; text-transform: uppercase;
        letter-spacing: 0.4px; margin-bottom: 0.35rem; font-weight: 600;
    }}
    .kpi-card .kpi-value {{
        color: {PALETTE['text']}; font-size: 1.55rem; font-weight: 700; line-height: 1.1;
    }}
    .kpi-card .kpi-delta {{
        margin-top: 0.35rem; font-size: 0.75rem; color: {PALETTE['muted']};
    }}
    .kpi-card.primary .kpi-value {{ color: {PALETTE['primary']}; }}
    .kpi-card.green   .kpi-value {{ color: {PALETTE['green']}; }}
    .kpi-card.red     .kpi-value {{ color: {PALETTE['red']}; }}
    .kpi-card.orange  .kpi-value {{ color: {PALETTE['orange']}; }}
    .kpi-delta.up   {{ color: {PALETTE['green']}; font-weight: 600; }}
    .kpi-delta.down {{ color: {PALETTE['red']}; font-weight: 600; }}
    .kpi-delta.neutral {{ color: {PALETTE['muted']}; }}

    /* Hero KPI — крупная плитка главной метрики */
    .kpi-hero {{
        background: linear-gradient(135deg, #f0f7ff 0%, #ffffff 70%);
        border: 1px solid #c9d6ec;
        border-radius: 12px;
        padding: 1.4rem 1.6rem;
        margin-bottom: 0.7rem;
        display: flex; flex-wrap: wrap; align-items: center; gap: 1.2rem;
    }}
    .kpi-hero.red  {{ background: linear-gradient(135deg, #fff5f5 0%, #ffffff 70%); border-color: #f4c7c7; }}
    .kpi-hero.green {{ background: linear-gradient(135deg, #f0fbf3 0%, #ffffff 70%); border-color: #b9e3c1; }}
    .kpi-hero-main {{ flex: 1 1 260px; min-width: 0; }}
    .kpi-hero-label {{
        color: {PALETTE['muted']}; font-size: 0.78rem; text-transform: uppercase;
        letter-spacing: 0.6px; font-weight: 700; margin-bottom: 0.35rem;
    }}
    .kpi-hero-value {{
        color: {PALETTE['text']}; font-size: 2.7rem; font-weight: 800;
        line-height: 1; letter-spacing: -1px;
    }}
    .kpi-hero.green .kpi-hero-value {{ color: {PALETTE['green']}; }}
    .kpi-hero.red   .kpi-hero-value {{ color: {PALETTE['red']}; }}
    .kpi-hero-sub {{
        color: {PALETTE['muted']}; font-size: 0.86rem; margin-top: 0.55rem; line-height: 1.5;
    }}
    .kpi-hero-delta {{
        display: inline-block; margin-left: 0.7rem; padding: 0.18rem 0.55rem;
        border-radius: 6px; font-size: 0.78rem; font-weight: 600;
        vertical-align: middle;
    }}
    .kpi-hero-delta.up   {{ background: #dcfce7; color: {PALETTE['green']}; }}
    .kpi-hero-delta.down {{ background: #fee2e2; color: {PALETTE['red']}; }}
    .kpi-hero-delta.neutral {{ background: #f1f5f9; color: {PALETTE['muted']}; }}
    .kpi-hero-breakdown {{
        flex: 1 1 360px; display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.6rem;
    }}
    .kpi-hero-bd-item {{
        background: rgba(255,255,255,0.7); border: 1px solid {PALETTE['border']};
        border-radius: 8px; padding: 0.55rem 0.75rem;
    }}
    .kpi-hero-bd-label {{
        color: {PALETTE['muted']}; font-size: 0.68rem; text-transform: uppercase;
        letter-spacing: 0.4px; font-weight: 600; margin-bottom: 0.2rem;
    }}
    .kpi-hero-bd-value {{ font-weight: 700; color: {PALETTE['text']}; font-size: 0.95rem; }}
    @media (max-width: 780px) {{
        .kpi-hero-value {{ font-size: 2rem; }}
        .kpi-hero-breakdown {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    }}

    /* Уменьшаем gap между колонками */
    [data-testid="stHorizontalBlock"] {{ gap: 0.7rem !important; }}

    /* Popover «Период» — стильное меню в духе Я.Метрики */
    .period-group-title {{
        color: {PALETTE['muted']}; font-size: 0.66rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.8px;
        margin: 0.7rem 0 0.35rem 0.15rem;
        display: block;
    }}

    /* Тело popover-меню (живёт в портале, селектор прямой) */
    [data-testid="stPopoverBody"] {{
        padding: 0.95rem 0.85rem 0.85rem !important; min-width: 280px;
        background: #ffffff !important;
        box-shadow: 0 12px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06) !important;
        border: 1px solid {PALETTE['border']} !important;
        border-radius: 10px !important;
        max-height: 78vh !important; overflow-y: auto !important;
    }}
    /* Сжимаем вертикальный gap между кнопками */
    [data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] {{ gap: 0 !important; }}
    [data-testid="stPopoverBody"] [data-testid="stElementContainer"] {{ margin-bottom: 0 !important; }}
    /* После markdown-заголовка группы нужен «воздух» перед следующим виджетом
       (особенно перед stColumns с двумя date_input — иначе их labels наезжают). */
    [data-testid="stPopoverBody"] [data-testid="stElementContainer"]:has(.period-group-title) {{
        margin-bottom: 0.3rem !important;
    }}
    /* Горизонтальный блок (st.columns) внутри popover — для двух date_input */
    [data-testid="stPopoverBody"] [data-testid="stHorizontalBlock"] {{
        margin-top: 0.3rem !important; gap: 0.5rem !important;
    }}
    /* Label у date_input — компактнее и без слипания с заголовком */
    [data-testid="stPopoverBody"] [data-testid="stWidgetLabel"] {{
        font-size: 0.78rem !important; margin-bottom: 0.2rem !important;
        color: {PALETTE['muted']} !important;
    }}

    /* Кнопки-пресеты — лево-выровненные, компактные */
    [data-testid="stPopoverBody"] [data-testid="stBaseButton-tertiary"],
    [data-testid="stPopoverBody"] [data-testid="stBaseButton-primary"] {{
        text-align: left !important; justify-content: flex-start !important;
        padding: 0.4rem 0.75rem !important; border-radius: 7px !important;
        font-weight: 500 !important; font-size: 0.93rem !important;
        border: 1px solid transparent !important; background: transparent !important;
        color: {PALETTE['text']} !important; box-shadow: none !important;
        min-height: 36px !important; height: auto !important;
        width: 100% !important;
        display: flex !important; align-items: center !important;
    }}
    /* Растягиваем внутренние обёртки и лево-выравниваем сам текст */
    [data-testid="stPopoverBody"] [data-testid^="stBaseButton-"] > div,
    [data-testid="stPopoverBody"] [data-testid^="stBaseButton-"] > div > span {{
        flex: 1 1 auto !important; text-align: left !important;
        display: block !important;
    }}
    [data-testid="stPopoverBody"] [data-testid^="stBaseButton-"] [data-testid="stMarkdownContainer"] {{
        text-align: left !important; width: 100% !important;
    }}
    [data-testid="stPopoverBody"] [data-testid^="stBaseButton-"] [data-testid="stMarkdownContainer"] p {{
        text-align: left !important; margin: 0 !important;
    }}
    [data-testid="stPopoverBody"] [data-testid="stBaseButton-tertiary"]:hover,
    [data-testid="stPopoverBody"] [data-testid="stBaseButton-primary"]:hover {{
        background: #f1f5f9 !important; border-color: transparent !important;
        color: {PALETTE['text']} !important;
    }}
    /* Активный пресет (primary тип) — мягкая серая подсветка */
    [data-testid="stPopoverBody"] [data-testid="stBaseButton-primary"] {{
        background: #eef2f6 !important; font-weight: 600 !important;
    }}
    /* Кнопка «Применить» в самом низу — выделена «фирменно» (тёмная) */
    [data-testid="stPopoverBody"] [data-testid="stElementContainer"]:last-of-type [data-testid="stBaseButton-primary"] {{
        background: {PALETTE['text']} !important; color: #fff !important;
        text-align: center !important; justify-content: center !important;
        font-weight: 600 !important; margin-top: 0.6rem !important;
        min-height: 40px !important;
    }}
    [data-testid="stPopoverBody"] [data-testid="stElementContainer"]:last-of-type [data-testid="stBaseButton-primary"]:hover {{
        background: #1a1f24 !important; color: #fff !important;
    }}

    /* Триггер popover — стильная белая кнопка справа в Hero */
    [data-testid="stPopoverButton"] {{
        background: #ffffff !important; border: 1px solid {PALETTE['border']} !important;
        color: {PALETTE['text']} !important; font-weight: 500 !important;
        padding: 0.5rem 0.95rem !important; border-radius: 8px !important;
        justify-content: space-between !important;
        min-height: 42px !important;
    }}
    [data-testid="stPopoverButton"]:hover {{
        border-color: #8c959f !important; background: #fafbfc !important;
    }}

    /* Плавающий триггер «Период анализа» — всегда виден в правом верхнем углу.
       Streamlit-header имеет z-index 999990, ставим триггер ПОД его уровень
       по вертикали (top: 3.2rem) и ВЫШЕ по z-index для модальных диалогов. */
    .st-key-period_picker {{
        position: fixed !important;
        top: 3.2rem !important;
        right: 1rem !important;
        z-index: 999991 !important;
        width: 220px !important;
        padding: 0 !important;
        background: transparent !important;
    }}
    /* Внутренний триггер popover внутри плавающего контейнера */
    .st-key-period_picker [data-testid="stPopoverButton"] {{
        background: rgba(255, 255, 255, 0.98) !important;
        -webkit-backdrop-filter: blur(10px) saturate(180%);
        backdrop-filter: blur(10px) saturate(180%);
        box-shadow: 0 4px 14px rgba(0,0,0,0.10) !important;
        font-weight: 600 !important;
    }}
    .st-key-period_picker [data-testid="stPopoverButton"]:hover {{
        background: #ffffff !important;
        box-shadow: 0 6px 18px rgba(0,0,0,0.13) !important;
    }}
    /* Popover-меню (живёт в портале) — поверх всего, включая header */
    [data-testid="stPopoverBody"] {{ z-index: 999992 !important; }}

    /* Лента «Покрытие данными» — flex, все ячейки равной ширины, без одиноких */
    .coverage-row {{
        display: flex; flex-wrap: wrap; gap: 0.35rem;
    }}
    .coverage-cell {{
        flex: 1 1 0; min-width: 70px;
        border-radius: 8px; padding: 0.5rem 0.3rem; text-align: center;
    }}
    .coverage-cell-icon {{ font-size: 1rem; line-height: 1; margin-bottom: 0.25rem; }}
    .coverage-cell-label {{
        font-size: 0.7rem; color: {PALETTE['text']}; font-weight: 600;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    @media (max-width: 640px) {{
        .coverage-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.3rem; }}
        .coverage-cell {{ padding: 0.45rem 0.25rem; min-width: 0; }}
        .coverage-cell-label {{ font-size: 0.65rem; }}
    }}
    @media (max-width: 340px) {{
        .coverage-row {{ grid-template-columns: repeat(2, 1fr); }}
    }}

    /* Авто-инсайты */
    .insight-row {{ display: flex; gap: 0.6rem; flex-wrap: wrap; margin: 0.4rem 0 1rem; }}
    .insight-pill {{
        flex: 1 1 280px; min-width: 240px; padding: 0.7rem 0.95rem;
        border-radius: 9px; border: 1px solid; font-size: 0.85rem; line-height: 1.45;
        display: flex; gap: 0.55rem; align-items: flex-start;
    }}
    .insight-pill .ico {{ font-size: 1rem; flex-shrink: 0; line-height: 1.35; }}
    .insight-pill.good {{ background: #f0fbf3; border-color: #b9e3c1; color: {PALETTE['text']}; }}
    .insight-pill.warn {{ background: #fef9c3; border-color: #f0c84a; color: {PALETTE['text']}; }}
    .insight-pill.info {{ background: #f0f7ff; border-color: #c9d6ec; color: {PALETTE['text']}; }}
    .insight-pill .label {{
        text-transform: uppercase; letter-spacing: 0.4px; font-size: 0.66rem;
        font-weight: 700; color: {PALETTE['muted']}; margin-bottom: 0.18rem; display: block;
    }}

    /* Секции */
    .section-title {{
        margin: 1.2rem 0 0.55rem 0; font-size: 0.82rem; font-weight: 700;
        color: {PALETTE['muted']}; text-transform: uppercase; letter-spacing: 0.5px;
    }}

    /* Sidebar */
    [data-testid="stSidebar"] {{
        background: {PALETTE['panel']}; border-right: 1px solid {PALETTE['border']};
    }}
    [data-testid="stSidebar"] h1 {{ font-size: 1.15rem; }}
    [data-testid="stSidebar"] h3 {{ font-size: 1.05rem; margin: 0; }}

    /* Дефолтные st.metric */
    [data-testid="stMetricValue"] {{ font-size: 1.4rem; font-weight: 700; }}
    [data-testid="stMetricLabel"] {{
        font-size: 0.7rem; color: {PALETTE['muted']};
        text-transform: uppercase; letter-spacing: 0.4px; font-weight: 600;
    }}

    .streamlit-expanderHeader {{ font-weight: 600; }}

    /* Плотнее отступы alerts */
    [data-testid="stAlert"] {{ padding: 0.7rem 0.95rem !important; }}

    /* KPI tooltip — CSS-only, без JS */
    .kpi-tip {{
        display: inline-block; margin-left: 0.35rem; cursor: help;
        color: {PALETTE['muted']}; font-size: 0.78rem; font-weight: 400;
        position: relative; line-height: 1; vertical-align: middle;
    }}
    .kpi-tip:hover::after {{
        content: attr(data-tip);
        position: absolute; bottom: calc(100% + 6px); left: 50%;
        transform: translateX(-50%);
        background: {PALETTE['text']}; color: #fff;
        padding: 0.5rem 0.7rem; border-radius: 6px; font-size: 0.72rem;
        line-height: 1.4; font-weight: 400;
        width: max-content; max-width: 260px;
        white-space: normal; text-transform: none; letter-spacing: 0;
        z-index: 1000; pointer-events: none;
        box-shadow: 0 6px 20px rgba(0,0,0,0.18);
    }}
    .kpi-tip:hover::before {{
        content: ""; position: absolute; bottom: calc(100% + 1px); left: 50%;
        transform: translateX(-50%);
        border: 5px solid transparent; border-top-color: {PALETTE['text']};
        z-index: 1000; pointer-events: none;
    }}

    /* Footer */
    .ufo-footer {{
        color: {PALETTE['muted']}; font-size: 0.78rem; text-align: center;
        margin-top: 1.5rem; padding-top: 0.85rem;
        border-top: 1px solid {PALETTE['border']};
    }}

    /* ─── Адаптивность: tablet / phone ─────────────────────────── */
    /* Tablet (< 1024px): чуть компактнее */
    @media (max-width: 1024px) {{
        .kpi-hero-value {{ font-size: 2.3rem !important; }}
        .ufo-hero-text h1 {{ font-size: 1.5rem !important; }}
        .st-key-period_picker {{
            width: 200px !important; right: 0.8rem !important; top: 3rem !important;
        }}
    }}

    /* Large phone / portrait tablet (< 900px): KPI в 2 столбца */
    @media (max-width: 900px) {{
        [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; }}
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
            flex: 1 1 calc(50% - 0.4rem) !important;
            min-width: calc(50% - 0.4rem) !important;
        }}
        .ufo-hero-text h1 {{ font-size: 1.35rem !important; }}
        .ufo-hero-text .ufo-sub {{ font-size: 0.78rem; }}
        .kpi-card {{ padding: 0.75rem 0.85rem; }}
        .kpi-card .kpi-value {{ font-size: 1.35rem !important; }}
        .kpi-hero {{ padding: 1.1rem 1.2rem; gap: 0.8rem; }}
        .kpi-hero-value {{ font-size: 2rem !important; }}
        .kpi-hero-breakdown {{
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            gap: 0.4rem !important;
        }}
        .kpi-hero-bd-item {{ padding: 0.45rem 0.55rem; }}
        .kpi-hero-bd-value {{ font-size: 0.85rem !important; }}
        /* Авто-инсайты — на планшете 2 в ряд автоматически (min-width 240px) */
    }}

    /* Phone (< 640px): полностью одна колонка, триггер периода — в потоке */
    @media (max-width: 640px) {{
        .main .block-container,
        section.main > div > div > div.block-container,
        [data-testid="stMainBlockContainer"] {{
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            padding-top: 0.8rem !important;
        }}

        /* Плавающий триггер периода СНИМАЕМ с position:fixed —
           он встаёт под Hero в нормальном потоке и не перекрывает заголовок. */
        .st-key-period_picker {{
            position: static !important;
            top: auto !important; right: auto !important;
            width: 100% !important;
            margin: 0.2rem 0 0.8rem !important;
            z-index: auto !important;
        }}
        .st-key-period_picker [data-testid="stPopoverButton"] {{
            box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
            min-height: 44px !important;
        }}
        /* Popover-меню — на всю ширину viewport минус малый отступ */
        [data-testid="stPopoverBody"] {{
            min-width: calc(100vw - 1.6rem) !important;
            max-width: calc(100vw - 1.6rem) !important;
        }}

        /* Hero KPI — уменьшаем главную цифру */
        .kpi-hero {{ padding: 1rem 1.1rem; }}
        .kpi-hero-label {{ font-size: 0.7rem; }}
        .kpi-hero-value {{ font-size: 1.7rem !important; letter-spacing: -0.5px; }}
        .kpi-hero-sub {{ font-size: 0.8rem; }}
        .kpi-hero-breakdown {{
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            gap: 0.35rem !important;
        }}
        .kpi-hero-bd-label {{ font-size: 0.62rem !important; }}
        .kpi-hero-bd-value {{ font-size: 0.78rem !important; }}

        /* KPI карточки — оставляем 2 в ряд для компактности */
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
            flex: 1 1 calc(50% - 0.4rem) !important;
            min-width: calc(50% - 0.4rem) !important;
        }}

        /* Section title — больше воздуха */
        .section-title {{ margin: 1.3rem 0 0.5rem; font-size: 0.74rem; }}

        /* Авто-инсайты — 1 столбец, более компактные */
        .insight-pill {{
            flex: 1 1 100% !important; min-width: 0 !important;
            font-size: 0.82rem; padding: 0.65rem 0.85rem;
        }}

        /* Sparkline в KPI плитке — уменьшаем чтобы не занимал место */
        .kpi-card svg {{ width: 100% !important; height: 22px !important; }}

        /* Лента покрытия данных — текст в ячейках компактнее */
        .ufo-hero-range {{ font-size: 0.72rem; padding-bottom: 0.7rem; }}
    }}

    /* Small phone (< 420px): 1 столбец для ВСЕГО, минимум отступов */
    @media (max-width: 420px) {{
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }}
        .kpi-hero-value {{ font-size: 1.55rem !important; }}
        .kpi-hero-breakdown {{
            grid-template-columns: 1fr 1fr !important;
        }}
        .ufo-hero-text h1 {{ font-size: 1.25rem !important; }}
        .main .block-container,
        [data-testid="stMainBlockContainer"] {{
            padding-left: 0.7rem !important;
            padding-right: 0.7rem !important;
        }}
    }}

    /* Очень широкие мониторы (>= 1600px): ограничиваем макс. ширину
       чтобы линии текста не растягивались бесконечно */
    @media (min-width: 1800px) {{
        .main .block-container,
        [data-testid="stMainBlockContainer"] {{
            max-width: 1700px !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
    }}

    /* Печать в PDF (Cmd+P → Save as PDF) */
    @media print {{
        [data-testid="stSidebar"], header, .stDeployButton,
        [data-testid="stToolbar"], .stApp > header {{ display: none !important; }}
        .main .block-container,
        section.main > div > div > div.block-container,
        [data-testid="stMainBlockContainer"] {{
            padding: 0 !important; max-width: none !important;
        }}
        .kpi-card {{ break-inside: avoid; }}
        .section-title {{ break-after: avoid; }}
        .ufo-footer {{ display: none; }}
        body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

PLOTLY_LAYOUT = dict(
    template="plotly_white",
    paper_bgcolor="#ffffff",
    plot_bgcolor="#ffffff",
    font=dict(color=PALETTE["text"], family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", size=12),
    margin=dict(t=40, l=10, r=10, b=10),
    xaxis=dict(gridcolor="#eaeef2", zerolinecolor="#d0d7de", linecolor="#d0d7de"),
    yaxis=dict(gridcolor="#eaeef2", zerolinecolor="#d0d7de", linecolor="#d0d7de"),
)


def fmt_rub(v, suffix=" ₽"):
    """Деньги: до миллиона — точные цифры с пробелами, от миллиона — млн."""
    if v is None or pd.isna(v):
        return "—"
    av = abs(v)
    if av >= 1_000_000:
        return f"{v/1_000_000:.2f} млн{suffix}"
    return f"{v:,.0f}{suffix}".replace(",", " ")


def fmt_num(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{int(v):,}".replace(",", " ")


def plural_ru(n, one, few, many):
    """Русская плюрализация: 1 файл / 2 файла / 5 файлов."""
    n = abs(int(n))
    if n % 100 in (11, 12, 13, 14):
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


_RU_MONTHS_SHORT = ["", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
_RU_MONTHS_FULL = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
_RU_MONTHS_LOW = ["", "январь", "февраль", "март", "апрель", "май", "июнь",
                  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def fmt_month_ru(dt, kind="short_year"):
    """Форматирует месяц на русском. kind:
    - 'short_year' → 'Авг 2025'
    - 'full_year'  → 'Август 2025'
    - 'low_year'   → 'август 2025'"""
    if pd.isna(dt):
        return "—"
    dt = pd.Timestamp(dt)
    if kind == "full_year":
        return f"{_RU_MONTHS_FULL[dt.month]} {dt.year}"
    if kind == "low_year":
        return f"{_RU_MONTHS_LOW[dt.month]} {dt.year}"
    return f"{_RU_MONTHS_SHORT[dt.month]} {dt.year}"


def make_sparkline_svg(values, color="#1f6feb", width=88, height=28, fill=True):
    """Возвращает inline SVG sparkline для KPI плитки. Принимает список чисел."""
    if not values or len(values) < 2:
        return ""
    vals = [float(v) if v is not None and not pd.isna(v) else 0 for v in values]
    if all(v == 0 for v in vals):
        return ""
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) if mx > mn else max(abs(mx), 1)
    points = []
    pad = 3
    for i, v in enumerate(vals):
        x = pad + i / (len(vals) - 1) * (width - 2 * pad)
        y = height - pad - ((v - mn) / rng) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    line = " ".join(points)
    fill_poly = ""
    if fill:
        fill_points = f"{pad},{height - pad} {line} {width - pad},{height - pad}"
        fill_poly = f'<polygon points="{fill_points}" fill="{color}" fill-opacity="0.12"/>'
    # точка последнего значения
    last_x = pad + (len(vals) - 1) / (len(vals) - 1) * (width - 2 * pad)
    last_y = height - pad - ((vals[-1] - mn) / rng) * (height - 2 * pad)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="display:block; margin-top:0.35rem;">'
        f'{fill_poly}'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.2" fill="{color}"/>'
        f'</svg>'
    )


def kpi_card(label: str, value: str, delta: str = "", kind: str = "",
             delta_kind: str = "neutral", tooltip: str = "",
             spark_values=None, spark_color: str | None = None):
    """Карточка KPI с фиксированным стилем. tooltip — подсказка ⓘ.
    spark_values — список чисел для мини-графика тренда внутри плитки."""
    klass = f"kpi-card {kind}".strip()
    delta_html = f'<div class="kpi-delta {delta_kind}">{delta}</div>' if delta else ""
    tip_html = ""
    if tooltip:
        tip_safe = tooltip.replace('"', '&quot;').replace("\n", " ")
        tip_html = f'<span class="kpi-tip" data-tip="{tip_safe}">ⓘ</span>'
    spark_html = ""
    if spark_values and len(spark_values) >= 2:
        c = spark_color or {
            "green": PALETTE["green"], "red": PALETTE["red"],
            "primary": PALETTE["primary"], "orange": PALETTE["orange"],
        }.get(kind, PALETTE["muted"])
        spark_html = make_sparkline_svg(spark_values, color=c)
    return f"""
    <div class="{klass}">
      <div class="kpi-label">{label}{tip_html}</div>
      <div class="kpi-value">{value}</div>
      {delta_html}
      {spark_html}
    </div>
    """


def _generate_insights(orders_df, ads_df, ck, ms, ch_sum, prev_kpi=None, prev_label=None):
    """Возвращает list[dict] с автоматическими наблюдениями по данным.
    Каждый элемент: {kind: good|warn|info, ico, label, text}. Максимум 4."""
    items = []

    # 1. Overlap ROMI — если расход сильно превышает доход из-за неполных CSV
    overlap_kpi = M.comparable_kpi(orders_df, ads_df)
    overlap_period_ = M.overlap_period(orders_df, ads_df)
    if overlap_kpi is not None and overlap_period_ is not None:
        ofrom, oto = overlap_period_
        if overlap_kpi.spend > 0 and ck.spend > overlap_kpi.spend * 1.4:
            o_romi = (overlap_kpi.revenue - overlap_kpi.spend) / overlap_kpi.spend * 100
            o_kind = "good" if o_romi >= 0 else "warn"
            o_ico = "✅" if o_romi >= 0 else "📅"
            items.append({
                "kind": o_kind, "ico": o_ico, "label": "Сопоставимый период",
                "text": (
                    f"За <b>{fmt_month_ru(ofrom, 'low_year')} – {fmt_month_ru(oto, 'low_year')}</b> "
                    f"(где есть и CSV, и Директ) реальный ROMI = <b>{o_romi:+.1f}%</b>, "
                    f"доход {fmt_rub(overlap_kpi.revenue)} vs расход {fmt_rub(overlap_kpi.spend)}."
                ),
            })

    # 2. CAC trend (последний vs первый месяц)
    if not ms.empty and len(ms) >= 3:
        cac_series = ms[ms["cac"].notna() & (ms["cac"] > 0)]
        if len(cac_series) >= 2:
            first_cac = float(cac_series.iloc[0]["cac"])
            last_cac = float(cac_series.iloc[-1]["cac"])
            first_m = cac_series.iloc[0]["month"]
            last_m = cac_series.iloc[-1]["month"]
            if first_cac > 0 and last_cac > 0:
                ratio = first_cac / last_cac
                if ratio >= 2:
                    items.append({
                        "kind": "good", "ico": "📉", "label": "CAC снизился",
                        "text": (
                            f"Стоимость нового клиента упала в <b>{ratio:.1f}×</b>: с "
                            f"<b>{fmt_rub(first_cac)}</b> ({fmt_month_ru(first_m, 'low_year')}) до "
                            f"<b>{fmt_rub(last_cac)}</b> ({fmt_month_ru(last_m, 'low_year')})."
                        ),
                    })
                elif last_cac / first_cac >= 1.3:
                    growth = (last_cac - first_cac) / first_cac * 100
                    items.append({
                        "kind": "warn", "ico": "📈", "label": "CAC вырос",
                        "text": (
                            f"Стоимость нового клиента выросла на <b>{growth:+.0f}%</b>: "
                            f"с <b>{fmt_rub(first_cac)}</b> ({fmt_month_ru(first_m, 'low_year')}) "
                            f"до <b>{fmt_rub(last_cac)}</b> ({fmt_month_ru(last_m, 'low_year')})."
                        ),
                    })

    # 3. Лучший месяц по доходу
    if not ms.empty and len(ms) >= 2:
        best_idx = ms["revenue"].idxmax()
        best_row = ms.loc[best_idx]
        if best_row["revenue"] > 0:
            items.append({
                "kind": "info", "ico": "🏆", "label": "Лучший месяц",
                "text": (
                    f"Максимум дохода — <b>{fmt_month_ru(best_row['month'], 'full_year')}</b>: "
                    f"<b>{fmt_rub(best_row['revenue'])}</b> от "
                    f"<b>{int(best_row['new_clients'])}</b> новых клиентов."
                ),
            })

    # 4. Клиенты под риском
    if ch_sum and ch_sum.get("at_risk", 0) >= 3:
        n = ch_sum["at_risk"]
        items.append({
            "kind": "warn", "ico": "🔔", "label": "Под риском оттока",
            "text": (
                f"<b>{n}</b> {plural_ru(n, 'клиент', 'клиента', 'клиентов')} не платили 31–90 дней. "
                f"Совокупный LTV — <b>{fmt_rub(ch_sum.get('at_risk_revenue', 0))}</b>. "
                f"Самое время вернуть скидкой или звонком."
            ),
        })

    return items[:4]


def _render_insights(items):
    if not items:
        return
    html_items = []
    for it in items:
        html_items.append(
            f'<div class="insight-pill {it["kind"]}">'
            f'<span class="ico">{it["ico"]}</span>'
            f'<div><span class="label">{it["label"]}</span>{it["text"]}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div class="insight-row">{"".join(html_items)}</div>',
        unsafe_allow_html=True,
    )


# ============================================================
#                       Persistent storage (HF Dataset)
# ============================================================

@st.cache_resource(show_spinner="Синхронизирую данные из облака…")
def _initial_storage_sync():
    if not storage.is_enabled():
        return {"enabled": False}
    storage.ensure_dataset_exists()
    info = storage.sync_down()
    # Автоматически тянем кэш API за последние 60 дней (обновляется GitHub Action ежедневно)
    api_df = storage.sync_api_cache_down()
    if api_df is not None and not api_df.empty:
        info["api_cache_rows"] = len(api_df)
        info["api_cache_last_month"] = str(api_df["month"].max())[:10] if "month" in api_df.columns else None
    # Кэш «качества рекламы» (CTR/CPC/конверсии) — 3 json'a. Без них на странице
    # /quality каждый раз после деплоя запускается долгая автозагрузка (3 года).
    q_info = storage.sync_quality_cache_down()
    info["quality_cache_downloaded"] = q_info.get("downloaded", 0)
    return info


_progress("Подключаюсь к облаку…", 15)
_sync_info = _initial_storage_sync()
_progress("Парсю выгрузки заказов…", 30)


@st.cache_data(ttl=600, show_spinner=False)
def _load_api_cache_df():
    """Подтягиваем кэшированные API-данные с диска (заполненные daily action или sync_api_cache_down)."""
    cache_path = Path(__file__).resolve().parent.parent / "data" / "api_cache" / "yd_rolling.json"
    if not cache_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_json(cache_path)
        if not df.empty and "month" in df.columns:
            df["month"] = pd.to_datetime(df["month"])
        return df
    except Exception:
        return pd.DataFrame()


# Расширенная аналитика качества (кампании / ключевики / объявления) —
# вынесена на отдельную страницу pages/1_🎯_Качество_рекламы.py.
# Общие helpers (включая save/load_quality_cache) — в src/_shared.py.


# ============================================================
#                       Sidebar
# ============================================================

with st.sidebar:
    st.markdown("### UFO Hosting")
    st.caption("Дашборд окупаемости · LTV · CAC")
    st.divider()

    st.markdown("**Загрузить выгрузку заказов**")
    uploaded_orders = st.file_uploader(
        label="CSV «Содержимое заказов» из админки UFO Hosting",
        type=["csv"],
        accept_multiple_files=True,
        key="orders_upload",
        label_visibility="visible",
        help="Можно загрузить несколько файлов — дубликаты по ID покупки убираются.",
    )
    # XLSX-загрузка для клиента не нужна: расходы тянутся только из Я.Директ API
    uploaded_ads = None

    # Сохраняем загруженный CSV в облако
    if storage.is_enabled():
        for f in uploaded_orders or []:
            key = f"_uploaded_{f.name}_{f.size}"
            if key not in st.session_state:
                if storage.upload_orders_csv(f.name, f.getvalue()):
                    st.session_state[key] = True
                    st.toast(f"Файл «{f.name}» сохранён в облако", icon="✅")

    # Компактный статус облака
    n_o_disk = len(list(ORDERS_DIR.glob('*.csv')))
    n_a_disk = len(list(ADS_DIR.glob('*.xlsx')))
    if storage.is_enabled():
        if _sync_info and _sync_info.get("error"):
            st.error(f"Ошибка облака: {_sync_info['error']}", icon="⚠️")
        else:
            files_word = plural_ru(n_o_disk, "файл", "файла", "файлов")
            st.caption(f"💾 Облако · {n_o_disk} {files_word} синхронизировано")
        if st.button("Обновить из облака", use_container_width=True, key="resync_btn", type="secondary"):
            st.cache_resource.clear()
            st.cache_data.clear()
            st.rerun()
    else:
        files_word = plural_ru(n_o_disk, "файл", "файла", "файлов")
        st.caption(f"Локально: {n_o_disk} {files_word} с заказами")

    st.divider()

    # Я.Директ API
    _yd_creds_global = yd_creds()
    if _yd_creds_global:
        with st.expander("Яндекс.Директ API · синхронизация", expanded=False):
            sync_from = st.date_input(
                "С даты",
                value=pd.Timestamp.today() - pd.Timedelta(days=90),
                key="yd_sync_from",
                format="DD.MM.YYYY",
            )
            sync_to = st.date_input(
                "По дату",
                value=pd.Timestamp.today(),
                key="yd_sync_to",
                format="DD.MM.YYYY",
            )

            @st.cache_data(ttl=86400, show_spinner=False)
            def _cached_yd_report(date_from: str, date_to: str, token_hash: str):
                from yandex_direct import (
                    fetch_campaign_report, to_ads_dataframe, DirectCredentials,
                )
                creds = DirectCredentials(
                    token=_yd_creds_global.token,
                    client_login=_yd_creds_global.client_login,
                )
                raw = fetch_campaign_report(creds, date_from=date_from, date_to=date_to)
                return to_ads_dataframe(raw)

            col_btn1, col_btn2 = st.columns(2)
            do_sync = col_btn1.button("Подтянуть", use_container_width=True, key="yd_sync_btn", type="primary")
            force = col_btn2.button("Обновить", use_container_width=True, key="yd_force_btn",
                                    help="Принудительно сбросить кэш и запросить заново")
            if force:
                _cached_yd_report.clear()
                do_sync = True
            if do_sync:
                try:
                    token_hash = hash(_yd_creds_global.token) & 0xFFFF  # короткий хэш, чтобы не светить токен в кэш-ключе
                    with st.spinner("Тяну отчёт из Я.Директ (до минуты)…"):
                        api_ads = _cached_yd_report(str(sync_from), str(sync_to), str(token_hash))
                    if api_ads.empty:
                        st.warning("API вернул пустой отчёт.")
                    else:
                        st.session_state["yd_api_ads"] = api_ads
                        st.success(
                            f"Подтянуто {len(api_ads)} строк, "
                            f"{api_ads['spend_rub'].sum():,.0f} ₽".replace(",", " ")
                        )
                        st.rerun()
                except Exception as e:
                    st.error(str(e))
            if "yd_api_ads" in st.session_state and not st.session_state["yd_api_ads"].empty:
                n = len(st.session_state["yd_api_ads"])
                st.caption(f"В сессии: {n} строк (кэш на 24 часа)")

        st.caption(
            "💡 Глубокая аналитика по кампаниям, ключевикам и объявлениям — "
            "на отдельной странице **«🎯 Качество рекламы»** (см. навигацию выше)."
        )

    st.divider()

    # Период и фильтры будут после загрузки данных
    placeholder_filters = st.container()


# ============================================================
#                       Data loading
# ============================================================

@st.cache_data(show_spinner="Парсим данные…", ttl=300)
def load_all(orders_signature: tuple, ads_signature: tuple,
             uploaded_orders_data: tuple, uploaded_ads_data: tuple):
    """Cache-key включает имена и размеры загруженных файлов, чтобы кэш инвалидировался."""
    import io
    extra_orders = [io.BytesIO(d) for n, d in uploaded_orders_data] if uploaded_orders_data else None
    for f, (name, _) in zip(extra_orders or [], uploaded_orders_data or []):
        f.name = name  # сохраним имя для __source__
    extra_ads = [io.BytesIO(d) for n, d in uploaded_ads_data] if uploaded_ads_data else None
    for f, (name, _) in zip(extra_ads or [], uploaded_ads_data or []):
        f.name = name
    o = load_orders(extra_files=extra_orders)
    a = load_ads(extra_files=extra_ads)
    return o, a


# ─── Кэшированные обёртки тяжёлых метрик ──────────────────────
# Streamlit умеет хэшировать pd.DataFrame по содержимому — если
# исходные orders/ads не меняются, переключения периода/фильтров
# не пересчитывают эти функции заново.

@st.cache_data(ttl=600, show_spinner=False)
def _cached_compute_kpi(orders_df, ads_df):
    return M.compute_kpi(orders_df, ads_df)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_monthly_summary(orders_df, ads_df):
    return M.monthly_summary(orders_df, ads_df)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_churn_summary(orders_df):
    return M.churn_summary(orders_df)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_product_mix(orders_df, by):
    return M.product_mix(orders_df, by=by)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_pareto_summary(orders_df):
    return M.pareto_summary(orders_df)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_funnel(orders_df):
    return M.funnel(orders_df)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_mrr_by_month(orders_df):
    return M.mrr_by_month(orders_df)


def _file_sig(files):
    if not files:
        return tuple()
    return tuple(sorted((f.name, getattr(f, "size", 0)) for f in files))


orders_disk_sig = tuple(sorted((p.name, p.stat().st_size) for p in ORDERS_DIR.glob("*.csv")))
ads_disk_sig = tuple(sorted((p.name, p.stat().st_size) for p in ADS_DIR.glob("*.xlsx")))

uploaded_orders_data = tuple((f.name, f.getvalue()) for f in (uploaded_orders or []))
uploaded_ads_data = tuple((f.name, f.getvalue()) for f in (uploaded_ads or []))

orders_all, ads_all = load_all(
    orders_disk_sig, ads_disk_sig,
    uploaded_orders_data, uploaded_ads_data,
)
_progress("Считаю когорты, LTV, churn…", 65)

# Welcome-state если нет данных
HAS_DATA = not (orders_all.empty and ads_all.empty)

if not HAS_DATA:
    st.title("🛰️ UFO Hosting · Дашборд окупаемости рекламы")
    st.markdown(
        "<div style='color: #9ba3d4; font-size: 1rem; margin-top: -0.5rem; margin-bottom: 1.5rem;'>"
        "Яндекс.Директ · LTV · CAC · Retention</div>",
        unsafe_allow_html=True,
    )
    st.info(
        "👈 **Загрузите выгрузки в сайдбаре слева, чтобы увидеть отчёт.**\n\n"
        "**Что загружать:**\n\n"
        "• **CSV** — выгрузки «Содержимое заказов» из админки UFO Hosting (можно несколько за разные периоды)\n\n"
        "• **XLSX** — отчёты по рекламным кампаниям Яндекс.Директ (помесячно)\n\n"
        "Дашборд сам разберёт и склеит данные, дедуплицирует пересекающиеся периоды."
    )
    with placeholder_filters:
        st.caption("Фильтры станут доступны после загрузки данных.")
    _progress_done()  # убираем прогресс на welcome-screen
    st.stop()


# ============================================================
#                       Sidebar: фильтры (после загрузки)
# ============================================================

# Вычисляем границы доступных данных
if not orders_all.empty:
    pay_min = orders_all["payment_date"].min().date()
    pay_max = orders_all["payment_date"].max().date()
else:
    pay_min = ads_all["month"].min().date()
    pay_max = ads_all["month"].max().date()
if not ads_all.empty:
    ad_min = ads_all["month"].min().date()
    ad_max = ads_all["month"].max().date()
else:
    ad_min, ad_max = pay_min, pay_max
# Учитываем даты API данных в overall_max (из session или из daily cache)
_api_session = st.session_state.get("yd_api_ads")
_api_cache_df = _load_api_cache_df()
_api_for_bounds = _api_session if (_api_session is not None and not _api_session.empty) else _api_cache_df
if _api_for_bounds is not None and not _api_for_bounds.empty and "month" in _api_for_bounds.columns:
    api_max = _api_for_bounds["month"].max().date()
    if api_max > ad_max:
        ad_max = api_max
overall_min = min(pay_min, ad_min)
overall_max = max(pay_max, ad_max)

# Пресеты периода — как у Я.Директ
PERIOD_PRESETS = [
    "Сегодня",
    "Вчера",
    "Последние 7 дней",
    "Последние 14 дней",
    "Последние 30 дней",
    "Последние 90 дней",
    "Эта неделя",
    "Прошлая неделя",
    "Этот месяц",
    "Прошлый месяц",
    "Этот квартал",
    "Прошлый квартал",
    "Этот год",
    "За всё время",
    "Произвольный",
]

# Группировка пресетов для popover-выбора в стиле «Свой диапазон»
PERIOD_GROUPS = [
    ("СКОЛЬЗЯЩЕЕ ОКНО", [
        "Последние 7 дней", "Последние 14 дней",
        "Последние 30 дней", "Последние 90 дней",
    ]),
    ("КАЛЕНДАРЬ", [
        "Сегодня", "Вчера", "Эта неделя", "Прошлая неделя",
        "Этот месяц", "Прошлый месяц",
        "Этот квартал", "Прошлый квартал", "Этот год",
        "За всё время",
    ]),
]


def _compute_preset_range(name: str, data_max: pd.Timestamp, data_min: pd.Timestamp):
    today = pd.Timestamp(data_max).normalize()
    if name == "Сегодня":
        return (today, today)
    if name == "Вчера":
        y = today - pd.Timedelta(days=1)
        return (y, y)
    if name == "Последние 7 дней":
        return (today - pd.Timedelta(days=6), today)
    if name == "Последние 14 дней":
        return (today - pd.Timedelta(days=13), today)
    if name == "Последние 30 дней":
        return (today - pd.Timedelta(days=29), today)
    if name == "Последние 90 дней":
        return (today - pd.Timedelta(days=89), today)
    if name == "Эта неделя":
        # Понедельник = 0
        week_start = today - pd.Timedelta(days=today.weekday())
        return (week_start, today)
    if name == "Прошлая неделя":
        this_week_start = today - pd.Timedelta(days=today.weekday())
        last_week_end = this_week_start - pd.Timedelta(days=1)
        last_week_start = last_week_end - pd.Timedelta(days=6)
        return (last_week_start, last_week_end)
    if name == "Этот месяц":
        return (today.replace(day=1), today)
    if name == "Прошлый месяц":
        first = today.replace(day=1)
        last_prev = first - pd.Timedelta(days=1)
        return (last_prev.replace(day=1), last_prev)
    if name == "Этот квартал":
        q = (today.month - 1) // 3
        return (pd.Timestamp(today.year, q * 3 + 1, 1), today)
    if name == "Прошлый квартал":
        q = (today.month - 1) // 3
        if q == 0:
            start = pd.Timestamp(today.year - 1, 10, 1)
            end = pd.Timestamp(today.year - 1, 12, 31)
        else:
            start = pd.Timestamp(today.year, (q - 1) * 3 + 1, 1)
            end = pd.Timestamp(today.year, q * 3 + 1, 1) - pd.Timedelta(days=1)
        return (start, end)
    if name == "Этот год":
        return (pd.Timestamp(today.year, 1, 1), today)
    return (pd.Timestamp(data_min), pd.Timestamp(data_max))


def _ru_quarter_label(dt: pd.Timestamp) -> str:
    q = (dt.month - 1) // 3 + 1
    return f"Q{q} {dt.year}"


def _compute_compare_range(preset: str, cur_from: pd.Timestamp, cur_to: pd.Timestamp):
    """Возвращает (prev_from, prev_to, cur_label, prev_label) или None если
    сравнение по пресету не имеет смысла (например, «За всё время»)."""
    cur_from = pd.Timestamp(cur_from).normalize()
    cur_to = pd.Timestamp(cur_to).normalize()

    if preset == "За всё время":
        return None

    if preset == "Сегодня":
        prev = cur_from - pd.Timedelta(days=1)
        return prev, prev, f"Сегодня · {cur_from:%d.%m.%Y}", f"Вчера · {prev:%d.%m.%Y}"

    if preset == "Вчера":
        prev = cur_from - pd.Timedelta(days=1)
        return prev, prev, f"Вчера · {cur_from:%d.%m.%Y}", f"Позавчера · {prev:%d.%m.%Y}"

    # Недельные — vs аналогичный отрезок прошлой недели
    if preset == "Эта неделя":
        prev_from = cur_from - pd.Timedelta(days=7)
        prev_to = prev_from + (cur_to - cur_from)
        return (prev_from, prev_to,
                f"{cur_from:%d.%m} – {cur_to:%d.%m.%Y}",
                f"{prev_from:%d.%m} – {prev_to:%d.%m.%Y}")

    if preset == "Прошлая неделя":
        prev_from = cur_from - pd.Timedelta(days=7)
        prev_to = cur_to - pd.Timedelta(days=7)
        return (prev_from, prev_to,
                f"{cur_from:%d.%m} – {cur_to:%d.%m.%Y}",
                f"{prev_from:%d.%m} – {prev_to:%d.%m.%Y}")

    # Календарные «прошлые» — сравниваем с предыдущим полным календарным периодом
    if preset == "Прошлый месяц":
        prev_to = cur_from - pd.Timedelta(days=1)
        prev_from = prev_to.replace(day=1)
        return prev_from, prev_to, fmt_month_ru(cur_from, "full_year"), fmt_month_ru(prev_from, "full_year")

    if preset == "Прошлый квартал":
        prev_to = cur_from - pd.Timedelta(days=1)
        q_idx = (prev_to.month - 1) // 3
        prev_from = pd.Timestamp(prev_to.year, q_idx * 3 + 1, 1)
        return prev_from, prev_to, _ru_quarter_label(cur_from), _ru_quarter_label(prev_from)

    # «Этот месяц/квартал/год» — сравниваем same-period-to-date в прошлом
    if preset == "Этот месяц":
        prev_month_first = (cur_from - pd.DateOffset(months=1)).replace(day=1)
        days_into = (cur_to - cur_from).days
        prev_from = prev_month_first
        prev_to = prev_from + pd.Timedelta(days=days_into)
        cur_label = f"{fmt_month_ru(cur_from, 'full_year')} · 1–{cur_to.day}"
        prev_label = f"{fmt_month_ru(prev_from, 'full_year')} · 1–{prev_to.day}"
        return prev_from, prev_to, cur_label, prev_label

    if preset == "Этот квартал":
        q_idx = (cur_from.month - 1) // 3
        prev_q_idx = (q_idx - 1) % 4
        prev_year = cur_from.year if q_idx > 0 else cur_from.year - 1
        prev_from = pd.Timestamp(prev_year, prev_q_idx * 3 + 1, 1)
        days_into = (cur_to - cur_from).days
        prev_to = prev_from + pd.Timedelta(days=days_into)
        return prev_from, prev_to, _ru_quarter_label(cur_from), _ru_quarter_label(prev_from)

    if preset == "Этот год":
        prev_from = pd.Timestamp(cur_from.year - 1, 1, 1)
        days_into = (cur_to - cur_from).days
        prev_to = prev_from + pd.Timedelta(days=days_into)
        return prev_from, prev_to, f"{cur_from.year}", f"{prev_from.year}"

    # «Последние N дней» и «Произвольный» — предыдущий интервал той же длины
    length = (cur_to - cur_from)
    prev_to = cur_from - pd.Timedelta(days=1)
    prev_from = prev_to - length
    cur_label = f"{cur_from:%d.%m} – {cur_to:%d.%m.%Y}"
    prev_label = f"{prev_from:%d.%m} – {prev_to:%d.%m.%Y}"
    return prev_from, prev_to, cur_label, prev_label


# Hero: заголовок на всю ширину; триггер периода — отдельный плавающий контейнер
st.markdown(
    """
    <div class="ufo-hero-text">
      <h1>Окупаемость рекламы</h1>
      <div class="ufo-sub">UFO Hosting · Яндекс.Директ · LTV / CAC / Retention</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Текущий выбор хранится в session_state, чтобы popover был stateless
if "period_preset" not in st.session_state:
    st.session_state["period_preset"] = "За всё время"
preset = st.session_state["period_preset"]

# Плавающий триггер периода: через st.container(key=...) даём ему CSS-якорь,
# чтобы position:fixed в правом верхнем углу — всегда виден при скролле.
with st.container(key="period_picker"):
    with st.popover(f"📅 {preset}", use_container_width=True):
        # Группы пресетов
        for group_title, group_items in PERIOD_GROUPS:
            st.markdown(
                f'<div class="period-group-title">{group_title}</div>',
                unsafe_allow_html=True,
            )
            for item in group_items:
                active = item == preset
                if st.button(
                    item,
                    key=f"pp_{item}",
                    use_container_width=True,
                    type=("primary" if active else "tertiary"),
                ):
                    st.session_state["period_preset"] = item
                    # сбрасываем кастомный диапазон, чтобы не висел рядом
                    st.session_state.pop("period_custom_active", None)
                    st.rerun()

        # Произвольный период — 2 поля, автоприменение без кнопки
        st.markdown(
            '<div class="period-group-title">ПРОИЗВОЛЬНЫЙ ПЕРИОД</div>',
            unsafe_allow_html=True,
        )
        _pc_value = st.session_state.get(
            "period_custom_value", (overall_min, overall_max)
        )
        dcol_from, dcol_to = st.columns(2)
        with dcol_from:
            cf_val = st.date_input(
                "С даты",
                value=_pc_value[0],
                min_value=overall_min, max_value=overall_max,
                format="DD.MM.YYYY",
                key="period_custom_from",
            )
        with dcol_to:
            ct_val = st.date_input(
                "По дату",
                value=_pc_value[1],
                min_value=overall_min, max_value=overall_max,
                format="DD.MM.YYYY",
                key="period_custom_to",
            )
        # Автоприменение: если оба поля валидны и пользователь изменил хоть одно
        # относительно сохранённого — переключаемся на «Произвольный».
        if cf_val and ct_val and cf_val <= ct_val:
            new_value = (cf_val, ct_val)
            if new_value != _pc_value or not st.session_state.get("period_custom_active"):
                if new_value != (overall_min, overall_max) or st.session_state.get("period_custom_active"):
                    # Применяем только если пользователь реально изменил даты
                    # (а не просто открыл popover с дефолтным диапазоном)
                    if new_value != _pc_value:
                        st.session_state["period_preset"] = "Произвольный"
                        st.session_state["period_custom_value"] = new_value
                        st.session_state["period_custom_active"] = True
                        st.rerun()
        elif cf_val and ct_val and cf_val > ct_val:
            st.caption(f"⚠️ «С даты» позже, чем «По дату» — поменяйте порядок.")

# Расчёт фактических дат по выбранному пресету
if preset == "Произвольный" and st.session_state.get("period_custom_active"):
    pc = st.session_state.get("period_custom_value", (overall_min, overall_max))
    d_from, d_to = pd.Timestamp(pc[0]), pd.Timestamp(pc[1])
else:
    d_from, d_to = _compute_preset_range(
        preset, pd.Timestamp(overall_max), pd.Timestamp(overall_min)
    )
    d_from = max(d_from, pd.Timestamp(overall_min))
    d_to = min(d_to, pd.Timestamp(overall_max))

# Подзаголовок с актуальным диапазоном дат
st.markdown(
    f'<div class="ufo-hero-range">Период: <b>{d_from:%d.%m.%Y} — {d_to:%d.%m.%Y}</b></div>',
    unsafe_allow_html=True,
)


with placeholder_filters:
    # PDF / Print
    import streamlit.components.v1 as components
    pdf_clicked = st.button(
        "📄 Сохранить отчёт в PDF",
        use_container_width=True,
        help="Откроется системный диалог печати — выберите «Сохранить как PDF».",
        key="print_pdf_btn",
    )
    if pdf_clicked:
        components.html(
            "<script>setTimeout(()=>{ window.parent.print(); }, 100);</script>",
            height=0,
        )

    with st.expander("⚙️ Настройки расчёта прибыли", expanded=False):
        cogs_pct = st.slider(
            "Себестоимость (COGS), %",
            min_value=0, max_value=80, value=30, step=5,
            help=(
                "Доля себестоимости от выручки. Для хостинга обычно 25–35% "
                "(датацентры, лицензии). Используется в расчёте чистой прибыли: "
                "Прибыль = Доход − COGS − Расход на рекламу."
            ),
        )
        st.caption(
            "Атрибуция: все клиенты учтены как от Директа (100%). "
            "Точная атрибуция появится после внедрения GA4 purchase-событий."
        )
    cogs_factor = cogs_pct / 100.0
    # Атрибуция = 100% всегда. Слайдер удалён — создавал иллюзию точности
    # и был несовместим с другими KPI, которые считались без учёта.
    attribution_factor = 1.0

    st.divider()
    from _shared import render_cache_reset_button as _reset_btn
    _reset_btn(key_prefix="dashboard")

    # Кнопка «Выйти» — только если включена парольная защита
    if os.environ.get("APP_PASSWORD"):
        st.divider()
        if st.button("🚪 Выйти", use_container_width=True, key="logout_btn",
                     help="Сбросить вход на этом устройстве. Чтобы зайти заново — потребуется пароль."):
            st.session_state.pop("auth_ok", None)
            st.query_params.clear()
            st.rerun()


orders = M.filter_orders_by_period(orders_all, d_from, d_to)

# Объединяем XLSX и API расходы по принципу «лучший источник на месяц»
# - Для каждого месяца, в котором есть данные API: если API покрывает ≥80% от XLSX,
#   считаем что API даёт полный месяц и замещаем XLSX.
# - Иначе оставляем XLSX (API частичный, чтобы не задвоить данные).
ads_combined = ads_all
# Источник API: session (ручной Sync) приоритетнее кэша из daily action
_api_ads_source = st.session_state.get("yd_api_ads")
if _api_ads_source is None or (hasattr(_api_ads_source, "empty") and _api_ads_source.empty):
    _api_ads_source = _load_api_cache_df()
if _api_ads_source is not None and not _api_ads_source.empty:
    api_ads = _api_ads_source
    api_sum_by_month = api_ads.groupby("month")["spend_rub"].sum()
    xlsx_sum_by_month = ads_all.groupby("month")["spend_rub"].sum() if not ads_all.empty else pd.Series(dtype=float)
    months_replace = set()  # API замещает XLSX за этот месяц целиком
    months_add = set()       # месяца есть только в API — просто добавить
    for m, api_v in api_sum_by_month.items():
        xlsx_v = xlsx_sum_by_month.get(m, 0)
        if xlsx_v == 0:
            months_add.add(m)
        elif api_v >= 0.8 * xlsx_v:
            months_replace.add(m)
        # иначе — API частичный, игнорируем за этот месяц
    keep_api_months = months_replace | months_add
    xlsx_keep = ads_all[~ads_all["month"].isin(months_replace)] if not ads_all.empty else ads_all
    api_keep = api_ads[api_ads["month"].isin(keep_api_months)]
    if not api_keep.empty:
        ads_combined = pd.concat([xlsx_keep, api_keep], ignore_index=True)
    else:
        ads_combined = ads_all

ads = M.filter_ads_by_period(ads_combined, d_from, d_to)
ads_all = ads_combined  # чтобы остальной код видел совместный набор


period_label = f"{d_from:%d.%m.%Y} – {d_to:%d.%m.%Y}"


# ============================================================
#                       Покрытие данными
# ============================================================

coverage = M.data_coverage(orders, ads)
if not coverage.empty:
    months_with_orders = coverage[coverage["has_orders"]]["month"].tolist()
    months_only_ads = coverage[(coverage["has_ads"]) & (~coverage["has_orders"])]["month"].tolist()
    months_only_orders = coverage[(coverage["has_orders"]) & (~coverage["has_ads"])]["month"].tolist()

    st.markdown('<div class="section-title">Покрытие данными по периоду</div>', unsafe_allow_html=True)

    # Лента месяцев
    cells_html = []
    for _, row in coverage.iterrows():
        m_label = fmt_month_ru(row["month"], "short_year")
        if row["has_orders"] and row["has_ads"]:
            bg = "#dcfce7"; border = "#86efac"; icon = "✓"; tip = f"CSV: {int(row['orders_count'])} оплат · Директ: {fmt_rub(row['ads_spend'])}"
        elif row["has_ads"] and not row["has_orders"]:
            bg = "#fef9c3"; border = "#facc15"; icon = "⚠"; tip = f"Только Директ: {fmt_rub(row['ads_spend'])}. Нет CSV выгрузки"
        elif row["has_orders"] and not row["has_ads"]:
            bg = "#dbeafe"; border = "#93c5fd"; icon = "○"; tip = f"Только CSV: {int(row['orders_count'])} оплат. Нет данных Директа"
        else:
            bg = "#f1f5f9"; border = "#cbd5e1"; icon = "·"; tip = "Нет данных"
        cells_html.append(
            f'<div title="{tip}" class="coverage-cell" style="background:{bg}; '
            f'border:1px solid {border};">'
            f'<div class="coverage-cell-icon">{icon}</div>'
            f'<div class="coverage-cell-label">{m_label}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div class="coverage-row">{"".join(cells_html)}</div>',
        unsafe_allow_html=True,
    )

    n_only_ads = len(months_only_ads)
    if n_only_ads > 0:
        missing_list = ", ".join(fmt_month_ru(m, "low_year") for m in months_only_ads)
        st.warning(
            f"**Не хватает CSV-выгрузок за {n_only_ads} "
            f"{plural_ru(n_only_ads, 'месяц', 'месяца', 'месяцев')}:** {missing_list}.  \n"
            f"Запросите у клиента «Содержимое заказов» из админки UFO Hosting за эти периоды — "
            f"тогда ROMI пересчитается с реальным доходом.",
            icon="📋",
        )


# ============================================================
#                       Главные KPI
# ============================================================

# Полный KPI за выбранный период (без отрезания до overlap).
# Пользователь видит реальные расходы на Директ за весь период работы.
ck = _cached_compute_kpi(orders, ads)
revenue_attr = ck.revenue * attribution_factor
net = revenue_attr - ck.spend
romi_pct = (net / ck.spend * 100) if ck.spend else 0.0
cac = ck.spend / max(ck.new_clients, 1)
ltv_cac = ck.arpu / cac if cac else 0.0

# P&L (Profit & Loss): прибыль = доход − себестоимость − реклама
cogs_amount = ck.revenue * cogs_factor
profit = ck.revenue - cogs_amount - ck.spend
profit_margin = (profit / ck.revenue * 100) if ck.revenue > 0 else 0.0

# Sparkline-тренды за месяцы (для вставки в плитки)
_ms = _cached_monthly_summary(orders, ads)
spark_spend = _ms["spend"].tolist() if not _ms.empty else []
spark_revenue = _ms["revenue"].tolist() if not _ms.empty else []
spark_new = _ms["new_clients"].tolist() if not _ms.empty else []
spark_romi = _ms["romi"].fillna(0).tolist() if not _ms.empty else []
spark_cac = _ms["cac"].fillna(0).tolist() if not _ms.empty else []

# Считаем prev-период один раз, чтобы Hero и блок «Сравнение» использовали общий результат
compare_range = _compute_compare_range(preset, d_from, d_to)
prev_kpi = None
prev_profit = None
if compare_range is not None:
    _prev_from, _prev_to, _cur_label, _prev_label = compare_range
    prev_kpi = _cached_compute_kpi(
        M.filter_orders_by_period(orders_all, _prev_from, _prev_to),
        M.filter_ads_by_period(ads_all, _prev_from, _prev_to),
    )
    prev_profit = prev_kpi.revenue - prev_kpi.revenue * cogs_factor - prev_kpi.spend


def _hero_delta_html(cur_val, prev_val, *, invert=False, suffix=""):
    """HTML для плашки дельты «↑ 12.3% vs прошлый». invert=True для метрик,
    где рост — плохо (например, расход)."""
    if prev_val is None or prev_val == 0 or pd.isna(prev_val):
        return ""
    pct = (cur_val - prev_val) / abs(prev_val) * 100
    arrow = "↑" if pct >= 0 else "↓"
    positive = (pct >= 0) if not invert else (pct <= 0)
    cls = "up" if positive else "down"
    return f'<span class="kpi-hero-delta {cls}">{arrow} {abs(pct):.1f}%{suffix}</span>'


# ─── Hero KPI: Прибыль (большая плитка) ──────────────────────
profit_hero_kind = "green" if profit >= 0 else "red"
profit_delta = _hero_delta_html(profit, prev_profit, suffix=" vs прошлый")

# Предупреждение о неоднородности данных: если есть месяцы с расходом на
# Директ, но без CSV платежей — главный ROMI смешивает 9 месяцев расхода
# с N месяцами дохода. Показываем «честный» ROMI за overlap-период.
_data_mismatch_note = ""
_ck_comp = M.comparable_kpi(orders, ads)
if _ck_comp is not None and _ck_comp.spend > 0 and ck.spend > 0:
    _romi_full = (ck.revenue - ck.spend) / ck.spend * 100
    _romi_comp = (_ck_comp.revenue - _ck_comp.spend) / _ck_comp.spend * 100
    # Триггерим только при значимом расхождении (≥5 п.п.) — иначе шум
    if (ck.spend - _ck_comp.spend) > 0 and abs(_romi_full - _romi_comp) >= 5:
        _missing_share = (ck.spend - _ck_comp.spend) / ck.spend * 100
        _data_mismatch_note = (
            f'<div style="margin-top:0.55rem; padding:0.5rem 0.7rem; '
            f'background:rgba(250,204,21,0.18); border-left:3px solid #facc15; '
            f'border-radius:4px; font-size:0.78rem; color:#525a62; line-height:1.45;">'
            f'⚠️ <b>{_missing_share:.0f}%</b> расхода на Директ '
            f'({fmt_rub(ck.spend - _ck_comp.spend)}) приходится на месяцы, '
            f'за которые нет CSV-выгрузок — поэтому общий ROMI занижен. '
            f'Честный ROMI за overlap-период: <b>{_romi_comp:+.1f}%</b> '
            f'(доход {fmt_rub(_ck_comp.revenue)} vs расход {fmt_rub(_ck_comp.spend)}). '
            f'Подгрузите CSV за недостающие месяцы — цифра пересчитается.'
            f'</div>'
        )

st.markdown(
    f"""
    <div class="kpi-hero {profit_hero_kind}">
      <div class="kpi-hero-main">
        <div class="kpi-hero-label">Чистая прибыль · {period_label}</div>
        <div class="kpi-hero-value">{fmt_rub(profit)} {profit_delta}</div>
        <div class="kpi-hero-sub">
          Доход <b>{fmt_rub(ck.revenue)}</b> минус себестоимость <b>{fmt_rub(cogs_amount)}</b> ({cogs_pct}%)
          минус расход на Директ <b>{fmt_rub(ck.spend)}</b> · маржа {profit_margin:+.1f}%
        </div>
        {_data_mismatch_note}
      </div>
      <div class="kpi-hero-breakdown">
        <div class="kpi-hero-bd-item">
          <div class="kpi-hero-bd-label">Доход</div>
          <div class="kpi-hero-bd-value" style="color:{PALETTE['green']};">{fmt_rub(ck.revenue)}</div>
        </div>
        <div class="kpi-hero-bd-item">
          <div class="kpi-hero-bd-label">Расход</div>
          <div class="kpi-hero-bd-value" style="color:{PALETTE['red']};">−{fmt_rub(ck.spend, suffix=' ₽')}</div>
        </div>
        <div class="kpi-hero-bd-item">
          <div class="kpi-hero-bd-label">ROMI</div>
          <div class="kpi-hero-bd-value" style="color:{PALETTE['green'] if net >= 0 else PALETTE['red']};">{romi_pct:+.1f}%</div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ─── Авто-инсайты ─────────────────────────────────────────────
# Вычисляем churn_summary раньше — нужно и для инсайтов, и для блока «Здоровье базы» ниже.
ch_sum_early = _cached_churn_summary(orders)
_insights = _generate_insights(orders, ads, ck, _ms, ch_sum_early, prev_kpi=prev_kpi)
_render_insights(_insights)

# ─── Row 1 — операционные плитки ─────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.markdown(kpi_card(
    "Расход на Директ",
    fmt_rub(ck.spend),
    f"с НДС · {period_label}", kind="red", delta_kind="neutral",
    tooltip="Сумма списаний в Яндекс.Директе за период. Суммы указаны с учётом НДС (как у Яндекса). Тянется из XLSX или из API.",
    spark_values=spark_spend,
), unsafe_allow_html=True)
c2.markdown(kpi_card(
    "Доход (оплаты)",
    fmt_rub(ck.revenue),
    f"{ck.orders_paid:,} {plural_ru(ck.orders_paid, 'оплата', 'оплаты', 'оплат')}".replace(",", " "),
    kind="green",
    tooltip="Реально поступившие деньги от клиентов за период. Из CSV-выгрузок «Содержимое заказов» (статус «Оплачен»).",
    spark_values=spark_revenue,
), unsafe_allow_html=True)
romi_kind = "up" if net >= 0 else "down"
romi_arrow = "↑" if net >= 0 else "↓"
romi_color_kind = "green" if net >= 0 else "red"
c3.markdown(kpi_card(
    "ROMI",
    f"{romi_pct:+.1f}%",
    f"{romi_arrow} {fmt_rub(abs(net))} {'прибыли' if net >= 0 else 'к окупаемости'}",
    kind=romi_color_kind, delta_kind=romi_kind,
    tooltip="Return On Marketing Investment = (Доход − Расход) / Расход. >0 — реклама окупается. Для хостинга норма раскрывается на горизонте 6–12 мес. за счёт повторных оплат. Атрибуция: 100% (все клиенты как от Директа).",
    spark_values=spark_romi,
), unsafe_allow_html=True)
c4.markdown(kpi_card(
    "Клиенты",
    fmt_num(ck.unique_clients),
    f"новых: {ck.new_clients} · повторных: {ck.repeat_clients}",
    kind="primary",
    tooltip="Уникальные клиенты с хотя бы одной оплатой в периоде. Новый = первая оплата клиента помечена «Новый». Повторный = оплата клиента, зарегистрированного раньше.",
    spark_values=spark_new,
), unsafe_allow_html=True)

st.markdown("<div style='height: 0.4rem'></div>", unsafe_allow_html=True)

# ─── Row 2 — клиентские плитки ───────────────────────────────
c5, c6, c7, c8 = st.columns(4)
c5.markdown(kpi_card(
    "CAC", fmt_rub(cac), "стоимость нового клиента",
    tooltip="Customer Acquisition Cost = Расход на рекламу / число новых клиентов. Чем ниже, тем дешевле привлечение.",
    spark_values=spark_cac,
), unsafe_allow_html=True)
c6.markdown(kpi_card(
    "ARPU", fmt_rub(ck.arpu), "доход на клиента",
    tooltip="Average Revenue Per User = Доход / уникальных клиентов. Сколько в среднем приносит один клиент за период.",
), unsafe_allow_html=True)
ltv_kind = "up" if ltv_cac >= 1 else "down"
ltv_color = "green" if ltv_cac >= 1 else "red"
c7.markdown(kpi_card(
    "LTV / CAC",
    f"{ltv_cac:.2f}×",
    f"{ck.avg_orders_per_client:.2f} оплат на клиента",
    kind=ltv_color, delta_kind=ltv_kind,
    tooltip="Отношение пожизненной ценности клиента к стоимости его привлечения. 1× — окупается, 3× — прибыльная модель. У хостинга растёт во времени за счёт продлений.",
), unsafe_allow_html=True)
c8.markdown(kpi_card(
    "Средний чек",
    fmt_rub(ck.avg_check),
    f"{ck.orders_paid} {plural_ru(ck.orders_paid, 'оплата', 'оплаты', 'оплат')}",
    tooltip="Средняя сумма одной оплаты в периоде. Полезно сравнивать с MoM динамикой — растёт ли средний чек.",
), unsafe_allow_html=True)


# ============================================================
#                       Сравнение с прошлым периодом
# ============================================================

# Используем prev_kpi, посчитанный выше (для Hero KPI). compare_range
# даёт читаемые подписи периодов («Май 2026 · 1–16» vs «Апрель 2026 · 1–16»).
pc = None
if compare_range is not None and prev_kpi is not None:
    def _dpct(a, b):
        if b is None or pd.isna(b) or b == 0:
            return None
        return (a - b) / abs(b) * 100

    pc = {
        "current": ck, "previous": prev_kpi,
        "current_label": _cur_label,
        "prev_label": _prev_label,
        "deltas": {
            "spend": _dpct(ck.spend, prev_kpi.spend),
            "revenue": _dpct(ck.revenue, prev_kpi.revenue),
            "new_clients": _dpct(ck.new_clients, prev_kpi.new_clients),
            "arpu": _dpct(ck.arpu, prev_kpi.arpu),
            "avg_check": _dpct(ck.avg_check, prev_kpi.avg_check),
        },
    }

if pc:
    st.markdown(
        f'<div class="section-title">Сравнение: <span style="color:{PALETTE["text"]}; '
        f'text-transform:none; letter-spacing:0;">{pc["current_label"]}</span> '
        f'<span style="color:{PALETTE["muted"]}; font-weight:400;">vs</span> '
        f'<span style="color:{PALETTE["muted"]}; text-transform:none; letter-spacing:0;">{pc["prev_label"]}</span></div>',
        unsafe_allow_html=True,
    )

    def _delta_html(label, current_fmt, prev_fmt, delta_val, *, invert=False):
        if delta_val is None or pd.isna(delta_val):
            return kpi_card(label, current_fmt, f"было: {prev_fmt}", delta_kind="neutral")
        arrow = "↑" if delta_val >= 0 else "↓"
        # invert=True если для метрики «расход» рост — это плохо
        positive = (delta_val >= 0) if not invert else (delta_val <= 0)
        delta_kind = "up" if positive else "down"
        return kpi_card(
            label, current_fmt,
            f"{arrow} {abs(delta_val):.1f}% · было: {prev_fmt}",
            delta_kind=delta_kind,
        )

    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    cc1.markdown(_delta_html(
        "Расход",
        fmt_rub(pc["current"].spend), fmt_rub(pc["previous"].spend),
        pc["deltas"]["spend"], invert=True,
    ), unsafe_allow_html=True)
    cc2.markdown(_delta_html(
        "Доход",
        fmt_rub(pc["current"].revenue), fmt_rub(pc["previous"].revenue),
        pc["deltas"]["revenue"],
    ), unsafe_allow_html=True)
    cc3.markdown(_delta_html(
        "Новых клиентов",
        fmt_num(pc["current"].new_clients), fmt_num(pc["previous"].new_clients),
        pc["deltas"]["new_clients"],
    ), unsafe_allow_html=True)
    cc4.markdown(_delta_html(
        "ARPU",
        fmt_rub(pc["current"].arpu), fmt_rub(pc["previous"].arpu),
        pc["deltas"]["arpu"],
    ), unsafe_allow_html=True)
    cc5.markdown(_delta_html(
        "Средний чек",
        fmt_rub(pc["current"].avg_check), fmt_rub(pc["previous"].avg_check),
        pc["deltas"]["avg_check"],
    ), unsafe_allow_html=True)


# ============================================================
#                       What-if симулятор бюджета
# ============================================================

# Берём «рабочие» CAC и ARPU per new — последние 3 месяца с данными.
# Базовая точка = средние за эти 3 месяца, слайдер моделирует ОТНОСИТЕЛЬНО неё.
# Это даёт честный прогноз при сохранении текущей эффективности Директа,
# а не средне-исторический CAC (он перекошен старым аккаунтом).
_sim_base_rows = _ms[_ms["cac"].notna() & (_ms["cac"] > 0) & (_ms["new_clients"] > 0)].tail(3)
if not _sim_base_rows.empty:
    _sim_total_spend = float(_sim_base_rows["spend"].sum())
    _sim_total_new = float(_sim_base_rows["new_clients"].sum())
    _sim_total_rev_from_new = float(_sim_base_rows.get("revenue_from_new", _sim_base_rows["revenue"]).sum())
    _sim_n_months = len(_sim_base_rows)
    _sim_base = {
        "spend_per_month": _sim_total_spend / _sim_n_months,
        "new_per_month": _sim_total_new / _sim_n_months,
        "cac": _sim_total_spend / max(_sim_total_new, 1),
        "revenue_per_new": _sim_total_rev_from_new / max(_sim_total_new, 1),
        "label": (
            f"{fmt_month_ru(_sim_base_rows.iloc[0]['month'], 'low_year')}"
            f" – {fmt_month_ru(_sim_base_rows.iloc[-1]['month'], 'low_year')}"
        ),
        "cogs_factor": cogs_factor,
    }

    st.markdown('<div class="section-title">Симулятор бюджета · что если?</div>', unsafe_allow_html=True)

    @st.fragment
    def _render_whatif_simulator(base):
        """Изолированный фрагмент — слайдеры внутри пересчитывают только этот блок,
        а не всю страницу. Streamlit ≥ 1.32."""
        sim_col_l, sim_col_r = st.columns([1.1, 1.4])
        with sim_col_l:
            st.markdown(
                f"<div style='color:{PALETTE['muted']}; font-size:0.82rem; margin-bottom:0.4rem;'>"
                f"База — средний месяц за <b>{base['label']}</b>:<br>"
                f"бюджет <b>{fmt_rub(base['spend_per_month'])}</b> · "
                f"новых клиентов <b>{fmt_num(base['new_per_month'])}</b> · "
                f"CAC <b>{fmt_rub(base['cac'])}</b> · "
                f"доход с нового в M+0 <b>{fmt_rub(base['revenue_per_new'])}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )
            sim_delta = st.slider(
                "Изменить бюджет на месяц",
                min_value=-80, max_value=300, value=0, step=10,
                format="%+d%%",
                key="whatif_budget_pct",
                help=(
                    "Прогноз при сохранении текущего CAC и ARPU. "
                    "Реальная эффективность с ростом бюджета обычно немного снижается "
                    "(закон убывающей отдачи) — закладывайте запас 20–30%."
                ),
            )
            sim_ltv_mult = st.slider(
                "Горизонт LTV (мес)",
                min_value=1, max_value=12, value=3, step=1,
                key="whatif_ltv_horizon",
                help=(
                    "Сколько месяцев считаем доход с нового клиента. "
                    "M=1 — только первая оплата (консервативно, обычно реклама в минусе). "
                    "M=6 — клиент платит полгода (близко к реальному LTV для хостинга)."
                ),
            )

        new_spend = base["spend_per_month"] * (1 + sim_delta / 100)
        new_clients_proj = new_spend / max(base["cac"], 1)
        extra_clients = new_clients_proj - base["new_per_month"]
        revenue_per_client_horizon = base["revenue_per_new"] * sim_ltv_mult
        proj_revenue = new_clients_proj * revenue_per_client_horizon
        proj_cogs = proj_revenue * base["cogs_factor"]
        proj_profit = proj_revenue - proj_cogs - new_spend
        proj_romi = ((proj_revenue - new_spend) / new_spend * 100) if new_spend else 0

        with sim_col_r:
            budget_kind = "primary" if sim_delta != 0 else ""
            budget_delta = f"{sim_delta:+d}% к базе" if sim_delta else "= база"
            clients_delta = (
                f"+{int(round(extra_clients))} к базе" if extra_clients > 0.5
                else (f"{int(round(extra_clients))} к базе" if extra_clients < -0.5 else "= база")
            )
            romi_kind = "green" if proj_romi >= 0 else "red"

            sc1, sc2 = st.columns(2)
            sc1.markdown(kpi_card(
                "Бюджет на месяц",
                fmt_rub(new_spend),
                budget_delta,
                kind=budget_kind,
            ), unsafe_allow_html=True)
            sc2.markdown(kpi_card(
                "Прогноз новых клиентов",
                fmt_num(new_clients_proj),
                clients_delta,
                kind="primary",
            ), unsafe_allow_html=True)
            sc3, sc4 = st.columns(2)
            sc3.markdown(kpi_card(
                f"Доход за M+{sim_ltv_mult}",
                fmt_rub(proj_revenue),
                f"{fmt_rub(revenue_per_client_horizon)} × {fmt_num(new_clients_proj)} клиентов",
                kind="green",
            ), unsafe_allow_html=True)
            sc4.markdown(kpi_card(
                "Прогнозный ROMI",
                f"{proj_romi:+.1f}%",
                f"прибыль {fmt_rub(proj_profit)}",
                kind=romi_kind,
                delta_kind=("up" if proj_romi >= 0 else "down"),
            ), unsafe_allow_html=True)

        st.caption(
            "Грубая модель: при увеличении бюджета пропорционально вырастают клиенты "
            "по текущему CAC. В реальности с ростом бюджета CAC обычно растёт (CPC выше, "
            "хуже релевантность) — закладывайте запас 20–30%. "
            "Горизонт LTV M=1 = только первая оплата (хостинг обычно не окупается за месяц, "
            "это нормально), M=6 ≈ реальный LTV годовой подписки."
        )

    _render_whatif_simulator(_sim_base)


# ============================================================
#                       Главный график: динамика
# ============================================================

st.markdown('<div class="section-title">Динамика по месяцам</div>', unsafe_allow_html=True)

ms = _cached_monthly_summary(orders, ads)
if not ms.empty:
    ms_d = ms.copy()
    ms_d["month_label"] = ms_d["month"].dt.strftime("%b %Y")

    fig = go.Figure()
    fig.add_bar(
        x=ms_d["month_label"], y=ms_d["spend"],
        name="Расход на Директ", marker_color=PALETTE["red"],
        hovertemplate="<b>%{x}</b><br>Расход: %{y:,.0f} ₽<extra></extra>",
    )
    fig.add_bar(
        x=ms_d["month_label"], y=ms_d["revenue"],
        name="Доход (оплаты)", marker_color=PALETTE["green"],
        hovertemplate="<b>%{x}</b><br>Доход: %{y:,.0f} ₽<extra></extra>",
    )
    fig.add_scatter(
        x=ms_d["month_label"], y=ms_d["new_clients"],
        name="Новых клиентов", mode="lines+markers", yaxis="y2",
        line=dict(color=PALETTE["primary"], width=3), marker=dict(size=8),
        hovertemplate="<b>%{x}</b><br>Новых клиентов: %{y}<extra></extra>",
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        height=420, barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis_title="Рубли",
        yaxis2=dict(
            title="Новых клиентов", overlaying="y", side="right",
            gridcolor="#eaeef2",
        ),
    )
    st.plotly_chart(fig, use_container_width=True)


# ============================================================
#                       Тройка: продукты · топ-клиенты · повторные
# ============================================================

col_left, col_mid, col_right = st.columns([1.1, 1.1, 0.9])

with col_left:
    st.markdown('<div class="section-title">Структура продаж</div>', unsafe_allow_html=True)
    fam = M.product_mix(orders, by="product_family")
    if not fam.empty:
        top_fam = fam.head(7).copy()
        if len(fam) > 7:
            rest = pd.DataFrame([{
                "product_family": "Прочее",
                "revenue": fam.iloc[7:]["revenue"].sum(),
                "orders": fam.iloc[7:]["orders"].sum(),
                "clients": fam.iloc[7:]["clients"].sum(),
                "avg_check": 0, "share": fam.iloc[7:]["share"].sum(),
            }])
            top_fam = pd.concat([top_fam, rest], ignore_index=True)

        fig = px.pie(
            top_fam, values="revenue", names="product_family",
            hole=0.55,
            color_discrete_sequence=[
                PALETTE["primary"], PALETTE["purple"], PALETTE["green"],
                PALETTE["orange"], PALETTE["red"], "#5fb3d4", "#d4945f", "#888fa8",
            ],
        )
        fig.update_traces(
            textposition="outside",
            textinfo="label+percent",
            textfont=dict(color=PALETTE["text"], size=11),
            hovertemplate="<b>%{label}</b><br>Доход: %{value:,.0f} ₽<br>%{percent}<extra></extra>",
        )
        fig.update_layout(
            **{**PLOTLY_LAYOUT, "margin": dict(t=10, l=10, r=10, b=10)},
            height=340, showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

with col_mid:
    st.markdown('<div class="section-title">Топ клиенты по LTV</div>', unsafe_allow_html=True)
    tc = M.top_clients(orders, n=8)
    if not tc.empty:
        for _, row in tc.iterrows():
            name = row["client_name"] or row["client_key"]
            if isinstance(name, str) and len(name) > 28:
                name = name[:26] + "…"
            email = row["client_key"]
            if isinstance(email, str) and len(email) > 32:
                email = email[:30] + "…"
            st.markdown(
                f"""<div style='display:flex; justify-content:space-between; padding:0.55rem 0.75rem;
                margin-bottom:0.35rem; background:#ffffff; border-radius:8px;
                border:1px solid {PALETTE['border']};'>
                <div>
                  <div style='font-weight:600; color:{PALETTE['text']};'>{name}</div>
                  <div style='font-size:0.72rem; color:{PALETTE['muted']};'>{email} · {row['orders']} {plural_ru(row['orders'], 'оплата', 'оплаты', 'оплат')}</div>
                </div>
                <div style='text-align:right;'>
                  <div style='font-weight:700; color:{PALETTE['green']};'>{fmt_rub(row['total_paid'])}</div>
                  <div style='font-size:0.72rem; color:{PALETTE['muted']};'>{int(row['lifespan_days']) if pd.notna(row['lifespan_days']) else 0} дн.</div>
                </div></div>""",
                unsafe_allow_html=True,
            )

with col_right:
    st.markdown('<div class="section-title">Повторные оплаты</div>', unsafe_allow_html=True)
    paid = orders[orders["is_paid"]]
    new_orders_cnt = int((paid["new_or_old"] == "Новый").sum())
    old_orders_cnt = int((paid["new_or_old"] == "Старый").sum())
    total_orders = new_orders_cnt + old_orders_cnt
    repeat_share = (old_orders_cnt / total_orders * 100) if total_orders else 0

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=repeat_share,
        number={"suffix": "%", "font": {"color": PALETTE["green"], "size": 36}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": PALETTE["muted"], "tickfont": {"color": PALETTE["muted"]}},
            "bar": {"color": PALETTE["green"], "thickness": 0.8},
            "bgcolor": "#ffffff",
            "borderwidth": 1,
            "bordercolor": PALETTE["border"],
            "steps": [
                {"range": [0, 30], "color": "#fef2f2"},
                {"range": [30, 60], "color": "#fef9c3"},
                {"range": [60, 100], "color": "#dcfce7"},
            ],
        },
    ))
    fig.update_layout(
        **{**PLOTLY_LAYOUT, "margin": dict(t=10, l=20, r=20, b=10)},
        height=240,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        (
            f"**{old_orders_cnt:,}** {plural_ru(old_orders_cnt, 'повторная', 'повторных', 'повторных')} · "
            f"**{new_orders_cnt:,}** {plural_ru(new_orders_cnt, 'новая', 'новых', 'новых')} "
            f"{plural_ru(new_orders_cnt + old_orders_cnt, 'оплата', 'оплаты', 'оплат')}  \n"
            f"Для хостинга 60%+ — сильный показатель удержания."
        ).replace(",", " ")
    )


# ============================================================
#                       Churn / здоровье клиентской базы
# ============================================================

ch_sum = ch_sum_early  # уже посчитан выше для инсайтов
if ch_sum:
    st.markdown('<div class="section-title">Здоровье клиентской базы</div>', unsafe_allow_html=True)

    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.markdown(kpi_card(
        "Активные",
        fmt_num(ch_sum["active"]),
        f"оплата ≤ 30 дней назад · {ch_sum['active']/max(ch_sum['total_clients'],1)*100:.0f}% базы",
        kind="green",
        tooltip="Клиенты с оплатой не далее 30 дней назад. Это «работающие» клиенты, активно генерирующие выручку.",
    ), unsafe_allow_html=True)
    cc2.markdown(kpi_card(
        "Под риском",
        fmt_num(ch_sum["at_risk"]),
        f"31–90 дней без оплат · {fmt_rub(ch_sum['at_risk_revenue'])} в потенциале",
        kind="orange",
        tooltip="Не платили 31–90 дней. Это «зона спасения» — пока ещё можно вернуть скидкой, письмом, звонком. После 90 дней — статистически уже отток.",
    ), unsafe_allow_html=True)
    cc3.markdown(kpi_card(
        "Отток",
        fmt_num(ch_sum["churned"]),
        f"> 90 дней без оплат",
        kind="red",
        tooltip="Клиенты, не платившие более 90 дней. С большой вероятностью уже не вернутся. Включаются в расчёт churn rate.",
    ), unsafe_allow_html=True)
    cc4.markdown(kpi_card(
        "Churn rate",
        f"{ch_sum['churn_rate']:.1f}%",
        f"норма для хостинга: до 5% в месяц",
        kind="red" if ch_sum["churn_rate"] > 5 else "green",
        tooltip="Доля клиентов в оттоке от общего числа. Промышленная норма для хостинга — менее 5% месячных оттоков. Выше — повод смотреть продукт и клиентский сервис.",
    ), unsafe_allow_html=True)


# ============================================================
#                       MRR (Monthly Recurring Revenue)
# ============================================================

mrr = M.mrr_by_month(orders)
if not mrr.empty and len(mrr) >= 1:
    st.markdown('<div class="section-title">MRR · ежемесячная выручка</div>', unsafe_allow_html=True)

    mrr_d = mrr.copy()
    mrr_d["month_label"] = mrr_d["payment_month"].dt.strftime("%b %Y")

    fig_mrr = go.Figure()
    fig_mrr.add_bar(
        x=mrr_d["month_label"], y=mrr_d["new_mrr"],
        name="От новых клиентов",
        marker_color=PALETTE["primary"],
        hovertemplate="%{x}<br>Новые: %{y:,.0f} ₽<extra></extra>",
    )
    fig_mrr.add_bar(
        x=mrr_d["month_label"], y=mrr_d["expansion_mrr"],
        name="От старых клиентов",
        marker_color=PALETTE["green"],
        hovertemplate="%{x}<br>Старые: %{y:,.0f} ₽<extra></extra>",
    )
    fig_mrr.update_layout(
        **PLOTLY_LAYOUT,
        height=300, barmode="stack",
        yaxis_title="Выручка, ₽",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fig_mrr, use_container_width=True)

    last = mrr.iloc[-1]
    last_growth = last.get("growth_pct")
    if pd.notna(last_growth):
        arrow = "↑" if last_growth >= 0 else "↓"
        color = PALETTE["green"] if last_growth >= 0 else PALETTE["red"]
        st.caption(
            f"Последний месяц: **{fmt_rub(last['mrr'])}** · "
            f"<span style='color:{color}; font-weight:600;'>{arrow} {abs(last_growth):.1f}% MoM</span> · "
            f"новые: {fmt_rub(last['new_mrr'])}, старые: {fmt_rub(last['expansion_mrr'])}",
            unsafe_allow_html=True,
        )


# ============================================================
#                       Pareto-сегментация клиентов
# ============================================================

par = M.pareto_summary(orders)
if par:
    st.markdown('<div class="section-title">Сегментация клиентов · ABC</div>', unsafe_allow_html=True)

    pcol1, pcol2 = st.columns([1, 1.4])

    with pcol1:
        labels = [
            f"A · топ ({par['A_clients']} клиентов)",
            f"B · средние ({par['B_clients']})",
            f"C · хвост ({par['C_clients']})",
        ]
        values = [par["A_revenue"], par["B_revenue"], par["C_revenue"]]
        fig_p = px.pie(
            names=labels, values=values, hole=0.55,
            color_discrete_sequence=[PALETTE["green"], PALETTE["primary"], PALETTE["muted"]],
        )
        fig_p.update_traces(
            textposition="outside",
            textinfo="percent",
            textfont=dict(color=PALETTE["text"], size=12),
            hovertemplate="<b>%{label}</b><br>%{value:,.0f} ₽<br>%{percent}<extra></extra>",
        )
        fig_p.update_layout(
            **{**PLOTLY_LAYOUT, "margin": dict(t=10, l=10, r=10, b=10)},
            height=280, showlegend=False,
        )
        st.plotly_chart(fig_p, use_container_width=True)

    with pcol2:
        for seg, color, descr in [
            ("A", PALETTE["green"], "ядро (≈ 80% выручки)"),
            ("B", PALETTE["primary"], "средний слой"),
            ("C", PALETTE["muted"], "хвост, низкая выручка"),
        ]:
            st.markdown(
                f"""<div style='padding:0.55rem 0.85rem; margin-bottom:0.35rem;
                background:#ffffff; border:1px solid {PALETTE['border']}; border-radius:8px;
                border-left:4px solid {color};
                display:flex; justify-content:space-between; align-items:center;'>
                <div>
                  <div style='font-weight:700; color:{PALETTE['text']};'>Сегмент {seg} · {descr}</div>
                  <div style='font-size:0.75rem; color:{PALETTE['muted']};'>
                    {par[f'{seg}_clients']} клиентов ({par[f'{seg}_share_clients']:.0f}% базы)
                  </div>
                </div>
                <div style='text-align:right;'>
                  <div style='font-weight:700; color:{color};'>{fmt_rub(par[f'{seg}_revenue'])}</div>
                  <div style='font-size:0.72rem; color:{PALETTE['muted']};'>{par[f'{seg}_share_revenue']:.1f}% выручки</div>
                </div>
                </div>""",
                unsafe_allow_html=True,
            )
        st.caption(
            "Сегмент A — кого нужно удерживать в первую очередь (личный контакт, апсейлы). "
            "Сегмент B — растить вверх через продление и кросс-продажу. "
            "Сегмент C — массовые рассылки и автоматизация, тратить на них минимум усилий."
        )


# ============================================================
#                       Воронка клиентов
# ============================================================

fn = M.funnel(orders)
if not fn.empty:
    st.markdown('<div class="section-title">Воронка клиентов</div>', unsafe_allow_html=True)

    fcol1, fcol2 = st.columns([1.4, 1])
    with fcol1:
        fig_fn = go.Figure(go.Funnel(
            y=fn["stage"],
            x=fn["count"],
            textinfo="value+percent initial",
            marker=dict(color=[PALETTE["primary"], PALETTE["green"], PALETTE["orange"], PALETTE["purple"]]),
            connector=dict(line=dict(color=PALETTE["border"], width=1)),
        ))
        fig_fn.update_layout(**PLOTLY_LAYOUT, height=320)
        st.plotly_chart(fig_fn, use_container_width=True)

    with fcol2:
        total = fn.iloc[0]["count"]
        for _, row in fn.iterrows():
            share = row["count"] / total * 100 if total else 0
            st.markdown(
                f"""<div style='padding:0.5rem 0.7rem; margin-bottom:0.4rem; background:#ffffff;
                border:1px solid {PALETTE['border']}; border-radius:8px;
                display:flex; justify-content:space-between; align-items:center;'>
                <div style='color:{PALETTE['text']}; font-weight:500;'>{row['stage']}</div>
                <div style='text-align:right;'>
                  <div style='font-weight:700; color:{PALETTE['primary']};'>{int(row['count']):,}</div>
                  <div style='font-size:0.72rem; color:{PALETTE['muted']};'>{share:.1f}% от старта</div>
                </div></div>""".replace(",", " "),
                unsafe_allow_html=True,
            )


# ============================================================
#                       Когортная heatmap
# ============================================================

st.markdown('<div class="section-title">Когортный анализ — доход по месяцу регистрации</div>', unsafe_allow_html=True)

cohort_basis = "registration"
ct = M.build_cohort_table(orders, basis=cohort_basis)
if not ct.empty and not ads_all.empty:
    cutoff = ads_all["month"].min()
    ct = ct.loc[ct.index >= cutoff]

if ct.empty:
    st.info("Недостаточно данных для когортного анализа.")
else:
    sizes = M.cohort_client_counts(orders, basis=cohort_basis).reindex(ct.index).fillna(0).astype(int)
    z = ct.values
    x = list(ct.columns)
    y = [d.strftime("%b %Y") for d in ct.index]
    # подписи внутри клеток
    text = [[f"{v/1000:.0f}K" if v >= 1000 else (f"{int(v)}" if v > 0 else "") for v in row] for row in z]

    fig = go.Figure(go.Heatmap(
        z=z, x=x, y=y, text=text, texttemplate="%{text}",
        colorscale=[
            [0.0, "#f6f8fa"],
            [0.3, "#bfdbfe"],
            [0.6, "#60a5fa"],
            [1.0, "#1d4ed8"],
        ],
        hovertemplate="<b>Когорта %{y}</b><br>%{x}<br>Доход: %{z:,.0f} ₽<extra></extra>",
        showscale=False,
        textfont=dict(size=11),
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT,
        height=max(280, 38 * len(ct) + 80),
        xaxis_title="Месяц после регистрации",
        yaxis_title="Когорта",
        xaxis_side="top",
        yaxis_autorange="reversed",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Каждая строка — клиенты, зарегистрированные в этом месяце. "
        "Каждый столбец — деньги, которые они принесли через N месяцев после регистрации. "
        "Чем «жирнее» строка вправо — тем выше LTV когорты."
    )


# ============================================================
#         📊 ИСТОЧНИКИ ТРАФИКА (ЯНДЕКС.МЕТРИКА)
# ============================================================
# Дополнительный блок: данные напрямую из Метрики через её API.
# Атрибуция «Последний значимый переход» + кросс-девайс (как
# настроено в web-интерфейсе клиента).
#
# ВАЖНО: данные Метрики оценочные — могут расходиться с реальными
# оплатами в CSV из BILLmanager (двойные хиты целей, реклоустеризация
# визитов). Основа экономики дашборда — всегда CSV; Метрика нужна
# только для атрибуции «откуда пришёл клиент».

try:
    import metrika as MK
    _mk_creds = MK.get_credentials()
except Exception:
    _mk_creds = None
    MK = None

if _mk_creds is not None and MK is not None:
    st.markdown(
        '<div class="section-title">📊 Источники трафика и воронка покупок (из Метрики)</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Данные тянутся напрямую из Яндекс.Метрики. Атрибуция: "
        "**Последний значимый переход** + **кросс-девайс**. "
        "⚠️ Цифры покупок и дохода здесь оценочные (Метрика считает "
        "хиты целей) — реальные оплаты см. в шапке (CSV из BILLmanager)."
    )

    # Кэш — Метрика API не любит частые запросы
    @st.cache_data(ttl=1800, show_spinner=False)
    def _cached_metrika(period: tuple):
        df_from, df_to = period
        summary = MK.fetch_goal_summary(_mk_creds, df_from, df_to)
        funnel  = MK.fetch_funnel(_mk_creds, df_from, df_to)
        sources = MK.fetch_revenue_by_source(_mk_creds, df_from, df_to, limit=15)
        direct  = MK.fetch_revenue_by_direct_campaign(_mk_creds, df_from, df_to, limit=20)
        return summary, funnel, sources, direct

    _mk_period = (d_from.strftime("%Y-%m-%d"), d_to.strftime("%Y-%m-%d"))
    try:
        with st.spinner("📡 Тяну данные из Яндекс.Метрики…"):
            mk_summary, mk_funnel, mk_sources, mk_direct = _cached_metrika(_mk_period)
    except Exception as e:
        st.warning(f"Не удалось получить данные из Метрики: {e}")
        mk_summary = mk_funnel = mk_sources = mk_direct = pd.DataFrame()

    if not mk_summary.empty:
        # ─── KPI: ключевые цели ────────────────────────────────
        by_key = {r["goal_key"]: r for _, r in mk_summary.iterrows()}
        mk_c1, mk_c2, mk_c3, mk_c4 = st.columns(4)
        reg = by_key.get("register", {"users": 0})
        mk_c1.markdown(kpi_card(
            "Регистраций в BM",
            fmt_num(reg["users"]),
            f"{int(reg.get('reaches', 0))} событий за {period_label}",
            kind="primary",
            tooltip="Уникальные пользователи, достигшие цели user_register в Метрике.",
        ), unsafe_allow_html=True)
        cart = by_key.get("add_to_cart", {"users": 0})
        mk_c2.markdown(kpi_card(
            "Добавили в корзину",
            fmt_num(cart["users"]),
            f"уникальных",
            kind="primary",
            tooltip="Уникальные пользователи, добавившие услугу в корзину BILLmanager.",
        ), unsafe_allow_html=True)
        gtp = by_key.get("go_to_pay", {"users": 0})
        mk_c3.markdown(kpi_card(
            "Перешли к оплате",
            fmt_num(gtp["users"]),
            "уникальных",
            kind="primary",
            tooltip="Уникальные пользователи, перешедшие на страницу выбора способа оплаты.",
        ), unsafe_allow_html=True)
        epur = by_key.get("e_purchase", {"users": 0, "revenue": 0})
        mk_c4.markdown(kpi_card(
            "Оплат (Ecommerce)",
            fmt_num(epur["users"]),
            f"оценочный доход {fmt_rub(epur['revenue'])}",
            kind="green",
            tooltip="Покупки по цели e_purchase. Сумма — то, что отправил BILLmanager в Метрику; "
                    "может отличаться от реальных оплат в CSV.",
        ), unsafe_allow_html=True)

        st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)

        # ─── Воронка ──────────────────────────────────────────
        if not mk_funnel.empty:
            mk_col_f, mk_col_t = st.columns([1.2, 1])
            with mk_col_f:
                fig_fn = go.Figure(go.Funnel(
                    y=mk_funnel["stage"].tolist(),
                    x=mk_funnel["users"].tolist(),
                    textposition="inside",
                    textinfo="value+percent initial",
                    marker={"color": [PALETTE["primary"], "#60a5fa", "#3b82f6",
                                      "#1d4ed8", PALETTE["green"]]},
                    connector={"line": {"color": PALETTE["muted"], "width": 1}},
                ))
                fig_fn.update_layout(
                    **{**PLOTLY_LAYOUT, "height": 320,
                       "title": "Воронка: посетитель → оплата (уникальные)"},
                )
                st.plotly_chart(fig_fn, use_container_width=True)
                st.caption(
                    "ℹ️ Цели на разных ступенях считаются независимо (через атрибуцию "
                    "«Последний значимый переход») — поэтому числа могут не строго "
                    "убывать. Это нормально для Метрики."
                )

            # ─── Источники трафика → доход ────────────────────
            with mk_col_t:
                if not mk_sources.empty:
                    st.markdown("**Доход (Метрика) по источникам — топ 15**")
                    src_show = mk_sources.copy()
                    src_show.columns = ["Источник", "Доход, ₽", "Покупок", "Визитов"]
                    st.dataframe(
                        src_show, use_container_width=True, hide_index=True, height=350,
                        column_config={
                            "Доход, ₽": st.column_config.NumberColumn(format="%.0f"),
                            "Покупок":  st.column_config.NumberColumn(format="%d"),
                            "Визитов":  st.column_config.NumberColumn(format="%d"),
                        },
                    )

        # ─── Я.Директ — какие кампании приносят покупки ───────
        if not mk_direct.empty:
            st.markdown(
                "**Я.Директ: какие кампании реально приносят покупки** "
                "(только визиты с платной рекламы)"
            )
            d_show = mk_direct.copy()
            d_show["avg_check"] = (d_show["revenue"] / d_show["purchases"].replace(0, pd.NA)).fillna(0)
            d_show = d_show.rename(columns={
                "campaign":  "Кампания",
                "revenue":   "Доход, ₽",
                "purchases": "Покупок",
                "visits":    "Визитов",
                "avg_check": "Ср. чек, ₽",
            })
            st.dataframe(
                d_show, use_container_width=True, hide_index=True,
                column_config={
                    "Доход, ₽":   st.column_config.NumberColumn(format="%.0f"),
                    "Покупок":    st.column_config.NumberColumn(format="%d"),
                    "Визитов":    st.column_config.NumberColumn(format="%d"),
                    "Ср. чек, ₽": st.column_config.NumberColumn(format="%.0f"),
                },
            )
            total_direct_rev = float(d_show["Доход, ₽"].sum())
            total_direct_purch = int(d_show["Покупок"].sum())
            st.caption(
                f"💡 Всего Я.Директ принёс **{total_direct_purch} покупок** на "
                f"**{fmt_rub(total_direct_rev)}** по атрибуции «Последний значимый "
                f"переход». Это **прямой вклад рекламы** — повторные визиты "
                f"клиентов уже не учитываются здесь."
            )
else:
    # Креды Метрики не настроены — короткая подсказка
    with st.expander("📊 Подключить Я.Метрику для атрибуции источников"):
        st.markdown(
            "Чтобы дашборд показывал «откуда приходят клиенты» прямо из "
            "Метрики, добавьте в **Streamlit Secrets**:\n\n"
            "```toml\n"
            'METRIKA_TOKEN = "y0_AgAAAA..."\n'
            "METRIKA_COUNTER_ID = 102931802\n"
            "```\n\n"
            "Токен — на oauth.yandex.ru → создать приложение со scope "
            "`metrika:read`. Counter ID — в metrika.yandex.ru сверху страницы счётчика."
        )


# ============================================================
#         🎯 ДОЛГОСРОЧНАЯ ОКУПАЕМОСТЬ РЕКЛАМЫ
# ============================================================
# То чего НЕТ в Я.Директе и Метрике: связка «рекламный рубль ↔ платежи
# клиента через 1, 3, 6, 12 месяцев». Главная фишка дашборда — видеть,
# как реклама окупается за счёт повторных оплат на длинном горизонте.

pb_df = M.cohort_payback(orders_all, ads_all)

if not pb_df.empty and "ad_spend" in pb_df.columns:
    # «Вложено» считаем по ВСЕМ месяцам с расходом — даже если из них ещё
    # не пришло платящих клиентов. Иначе hero показывает 13.06 млн при
    # реальном расходе 13.82 млн в шапке (760к «теряются»).
    pb_with_spend = pb_df[pb_df["ad_spend"] > 0].copy()
    # Для кривой возврата, таблицы break-even и эры-сравнения — только
    # настоящие когорты (с клиентами), иначе деление на 0 и шум в графике.
    pb = pb_df[(pb_df["ad_spend"] > 0) & (pb_df["clients"] > 0)].copy()

    if not pb_with_spend.empty:
        st.markdown(
            '<div class="section-title">🎯 Долгосрочная окупаемость рекламы</div>',
            unsafe_allow_html=True,
        )

        rev_cols = sorted(
            [c for c in pb.columns if c.startswith("cum_M+")],
            key=lambda c: int(c.replace("cum_M+", "")),
        )
        max_horizon = max(int(c.replace("cum_M+", "")) for c in rev_cols) if rev_cols else 0

        # ─── Hero: ключевая цифра окупаемости ──────────────────
        # Вложено = весь расход на Директ (= шапка). Вернулось = деньги,
        # реально пришедшие от когорт с клиентами (без когорт нечему возвращаться).
        total_spend_all = float(pb_with_spend["ad_spend"].sum())
        spend_without_cohorts = float(
            pb_with_spend.loc[pb_with_spend["clients"] == 0, "ad_spend"].sum()
        )
        latest_col = rev_cols[-1] if rev_cols else None
        # Кумулятив возврата на текущий момент (последний наблюдаемый M+N для каждой когорты)
        observed_return = float(
            sum(row[rev_cols].max() if not pd.isna(row[rev_cols].max()) else 0
                for _, row in pb.iterrows())
        ) if not pb.empty and rev_cols else 0.0
        return_pct = (observed_return / total_spend_all * 100) if total_spend_all else 0
        # Сколько когорт уже окупились (payback_month <= max_horizon)
        cohorts_paid = int((pb["payback_month"].notna() & (pb["payback_month"] >= 0)).sum()) if not pb.empty else 0
        cohorts_total = int(len(pb))
        # Среднее число месяцев до окупаемости (только по окупившимся когортам)
        avg_payback_m = pb["payback_month"].dropna()
        avg_payback_m = avg_payback_m[avg_payback_m >= 0]
        avg_payback_label = (
            f"{avg_payback_m.mean():.1f} мес" if not avg_payback_m.empty else "ещё не окупились"
        )

        hero_kind = "green" if return_pct >= 100 else "orange" if return_pct >= 50 else "red"

        # Поясняем расхождения: (1) общий доход в шапке включает «старых»
        # клиентов, пришедших до начала рекламы — они не считаются возвратом
        # рекламного бюджета. (2) часть расхода ушла в месяцы без новых
        # платящих клиентов — это «бюджет в работе» (свежие месяцы, где
        # клиенты могут ещё дозреть) или прямой waste.
        _hero_notes = []
        if spend_without_cohorts > 0:
            _hero_notes.append(
                f"<b>{fmt_rub(spend_without_cohorts)}</b> расхода ещё не дали "
                f"платящих клиентов (свежие месяцы / waste)"
            )
        _hero_notes.append(
            "«Вернулось» считается только по клиентам, которые впервые "
            "зарегистрировались в месяцы с расходом на Директ — без двойного "
            "счёта старых клиентов"
        )
        _hero_notes_html = " · ".join(_hero_notes)

        st.markdown(
            f"""
            <div class="kpi-hero {hero_kind}">
              <div class="kpi-hero-main">
                <div class="kpi-hero-label">Возврат рекламного бюджета на сегодня</div>
                <div class="kpi-hero-value">{return_pct:.1f}%</div>
                <div class="kpi-hero-sub">
                  Из <b>{fmt_rub(total_spend_all)}</b> расхода на Директ
                  клиенты уже вернули <b>{fmt_rub(observed_return)}</b>.
                  Окупилось когорт: <b>{cohorts_paid} из {cohorts_total}</b>,
                  среднее время окупаемости: <b>{avg_payback_label}</b>.
                  <div style="margin-top:0.4rem; font-size:0.78rem; color:#57606a;">
                    ℹ️ {_hero_notes_html}.
                  </div>
                </div>
              </div>
              <div class="kpi-hero-breakdown">
                <div class="kpi-hero-bd-item">
                  <div class="kpi-hero-bd-label">Вложено</div>
                  <div class="kpi-hero-bd-value" style="color:{PALETTE['red']};">{fmt_rub(total_spend_all)}</div>
                </div>
                <div class="kpi-hero-bd-item">
                  <div class="kpi-hero-bd-label">Вернулось</div>
                  <div class="kpi-hero-bd-value" style="color:{PALETTE['green']};">{fmt_rub(observed_return)}</div>
                </div>
                <div class="kpi-hero-bd-item">
                  <div class="kpi-hero-bd-label">Когорт окупилось</div>
                  <div class="kpi-hero-bd-value">{cohorts_paid} / {cohorts_total}</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Дальше — кривая и таблица по реальным когортам с клиентами.
        # Если расход уже был, но клиенты ещё не появились — выходим
        # (hero уже показан, остальное считать не из чего).
        if pb.empty or not rev_cols:
            st.info(
                "📭 По текущим месяцам с расходом ещё нет платящих клиентов в "
                "когортах — кривая окупаемости появится, когда клиенты сделают "
                "первые оплаты."
            )
            st.stop()

        # ─── Payback Curve: средний % возврата по горизонту ────
        st.markdown(
            '<div class="section-title">Кривая окупаемости — 1 ₽ в Директе возвращается N₽ за M мес</div>',
            unsafe_allow_html=True,
        )

        # Для каждого M+k считаем средний % возврата по тем когортам, у которых есть данные на M+k
        curve_rows = []
        for c in rev_cols:
            k = int(c.replace("cum_M+", ""))
            ratios = pb[c] / pb["ad_spend"]
            ratios = ratios.replace([float("inf"), float("-inf")], pd.NA).dropna()
            if not ratios.empty:
                curve_rows.append({
                    "month": k,
                    "avg_return_ratio": float(ratios.mean()),
                    "median_return_ratio": float(ratios.median()),
                    "cohorts_count": int(ratios.shape[0]),
                })
        curve = pd.DataFrame(curve_rows)

        if not curve.empty:
            fig_pc = go.Figure()
            fig_pc.add_trace(go.Scatter(
                x=curve["month"], y=curve["avg_return_ratio"] * 100,
                mode="lines+markers",
                name="Средний возврат, %",
                line=dict(color=PALETTE["green"], width=3),
                marker=dict(size=8),
                hovertemplate="M+%{x}<br>Вернулось: %{y:.1f}% от вложенного<extra></extra>",
                fill="tozeroy", fillcolor="rgba(26, 127, 55, 0.10)",
            ))
            fig_pc.add_trace(go.Scatter(
                x=curve["month"], y=curve["median_return_ratio"] * 100,
                mode="lines",
                name="Медиана",
                line=dict(color=PALETTE["primary"], width=1, dash="dot"),
                hovertemplate="M+%{x}<br>Медиана: %{y:.1f}%<extra></extra>",
            ))
            # Линия break-even = 100%
            fig_pc.add_hline(
                y=100, line_dash="dash", line_color=PALETTE["muted"],
                annotation_text="Окупаемость = 100%",
                annotation_position="top right",
            )
            fig_pc.update_layout(
                **{**PLOTLY_LAYOUT, "height": 360},
                xaxis_title="Месяцев с момента регистрации клиента",
                yaxis_title="Накопленный возврат, % от расхода",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            )
            st.plotly_chart(fig_pc, use_container_width=True)
            st.caption(
                "Берём каждую когорту, считаем сколько вернулось от потраченного на её "
                "привлечение к месяцу M+k, и усредняем по всем когортам. Пересечение "
                "линии 100% = break-even. Чем дальше кривая уходит за 100% — тем выгоднее реклама."
            )

        # ─── Break-even таблица по когортам ────────────────────
        st.markdown(
            '<div class="section-title">Окупаемость по когортам — кто когда вышел в плюс</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Когорта = клиенты, впервые пришедшие в конкретный месяц. "
            "Колонки показывают **накопленный возврат от расхода** на эту когорту: "
            "«В мес рег.» — что вернули в тот же месяц регистрации, "
            "«За 3 мес» — что вернули за 3 месяца с момента регистрации, и т.д. "
            "100% = когорта окупила себя полностью."
        )

        # Фильтр-переключатель: все vs проблемные
        be_filter = st.radio(
            "Показать",
            ["Все когорты", "Только не окупившиеся", "Проблемные (возврат за 6 мес < 30%)"],
            horizontal=True, key="be_table_filter",
        )

        be_show = pb.reset_index()
        # Колонки для таблицы: ключевые M+ горизонты
        key_horizons = [k for k in (0, 1, 3, 6, 12) if f"cum_M+{k}" in be_show.columns]
        # Считаем коэффициенты return_M+k = cum_M+k / ad_spend
        for k in key_horizons:
            be_show[f"return_m{k}"] = be_show[f"cum_M+{k}"] / be_show["ad_spend"] * 100

        be_show["cohort_label"] = be_show.iloc[:, 0].apply(
            lambda d: fmt_month_ru(d, "short_year")
        )

        # ─── Топ-кампания месяца (по расходу) ─────────────────
        # В CSV нет источника трафика per клиент → точно сказать «откуда
        # пришёл этот клиент» нельзя. Но можно показать, какая кампания
        # была главной по расходу в месяц регистрации когорты — это даёт
        # контекст «вот этот месяц был драйверным для кампании X».
        top_camp_map = {}
        if not ads_all.empty and "campaign" in ads_all.columns:
            _spend_by_mc = (ads_all.groupby(["month", "campaign"])["spend_rub"]
                            .sum().reset_index())
            for m in be_show.iloc[:, 0]:
                _slice = _spend_by_mc[_spend_by_mc["month"] == m]
                if not _slice.empty:
                    _top = _slice.nlargest(1, "spend_rub").iloc[0]
                    _share = _top["spend_rub"] / _slice["spend_rub"].sum() * 100
                    top_camp_map[m] = f"{_top['campaign'][:35]} ({_share:.0f}%)"
        be_show["top_campaign"] = be_show.iloc[:, 0].map(top_camp_map).fillna("—")

        # Применяем фильтр
        if be_filter == "Только не окупившиеся":
            be_show = be_show[be_show["payback_month"].isna()]
        elif be_filter == "Проблемные (возврат за 6 мес < 30%)" and "return_m6" in be_show.columns:
            be_show = be_show[(be_show["return_m6"].fillna(0) < 30)
                              & (be_show["clients"] > 0)]

        if be_show.empty:
            st.success("✅ Нет когорт под этот фильтр — все когорты в норме.")
        else:
            # Заголовки человеко-понятные вместо M+0/M+1/etc
            horizon_label = {
                0: "В мес рег.",
                1: "За 1 мес",
                3: "За 3 мес",
                6: "За 6 мес",
                12: "За 12 мес",
            }
            horizon_help = {
                0: "Сколько % от рекламного расхода эта когорта вернула в свой первый месяц.",
                1: "Накопленный % возврата к концу 1-го месяца после регистрации.",
                3: "Накопленный % возврата за 3 месяца с момента регистрации.",
                6: "Накопленный % возврата за полгода. Главный ориентир для хостинга.",
                12: "Накопленный % возврата за год. Если ≥100% — реклама окупается за год.",
            }

            # Финальная таблица
            cols_order = ["cohort_label", "top_campaign", "clients", "ad_spend", "cac"]
            cols_rename = {
                "cohort_label": "Когорта",
                "top_campaign": "Главная кампания месяца",
                "clients": "Клиентов",
                "ad_spend": "Расход, ₽",
                "cac": "CAC, ₽",
            }
            for k in key_horizons:
                cols_order.append(f"return_m{k}")
                cols_rename[f"return_m{k}"] = horizon_label.get(k, f"M+{k}")
            cols_order.append("payback_month")
            cols_rename["payback_month"] = "Окупилось через"

            be_table = be_show[cols_order].rename(columns=cols_rename)

            column_config = {
                "Главная кампания месяца": st.column_config.TextColumn(
                    help="Кампания с наибольшим расходом в этот месяц (и её доля). "
                         "В CSV нет связки клиент→кампания, поэтому это контекст, "
                         "а не точное распределение клиентов."
                ),
                "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "CAC, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Клиентов": st.column_config.NumberColumn(format="%d"),
                "Окупилось через": st.column_config.NumberColumn(
                    format="%.0f мес",
                    help="Через сколько месяцев накопленный доход когорты "
                         "перекрыл расход на её привлечение. Пусто = ещё не окупилась."
                ),
            }
            for k in key_horizons:
                column_config[horizon_label.get(k, f"M+{k}")] = st.column_config.ProgressColumn(
                    format="%.0f%%", min_value=0, max_value=200,
                    help=horizon_help.get(k, f"Накопленный возврат к месяцу M+{k}"),
                )

            st.dataframe(
                be_table, use_container_width=True, hide_index=True,
                column_config=column_config,
            )

        # ─── Инсайт: сравнение «эры» — старый vs новый аккаунт ─
        # В контексте проекта: в ноябре 2025 запустили «новый» аккаунт Я.Директа,
        # CAC рухнул в 8×. Покажем явное сравнение.
        cutoff = pd.Timestamp("2025-11-01")
        pb_idx_dt = pd.to_datetime(pb.index)
        old_era = pb[pb_idx_dt < cutoff]
        new_era = pb[pb_idx_dt >= cutoff]

        if not old_era.empty and not new_era.empty:
            def _era_avg_payback(df):
                payback = df["payback_month"].dropna()
                payback = payback[payback >= 0]
                return payback.mean() if not payback.empty else None

            def _era_cac(df):
                if df["clients"].sum() > 0:
                    return df["ad_spend"].sum() / df["clients"].sum()
                return None

            old_cac = _era_cac(old_era)
            new_cac = _era_cac(new_era)
            old_pb_avg = _era_avg_payback(old_era)
            new_pb_avg = _era_avg_payback(new_era)

            st.markdown(
                '<div class="section-title">Сравнение эр Я.Директа: до ноября 2025 vs после</div>',
                unsafe_allow_html=True,
            )

            ec1, ec2 = st.columns(2)
            ec1.markdown(kpi_card(
                "Старый аккаунт (до 11.2025)",
                f"CAC {fmt_rub(old_cac) if old_cac else '—'}",
                f"{int(old_era['clients'].sum())} клиентов · "
                f"окупаемость {old_pb_avg:.1f} мес" if old_pb_avg else f"{int(old_era['clients'].sum())} клиентов · не окупились",
                kind="red",
                tooltip="Когорты до ноября 2025 — эра «старого аккаунта Директа» с высоким CPC и низким CTR.",
            ), unsafe_allow_html=True)
            ec2.markdown(kpi_card(
                "Новый аккаунт (с 11.2025)",
                f"CAC {fmt_rub(new_cac) if new_cac else '—'}",
                f"{int(new_era['clients'].sum())} клиентов · "
                f"окупаемость {new_pb_avg:.1f} мес" if new_pb_avg else f"{int(new_era['clients'].sum())} клиентов · ещё мало данных",
                kind="green",
                tooltip="Когорты с ноября 2025 — новый аккаунт Директа с принципиально другой экономикой.",
            ), unsafe_allow_html=True)

            if old_cac and new_cac and old_cac > 0:
                ratio = old_cac / new_cac
                st.caption(
                    f"💡 Новый аккаунт привлекает клиента в <b>{ratio:.1f}× дешевле</b> старого "
                    f"({fmt_rub(old_cac)} → {fmt_rub(new_cac)}). Это ключевой драйвер ROMI: "
                    f"при том же бюджете клиентов привлекается в {ratio:.1f} раза больше.",
                    unsafe_allow_html=True,
                )

        # ─── Прогноз окупаемости на 12 мес ─────────────────────
        # Используем cohort_ltv_forecast (есть в metrics.py): прогноз
        # кумулятивного дохода per client на M+12. Для каждой когорты
        # считаем «остаточный доход» = forecast_M12 - max_observed_revenue.
        # Суммируем по всем когортам → сколько ещё принесут уже
        # привлечённые клиенты в ближайшие 12 мес.

        fc = M.cohort_ltv_forecast(orders_all, horizon_months=12)
        if not fc.empty:
            # current = max observed revenue per client для каждой когорты
            cohort_rev_obs = M.build_cohort_table(orders_all, basis="registration")
            sizes_obs = M.cohort_client_counts(orders_all, basis="registration")

            # Кумулятив фактического дохода / клиент
            cum_obs = cohort_rev_obs.cumsum(axis=1)
            rev_per_client_obs = cum_obs.div(sizes_obs.reindex(cum_obs.index).replace(0, pd.NA), axis=0)
            # Максимум наблюдаемого LTV per client для каждой когорты
            current_ltv = rev_per_client_obs.max(axis=1).fillna(0)
            # Прогноз LTV per client на M+12
            forecast_m12 = fc.iloc[:, -1] if not fc.empty else pd.Series(dtype=float)
            # Общие клиенты в каждой когорте (только те, что в pb — у нас есть и расход)
            clients_in_pb = pb["clients"]
            # Остаточный LTV per cohort = (forecast_M12 - current) × clients
            common_idx = clients_in_pb.index.intersection(forecast_m12.index)
            residual_per_client = (forecast_m12.reindex(common_idx) - current_ltv.reindex(common_idx)).clip(lower=0)
            residual_total = float((residual_per_client * clients_in_pb.reindex(common_idx)).sum())

            # Общий прогнозный возврат через 12 мес = текущий возврат + остаточный
            forecast_total_return = observed_return + residual_total
            forecast_return_pct = (forecast_total_return / total_spend_all * 100) if total_spend_all else 0

            st.markdown(
                '<div class="section-title">Прогноз окупаемости на 12 месяцев</div>',
                unsafe_allow_html=True,
            )

            fc_col1, fc_col2, fc_col3 = st.columns(3)
            fc_col1.markdown(kpi_card(
                "Остаточный LTV",
                fmt_rub(residual_total),
                f"уже привлечённые клиенты принесут в ближайшие 12 мес",
                kind="green",
                tooltip="Прогноз: сколько ещё денег принесут клиенты, уже привлечённые на сегодня, за следующие 12 месяцев. Считается как (прогноз LTV на M+12 минус то, что уже получили) × клиенты в когорте.",
            ), unsafe_allow_html=True)
            forecast_kind = "green" if forecast_return_pct >= 100 else "orange" if forecast_return_pct >= 50 else "red"
            fc_col2.markdown(kpi_card(
                "Полная окупаемость через 12 мес",
                f"{forecast_return_pct:.1f}%",
                f"{fmt_rub(forecast_total_return)} из {fmt_rub(total_spend_all)} вложенного",
                kind=forecast_kind,
                tooltip="С учётом прогнозируемого остаточного дохода: текущий возврат + остаточный = общий ожидаемый возврат на горизонте 12 месяцев.",
            ), unsafe_allow_html=True)
            # Среднее по новой эре — самый чистый ориентир
            new_era_pb = pb[pd.to_datetime(pb.index) >= cutoff] if 'cutoff' in dir() else pd.DataFrame()
            if not new_era_pb.empty:
                ne_residual_idx = new_era_pb.index.intersection(forecast_m12.index)
                ne_residual = float(
                    ((forecast_m12.reindex(ne_residual_idx) - current_ltv.reindex(ne_residual_idx)).clip(lower=0)
                     * new_era_pb["clients"].reindex(ne_residual_idx)).sum()
                )
                ne_observed = float(
                    sum(row[rev_cols].max() if not pd.isna(row[rev_cols].max()) else 0
                        for _, row in new_era_pb.iterrows())
                )
                ne_spend = float(new_era_pb["ad_spend"].sum())
                ne_total = ne_observed + ne_residual
                ne_pct = (ne_total / ne_spend * 100) if ne_spend else 0
                ne_kind = "green" if ne_pct >= 100 else "orange" if ne_pct >= 50 else "red"
                fc_col3.markdown(kpi_card(
                    "Только новый аккаунт",
                    f"{ne_pct:.1f}%",
                    f"прогноз ROMI на 12 мес (с 11.2025)",
                    kind=ne_kind,
                    tooltip="То же самое, но только для новой эры Я.Директа (с ноября 2025). Это релевантный прогноз — на каких параметрах сейчас работает реклама.",
                ), unsafe_allow_html=True)

            # ─── Таблица break-even forecast для неокупившихся когорт ─
            # Новая модель: используем M.cohort_ltv_forecast (наблюдаемая
            # динамика + decay 0.9 в месяц) для прогноза до M+24. Для каждой
            # неокупившейся когорты ищем первый месяц, когда прогнозируемый
            # LTV per client × число клиентов догонит расход на привлечение.
            forecast_long = M.cohort_ltv_forecast(orders_all, horizon_months=24)

            not_paid_back = pb[pb["payback_month"].isna()].copy()
            if not not_paid_back.empty and not forecast_long.empty:
                forecast_be = []
                for idx, row in not_paid_back.iterrows():
                    spend = row["ad_spend"]
                    clients = row["clients"]
                    if spend <= 0 or clients <= 0 or idx not in forecast_long.index:
                        continue

                    target_per_client = spend / clients
                    fc_row = forecast_long.loc[idx]

                    # Текущий % возврата = max наблюдаемый
                    observed_max = max(
                        (row[c] / spend * 100 for c in rev_cols if not pd.isna(row[c])),
                        default=0,
                    )

                    # Ищем первый M+k где прогноз LTV per client достигает target
                    forecast_month = None
                    for col in fc_row.index:
                        if not col.startswith("M+"):
                            continue
                        k = int(col.replace("M+", ""))
                        ltv_pc = fc_row[col]
                        if pd.notna(ltv_pc) and ltv_pc >= target_per_client:
                            forecast_month = k
                            break

                    # Последний наблюдаемый M для расчёта «через сколько мес отсюда»
                    last_observed = max(
                        (int(c.replace("cum_M+", "")) for c in rev_cols
                         if not pd.isna(row[c]) and row[c] > 0),
                        default=0,
                    )

                    if forecast_month is None:
                        verdict = "⚠️ Не окупится за 24 мес — нужно ускорять привлечение"
                    elif forecast_month <= last_observed:
                        # На какой-то итерации forecast достиг target — но это
                        # ретроспективное предсказание, на практике уже наблюдалось
                        verdict = f"✅ Окупится в ближайший месяц (M+{forecast_month})"
                    else:
                        months_ahead = forecast_month - last_observed
                        if forecast_month <= 12:
                            verdict = f"✅ Через ~{months_ahead} мес (всего M+{forecast_month})"
                        elif forecast_month <= 18:
                            verdict = f"🟢 Через ~{months_ahead} мес (всего M+{forecast_month})"
                        else:
                            verdict = f"⚠️ Через ~{months_ahead} мес (всего M+{forecast_month})"

                    forecast_be.append({
                        "cohort": idx,
                        "current_pct": observed_max,
                        "forecast_month": forecast_month,
                        "verdict": verdict,
                    })

                if forecast_be:
                    fc_df = pd.DataFrame(forecast_be)
                    fc_df["Когорта"] = fc_df["cohort"].apply(lambda d: fmt_month_ru(d, "short_year"))
                    fc_df["Сейчас вернулось, %"] = fc_df["current_pct"].round(1)
                    fc_df["Прогноз окупаемости"] = fc_df["verdict"]
                    fc_df_show = fc_df[["Когорта", "Сейчас вернулось, %", "Прогноз окупаемости"]]
                    st.markdown(
                        '<div style="margin-top: 0.6rem; color:#57606a; font-size:0.85rem;">'
                        '<b>Когорты, которые ещё не вышли в плюс</b> — прогноз через '
                        '<code>cohort_ltv_forecast</code> (наблюдаемая динамика на клиента '
                        '+ декай 0.9 в месяц на горизонте 24 мес).'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                    st.dataframe(
                        fc_df_show, use_container_width=True, hide_index=True,
                        column_config={
                            "Сейчас вернулось, %": st.column_config.ProgressColumn(
                                format="%.1f%%", min_value=0, max_value=100,
                            ),
                        },
                    )

            st.caption(
                "📊 Прогноз остаточного LTV использует модель `cohort_ltv_forecast`: "
                "наблюдаемая динамика доходов на клиента + экстраполяция «хвоста» "
                "с decay 0.9 в месяц. Это **нижняя граница** — реальный LTV хостинга "
                "обычно выше за счёт ежегодных продлений (всплеск на M+12), которого "
                "линейная модель не видит."
            )


# ============================================================
#                       Детали (свёрнутые)
# ============================================================

st.markdown('<div class="section-title">Детали</div>', unsafe_allow_html=True)

with st.expander("📅 Помесячная таблица: расход, доход, новые, CAC, ROMI"):
    if not ms.empty:
        ms_show = ms.copy()
        ms_show["month_label"] = ms_show["month"].dt.strftime("%b %Y")
        st.dataframe(
            ms_show[["month_label", "spend", "revenue", "new_clients",
                     "revenue_from_new", "cac", "romi", "m0_payback_ratio"]]
              .rename(columns={
                  "month_label": "Месяц",
                  "spend": "Расход, ₽",
                  "revenue": "Доход, ₽",
                  "new_clients": "Новых",
                  "revenue_from_new": "Доход от новых M+0, ₽",
                  "cac": "CAC, ₽",
                  "romi": "ROMI",
                  "m0_payback_ratio": "Окуп. M+0",
              }),
            use_container_width=True, hide_index=True,
            column_config={
                "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Доход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Доход от новых M+0, ₽": st.column_config.NumberColumn(format="%.0f"),
                "CAC, ₽": st.column_config.NumberColumn(format="%.0f"),
                "ROMI": st.column_config.NumberColumn(format="%.1f%%"),
                "Окуп. M+0": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

with st.expander("📢 Расход по кампаниям"):
    cb = M.campaign_breakdown(ads)
    if not cb.empty:
        st.dataframe(
            cb.rename(columns={
                "campaign": "Кампания",
                "spend": "Расход, ₽",
                "months_active": "Месяцев",
                "share": "Доля",
            }),
            use_container_width=True, hide_index=True,
            column_config={
                "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Доля": st.column_config.NumberColumn(format="%.2f%%"),
            }
        )

with st.expander("🌍 По локациям серверов"):
    loc = M.product_mix(orders, by="product_location")
    if not loc.empty:
        st.dataframe(
            loc.rename(columns={
                "product_location": "Локация",
                "orders": "Заказов",
                "revenue": "Доход, ₽",
                "clients": "Клиентов",
                "avg_check": "Средний чек, ₽",
                "share": "Доля",
            }),
            use_container_width=True, hide_index=True,
            column_config={
                "Доход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Средний чек, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Доля": st.column_config.NumberColumn(format="%.2f%%"),
            }
        )

with st.expander("📊 Распределение чеков и сезонность"):
    col_a, col_b = st.columns(2)

    with col_a:
        cd = M.check_distribution(orders)
        if not cd.empty:
            fig_cd = go.Figure(go.Bar(
                x=cd["bin_label"], y=cd["count"],
                marker_color=PALETTE["primary"], opacity=0.85,
                hovertemplate="Чек: %{x} ₽<br>Оплат: %{y}<extra></extra>",
            ))
            fig_cd.update_layout(
                **PLOTLY_LAYOUT, height=290,
                title="Распределение по сумме чека",
                xaxis_tickangle=-35,
                showlegend=False,
            )
            st.plotly_chart(fig_cd, use_container_width=True)

    with col_b:
        sw = M.seasonality_weekday(orders)
        if not sw.empty:
            fig_sw = go.Figure(go.Bar(
                x=sw["weekday_label"], y=sw["revenue"],
                marker_color=PALETTE["green"], opacity=0.85,
                hovertemplate="%{x}<br>Доход: %{y:,.0f} ₽<extra></extra>",
            ))
            fig_sw.update_layout(
                **PLOTLY_LAYOUT, height=290,
                title="Доход по дню недели",
                showlegend=False,
            )
            st.plotly_chart(fig_sw, use_container_width=True)

with st.expander("📈 Прогноз LTV когорт"):
    fc = M.cohort_ltv_forecast(orders, horizon_months=12)
    if not fc.empty:
        cutoff = ads_all["month"].min() if not ads_all.empty else fc.index.min()
        fc_show = fc.loc[fc.index >= cutoff].copy()
        fc_show.index = fc_show.index.strftime("%b %Y")
        fc_show.index.name = "Когорта"
        st.caption(
            "Накопленный доход на одного клиента когорты, прогноз на 12 месяцев "
            "(простая экстраполяция с decay 0.9). По мере накопления данных прогноз становится точнее."
        )
        st.dataframe(
            fc_show.iloc[:, :13],
            use_container_width=True,
            column_config={c: st.column_config.NumberColumn(format="%.0f ₽") for c in fc_show.columns[:13]},
        )

with st.expander("⚠️ Клиенты под риском · вернуть пока не поздно"):
    risk_df = M.churn_analysis(orders)
    if not risk_df.empty:
        risk_only = risk_df[risk_df["segment"] == "Под риском"].copy()
        if risk_only.empty:
            st.success("Клиентов под риском нет — все активные.")
        else:
            risk_only["first_payment"] = risk_only["first_payment"].dt.date
            risk_only["last_payment"] = risk_only["last_payment"].dt.date
            st.dataframe(
                risk_only.rename(columns={
                    "client_key": "Клиент (email)",
                    "client_name": "Имя",
                    "first_payment": "Первая оплата",
                    "last_payment": "Последняя оплата",
                    "days_since_last": "Дней без оплат",
                    "orders": "Оплат всего",
                    "total_paid": "Принёс, ₽",
                })[["Клиент (email)", "Имя", "Последняя оплата",
                    "Дней без оплат", "Оплат всего", "Принёс, ₽"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "Принёс, ₽": st.column_config.NumberColumn(format="%.0f"),
                },
            )
            st.caption(
                f"💡 **{len(risk_only)} клиентов** под риском оттока. "
                f"Их совокупная LTV — **{fmt_rub(risk_only['total_paid'].sum())}**. "
                f"Свяжитесь с ними скидкой/звонком до того, как они уйдут в отток (> 90 дней)."
            )

with st.expander("⭐ Pareto-сегмент A · приоритетные клиенты"):
    par_df = M.pareto_segmentation(orders)
    if not par_df.empty:
        a_clients = par_df[par_df["segment"] == "A"].copy()
        st.caption(
            f"Эти {len(a_clients)} клиентов формируют ~80% всей выручки. "
            f"С ними нужно работать в первую очередь."
        )
        st.dataframe(
            a_clients[["client_key", "client_name", "orders", "total_paid", "cum_share"]]
              .rename(columns={
                  "client_key": "Клиент (email)",
                  "client_name": "Имя",
                  "orders": "Оплат",
                  "total_paid": "Принёс, ₽",
                  "cum_share": "Кумулятивная доля",
              }),
            use_container_width=True, hide_index=True,
            column_config={
                "Принёс, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Кумулятивная доля": st.column_config.ProgressColumn(
                    format="%.1f%%", min_value=0, max_value=1
                ),
            },
        )

with st.expander("📥 Скачать данные периода"):
    if not orders.empty:
        paid_out = orders[orders["is_paid"]][[
            "order_id", "payment_date", "registration_date", "new_or_old",
            "client_name", "email", "product", "product_family", "product_location",
            "payment_amount", "purchase_amount_rub",
        ]].copy()
        paid_out["payment_date"] = paid_out["payment_date"].dt.date
        paid_out["registration_date"] = paid_out["registration_date"].dt.date
        st.download_button(
            "⬇️ Оплаты в периоде (CSV)",
            data=paid_out.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"ufo_orders_{d_from:%Y%m%d}_{d_to:%Y%m%d}.csv",
            mime="text/csv",
        )


# ============================================================
#                       Footer
# ============================================================

ctx_full = _cached_compute_kpi(orders, ads)
st.markdown(
    f'<div class="ufo-footer">'
    f'Контекст всего периода: расход {fmt_rub(ctx_full.spend)} · '
    f'доход {fmt_rub(ctx_full.revenue)} · '
    f'gap покупка→оплата {ctx_full.payment_to_purchase_gap*100:.1f}%'
    f'</div>',
    unsafe_allow_html=True,
)

# Скрываем прогресс-бар когда страница полностью отрисована.
_progress_done()
