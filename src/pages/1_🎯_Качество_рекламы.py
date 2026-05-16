"""
Страница «Качество рекламы» — детальная аналитика по Яндекс.Директу.

Только для маркетинга: CTR, CPC, конверсии-цели Метрики, ключевики, объявления.
Главный «Дашборд окупаемости» (для руководителя) — на родительской странице.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="UFO Hosting · Качество рекламы",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Импорты общих helpers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _shared import (
    PALETTE, PLOTLY_LAYOUT,
    fmt_rub, fmt_num, plural_ru,
    kpi_card,
    check_password, apply_base_styles,
    load_quality_cache, save_quality_cache,
    render_cache_reset_button,
)
from yandex_direct import get_credentials as yd_creds


# ─── Password gate ────────────────────────────────────────────
if not check_password():
    st.stop()


# ─── Стили ────────────────────────────────────────────────────
apply_base_styles()


# ─── Hero ─────────────────────────────────────────────────────
st.markdown(
    """
    <div style="padding: 0.2rem 0 1rem;">
      <h1 style="margin:0; font-size:1.65rem; letter-spacing:-0.4px;">🎯 Качество рекламы</h1>
      <div style="color:#57606a; font-size:0.85rem; margin-top:0.3rem;">
        Яндекс.Директ · CTR · CPC · конверсии-цели · ключевики · объявления
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ─── Sidebar: синхронизация качества ──────────────────────────
with st.sidebar:
    st.markdown("### 🎯 Аналитика рекламы")
    st.caption("Для маркетинга. Главный дашборд → в навигации выше.")
    st.divider()

    _yd_creds_global = yd_creds()
    if not _yd_creds_global:
        st.warning(
            "API Яндекс.Директа не подключён. "
            "Добавьте `YANDEX_DIRECT_TOKEN` в Secrets.",
            icon="🔑",
        )
    else:
        st.caption(
            "Кэширует CTR/CPC/конверсии по кампаниям, ключевикам и "
            "объявлениям. Не запрашивает повторно."
        )
        q_from = st.date_input(
            "С даты",
            value=pd.Timestamp.today() - pd.Timedelta(days=90),
            key="yd_quality_from",
            format="DD.MM.YYYY",
        )
        q_to = st.date_input(
            "По дату",
            value=pd.Timestamp.today(),
            key="yd_quality_to",
            format="DD.MM.YYYY",
        )

        if st.button("Подтянуть качество",
                     use_container_width=True, type="primary",
                     key="yd_quality_sync"):
            try:
                from yandex_direct import (
                    DirectCredentials,
                    fetch_campaign_quality, fetch_keyword_report, fetch_ad_report,
                )
                creds_q = DirectCredentials(
                    token=_yd_creds_global.token,
                    client_login=_yd_creds_global.client_login,
                )
                period_str = (str(q_from), str(q_to))

                with st.spinner("1/3 кампании…"):
                    cq = fetch_campaign_quality(creds_q, *period_str)
                    save_quality_cache("campaign_quality", cq, period_str)
                with st.spinner("2/3 ключевики…"):
                    kw = fetch_keyword_report(creds_q, *period_str)
                    save_quality_cache("keywords", kw, period_str)
                with st.spinner("3/3 объявления…"):
                    ad = fetch_ad_report(creds_q, *period_str)
                    save_quality_cache("ads_creatives", ad, period_str)

                st.success(
                    f"Кампании: {len(cq)} · Ключевики: {len(kw)} · "
                    f"Объявления: {len(ad)}"
                )
                st.rerun()
            except Exception as e:
                st.error(str(e))

        _, _cq_meta = load_quality_cache("campaign_quality")
        if _cq_meta:
            st.caption(
                f"📦 Кэш за {_cq_meta.get('period_from', '?')} – "
                f"{_cq_meta.get('period_to', '?')}"
            )

    st.divider()
    render_cache_reset_button(key_prefix="quality")

    if os.environ.get("APP_PASSWORD"):
        st.divider()
        if st.button("🚪 Выйти", use_container_width=True, key="logout_btn",
                     help="Сбросить вход на этом устройстве."):
            st.session_state.pop("auth_ok", None)
            st.query_params.clear()
            st.rerun()


# ─── Загрузка кэша ────────────────────────────────────────────
_q_camp, _q_camp_meta = load_quality_cache("campaign_quality")
_q_kw, _q_kw_meta = load_quality_cache("keywords")
_q_ad, _q_ad_meta = load_quality_cache("ads_creatives")

# Если кэша нет, а API подключён — автозагрузка за последние 90 дней.
# Это даёт «Roistat-like» поведение: открыл страницу → кампании уже видны.
# При неудаче запоминаем флаг чтобы не зацикливать попытки.
_cache_empty = _q_camp.empty and _q_kw.empty and _q_ad.empty
_auto_failed = st.session_state.get("yd_quality_auto_failed", False)

if _cache_empty and _yd_creds_global and not _auto_failed:
    with st.spinner(
        "Подтягиваю кампании из Яндекс.Директа за последние 90 дней… "
        "(30-60 секунд, делается один раз — дальше кэшируется)"
    ):
        try:
            from yandex_direct import (
                DirectCredentials,
                fetch_campaign_quality, fetch_keyword_report, fetch_ad_report,
            )
            auto_creds = DirectCredentials(
                token=_yd_creds_global.token,
                client_login=_yd_creds_global.client_login,
            )
            auto_from = (pd.Timestamp.today() - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
            auto_to = pd.Timestamp.today().strftime("%Y-%m-%d")
            auto_period = (auto_from, auto_to)

            cq = fetch_campaign_quality(auto_creds, *auto_period)
            save_quality_cache("campaign_quality", cq, auto_period)
            kw = fetch_keyword_report(auto_creds, *auto_period)
            save_quality_cache("keywords", kw, auto_period)
            ad = fetch_ad_report(auto_creds, *auto_period)
            save_quality_cache("ads_creatives", ad, auto_period)
            st.rerun()
        except Exception as e:
            st.session_state["yd_quality_auto_failed"] = True
            st.error(f"Не получилось подтянуть аналитику автоматически: {e}")

if _cache_empty:
    if _yd_creds_global is None:
        st.error(
            "🔑 **API Яндекс.Директа не подключён.** Добавьте `YANDEX_DIRECT_TOKEN` "
            "в Streamlit Secrets — после этого кампании появятся автоматически."
        )
    else:
        st.info(
            "📭 **Нет данных.** Выберите период в сайдбаре слева и нажмите "
            "**«Подтянуть качество»** — кампании, ключевики и объявления подтянутся "
            "из Яндекс.Директа.\n\n"
            "Что вы увидите:\n"
            "- **Кампании** — CTR, CPC, конверсии-цели Метрики, CPL, отказы, глубина просмотров\n"
            "- **Ключевые слова** — топ по расходу, топ по конверсиям, топ убыточных\n"
            "- **Объявления (креативы)** — A/B-сравнение по CTR и конверсиям\n"
        )
    st.stop()

_q_period_lbl = (
    f"{_q_camp_meta.get('period_from', '?')} – {_q_camp_meta.get('period_to', '?')}"
    if _q_camp_meta else "—"
)
st.caption(f"Данные API за период **{_q_period_lbl}**. Обновляется кнопкой «Подтянуть качество» в сайдбаре.")


# ─── Tabs ─────────────────────────────────────────────────────
quality_tabs = st.tabs(["Кампании", "Ключевые слова", "Объявления"])

# ====== Tab 1: КАМПАНИИ ======================================
with quality_tabs[0]:
    if _q_camp.empty:
        st.info("Нет данных по кампаниям.")
    else:
        cq = _q_camp.copy()
        for col in ("ctr", "conversion_rate", "bounce_rate", "avg_pageviews",
                    "conversions", "cost_per_conversion", "avg_cpc",
                    "spend_rub", "impressions", "clicks"):
            if col in cq.columns:
                cq[col] = pd.to_numeric(cq[col], errors="coerce")

        # Сводные плитки
        total_spend = cq["spend_rub"].sum() if "spend_rub" in cq else 0
        total_clicks = cq["clicks"].sum() if "clicks" in cq else 0
        total_impr = cq["impressions"].sum() if "impressions" in cq else 0
        total_conv = cq["conversions"].sum() if "conversions" in cq else 0
        avg_ctr = (total_clicks / total_impr * 100) if total_impr else 0
        avg_cpc_total = (total_spend / total_clicks) if total_clicks else 0
        avg_cpl = (total_spend / total_conv) if total_conv else 0

        qc1, qc2, qc3, qc4 = st.columns(4)
        qc1.markdown(kpi_card(
            "Расход", fmt_rub(total_spend),
            f"{int(total_impr):,} показов".replace(",", " "),
            kind="red",
        ), unsafe_allow_html=True)
        qc2.markdown(kpi_card(
            "Кликов", fmt_num(total_clicks),
            f"CTR {avg_ctr:.2f}%",
            kind="primary",
            tooltip="Кликабельность объявлений = клики / показы. Чем выше, тем релевантнее. Норма для поиска ~1-3%, РСЯ ~0.3-1%.",
        ), unsafe_allow_html=True)
        qc3.markdown(kpi_card(
            "Средний CPC", fmt_rub(avg_cpc_total),
            "стоимость клика",
            tooltip="Cost Per Click = расход / клики. Чем ниже — тем дешевле трафик.",
        ), unsafe_allow_html=True)
        conv_kind = "green" if total_conv > 0 else "red"
        qc4.markdown(kpi_card(
            "Конверсии (цели)", fmt_num(total_conv),
            f"CPL {fmt_rub(avg_cpl)}" if total_conv else "цели Метрики не зафиксированы",
            kind=conv_kind,
            tooltip="Достижения целей в Я.Метрике (заявка / оплата / другая цель). CPL = расход / конверсии.",
        ), unsafe_allow_html=True)

        # Таблица
        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        cq_show = cq.sort_values("spend_rub", ascending=False).copy()
        display_cols = {
            "campaign": "Кампания",
            "campaign_type": "Тип",
            "impressions": "Показы",
            "clicks": "Клики",
            "ctr": "CTR, %",
            "spend_rub": "Расход, ₽",
            "avg_cpc": "CPC, ₽",
            "conversions": "Конв.",
            "conversion_rate": "CR, %",
            "cost_per_conversion": "CPL, ₽",
            "bounce_rate": "Отказы, %",
            "avg_pageviews": "Глубина",
        }
        available = [c for c in display_cols if c in cq_show.columns]
        st.dataframe(
            cq_show[available].rename(columns=display_cols),
            use_container_width=True, hide_index=True,
            column_config={
                "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "CPC, ₽": st.column_config.NumberColumn(format="%.1f"),
                "CTR, %": st.column_config.NumberColumn(format="%.2f"),
                "CR, %": st.column_config.NumberColumn(format="%.2f"),
                "Конв.": st.column_config.NumberColumn(format="%.0f"),
                "CPL, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Отказы, %": st.column_config.NumberColumn(format="%.1f"),
                "Глубина": st.column_config.NumberColumn(format="%.2f"),
                "Показы": st.column_config.NumberColumn(format="%d"),
                "Клики": st.column_config.NumberColumn(format="%d"),
            },
        )

        # Scatter CTR×CPC
        if "ctr" in cq.columns and "avg_cpc" in cq.columns and len(cq) >= 2:
            cq_chart = cq[(cq["clicks"] > 0) & cq["ctr"].notna() & cq["avg_cpc"].notna()].copy()
            if len(cq_chart) >= 2:
                fig_qc = px.scatter(
                    cq_chart,
                    x="avg_cpc", y="ctr",
                    size="spend_rub",
                    color="conversions" if cq_chart["conversions"].notna().any() else None,
                    hover_name="campaign",
                    hover_data={"spend_rub": ":.0f", "clicks": True, "conversions": True},
                    color_continuous_scale="Greens",
                    labels={"avg_cpc": "CPC, ₽", "ctr": "CTR, %",
                            "conversions": "Конверсии", "spend_rub": "Расход, ₽"},
                )
                fig_qc.update_layout(
                    **{**PLOTLY_LAYOUT, "height": 380,
                       "title": "CTR × CPC: размер точки = расход, цвет = конверсии"},
                )
                st.plotly_chart(fig_qc, use_container_width=True)


# ====== Tab 2: КЛЮЧЕВЫЕ СЛОВА ================================
with quality_tabs[1]:
    if _q_kw.empty:
        st.info("Нет данных по ключевикам.")
    else:
        kw = _q_kw.copy()
        for col in ("ctr", "conversion_rate", "conversions", "cost_per_conversion",
                    "avg_cpc", "spend_rub", "impressions", "clicks"):
            if col in kw.columns:
                kw[col] = pd.to_numeric(kw[col], errors="coerce")

        kw_view = st.radio(
            "Что показать",
            ["Топ-30 по расходу", "Топ-30 с конверсиями",
             "Топ-30 убыточных (клики > 30, конв. = 0)"],
            horizontal=True, key="kw_view_mode",
        )
        if kw_view == "Топ-30 по расходу":
            kw_show = kw.sort_values("spend_rub", ascending=False).head(30)
        elif kw_view == "Топ-30 с конверсиями":
            kw_show = (kw[kw["conversions"] > 0]
                       .sort_values("conversions", ascending=False).head(30))
        else:
            kw_show = (kw[(kw["clicks"] > 30) & (kw["conversions"].fillna(0) == 0)]
                       .sort_values("spend_rub", ascending=False).head(30))

        if kw_show.empty:
            st.info("По выбранному фильтру нет данных.")
        else:
            display_cols = {
                "criterion": "Ключевик / фраза",
                "campaign": "Кампания",
                "ad_group": "Группа",
                "match_type": "Тип",
                "impressions": "Показы",
                "clicks": "Клики",
                "ctr": "CTR, %",
                "spend_rub": "Расход, ₽",
                "avg_cpc": "CPC, ₽",
                "conversions": "Конв.",
                "conversion_rate": "CR, %",
                "cost_per_conversion": "CPL, ₽",
            }
            available = [c for c in display_cols if c in kw_show.columns]
            st.dataframe(
                kw_show[available].rename(columns=display_cols),
                use_container_width=True, hide_index=True,
                column_config={
                    "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                    "CPC, ₽": st.column_config.NumberColumn(format="%.1f"),
                    "CTR, %": st.column_config.NumberColumn(format="%.2f"),
                    "CR, %": st.column_config.NumberColumn(format="%.2f"),
                    "Конв.": st.column_config.NumberColumn(format="%.0f"),
                    "CPL, ₽": st.column_config.NumberColumn(format="%.0f"),
                },
            )
            if kw_view == "Топ-30 убыточных (клики > 30, конв. = 0)" and not kw_show.empty:
                waste = kw_show["spend_rub"].sum()
                st.caption(
                    f"💸 Эти {len(kw_show)} ключевиков съели **{fmt_rub(waste)}** "
                    f"без единой конверсии. Кандидаты на минус-слова или удаление."
                )


# ====== Tab 3: ОБЪЯВЛЕНИЯ ====================================
with quality_tabs[2]:
    if _q_ad.empty:
        st.info("Нет данных по объявлениям.")
    else:
        ad = _q_ad.copy()
        for col in ("ctr", "conversion_rate", "conversions",
                    "avg_cpc", "spend_rub", "impressions", "clicks"):
            if col in ad.columns:
                ad[col] = pd.to_numeric(ad[col], errors="coerce")
        ad_show = ad.sort_values("spend_rub", ascending=False).head(40)

        st.caption(
            "Топ-40 объявлений по расходу. **AdId** — id объявления в Директе "
            "(чтобы увидеть текст/картинку: direct.yandex.ru → найти по id)."
        )
        display_cols = {
            "ad_id": "AdId",
            "campaign": "Кампания",
            "ad_group": "Группа",
            "impressions": "Показы",
            "clicks": "Клики",
            "ctr": "CTR, %",
            "spend_rub": "Расход, ₽",
            "avg_cpc": "CPC, ₽",
            "conversions": "Конв.",
            "conversion_rate": "CR, %",
        }
        available = [c for c in display_cols if c in ad_show.columns]
        st.dataframe(
            ad_show[available].rename(columns=display_cols),
            use_container_width=True, hide_index=True,
            column_config={
                "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "CPC, ₽": st.column_config.NumberColumn(format="%.1f"),
                "CTR, %": st.column_config.NumberColumn(format="%.2f"),
                "CR, %": st.column_config.NumberColumn(format="%.2f"),
                "Конв.": st.column_config.NumberColumn(format="%.0f"),
            },
        )
