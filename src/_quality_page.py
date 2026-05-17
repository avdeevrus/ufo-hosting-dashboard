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
import storage


# При старте страницы тянем кэш качества с HF Dataset (если он там есть от
# прошлой сессии или другого устройства). Это критично на Streamlit Cloud:
# при каждом деплое контейнер пересоздаётся и локальный data/api_cache/*.json
# стирается → без этого sync_down автозагрузка дёргалась каждый раз.
# st.cache_resource гарантирует один вызов на сессию.
@st.cache_resource(show_spinner=False)
def _initial_quality_sync():
    return storage.sync_quality_cache_down() if storage.is_enabled() else None


_initial_quality_sync()


def _save_and_sync(kind: str, df: pd.DataFrame, period: tuple) -> None:
    """save_quality_cache + upload в HF Dataset (если включён). Чтобы кэш
    переживал рестарты контейнера и был доступен в других сессиях."""
    save_quality_cache(kind, df, period)
    if storage.is_enabled():
        filename_map = {
            "campaign_quality": "yd_campaign_quality.json",
            "keywords": "yd_keywords.json",
            "ads_creatives": "yd_ads_creatives.json",
        }
        fname = filename_map.get(kind)
        if fname:
            storage.sync_quality_cache_up(fname)


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
        # API Я.Директа отдаёт максимум за последние 3 года от текущего месяца.
        # Считаем динамически: первый день месяца «3 года назад» — самый
        # широкий валидный диапазон.
        _api_min = (pd.Timestamp.today().replace(day=1) - pd.DateOffset(years=3))
        q_from = st.date_input(
            "С даты",
            value=_api_min,
            min_value=_api_min,
            key="yd_quality_from",
            format="DD.MM.YYYY",
            help=(
                f"API Я.Директа отдаёт статистику не ранее "
                f"{_api_min:%d.%m.%Y} (3 года от текущего месяца)."
            ),
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

                with st.status(f"📥 Тяну Я.Директ за {period_str[0]} – {period_str[1]}…",
                               expanded=True) as st_status:

                    def _make_progress(stage_num: int, stage_name: str):
                        """Возвращает callback, который обновляет label статуса
                        по мере завершения чанков (параллельно)."""
                        def _cb(done: int, total: int):
                            st_status.update(
                                label=f"📥 [{stage_num}/3] {stage_name} — "
                                      f"чанков {done}/{total} (параллельно)",
                                state="running",
                            )
                        return _cb

                    st_status.update(label="📥 [1/3] Кампании (CTR, CPC, конверсии)…",
                                     state="running")
                    cq = fetch_campaign_quality(
                        creds_q, *period_str,
                        progress_callback=_make_progress(1, "Кампании"),
                    )
                    _save_and_sync("campaign_quality", cq, period_str)
                    st.write(f"✅ Кампании: {len(cq)} строк")

                    st_status.update(label="📥 [2/3] Ключевые слова…", state="running")
                    kw = fetch_keyword_report(
                        creds_q, *period_str,
                        progress_callback=_make_progress(2, "Ключевые слова"),
                    )
                    _save_and_sync("keywords", kw, period_str)
                    st.write(f"✅ Ключевые слова: {len(kw)} строк")

                    st_status.update(label="📥 [3/3] Объявления (креативы)…", state="running")
                    ad = fetch_ad_report(
                        creds_q, *period_str,
                        progress_callback=_make_progress(3, "Объявления"),
                    )
                    _save_and_sync("ads_creatives", ad, period_str)
                    st.write(f"✅ Объявления: {len(ad)} строк")

                    st_status.update(label="✅ Все 3 отчёта загружены", state="complete")
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

# Если кэша нет, а API подключён — автозагрузка ЗА ВСЁ ВРЕМЯ.
# 2023-01-01 = безопасная нижняя граница (Я.Директ UFO Hosting начался летом 2025).
# Это даёт «Roistat-like» поведение: открыл страницу → кампании уже видны.
# При неудаче запоминаем флаг чтобы не зацикливать попытки.
_cache_empty = _q_camp.empty and _q_kw.empty and _q_ad.empty
_auto_failed = st.session_state.get("yd_quality_auto_failed", False)

if _cache_empty and _yd_creds_global and not _auto_failed:
    # API Я.Директа: статистика только за последние 3 года от текущего месяца.
    # Берём первый день месяца «3 года назад» — максимально широкий валидный
    # диапазон. Жёсткая дата «2023-01-01» сломалась после 2026-04-30.
    _today = pd.Timestamp.today().normalize()
    auto_from = (_today.replace(day=1) - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
    auto_to = _today.strftime("%Y-%m-%d")
    auto_period = (auto_from, auto_to)

    # st.status — поэтапный progress: пользователь видит что именно тянется,
    # а не просто крутящийся спиннер на 3 минуты.
    with st.status(
        f"📥 Тяну всю историю Я.Директа ({auto_from} → {auto_to})…",
        expanded=True,
    ) as status:
        try:
            from yandex_direct import (
                DirectCredentials,
                fetch_campaign_quality, fetch_keyword_report, fetch_ad_report,
            )
            auto_creds = DirectCredentials(
                token=_yd_creds_global.token,
                client_login=_yd_creds_global.client_login,
            )
            errors_summary = []
            stages = [
                ("Кампании (CTR, CPC, конверсии, отказы)", "campaign_quality", fetch_campaign_quality),
                ("Ключевые слова (с match-type)",          "keywords",          fetch_keyword_report),
                ("Объявления (креативы)",                  "ads_creatives",     fetch_ad_report),
            ]

            def _make_auto_progress(stage_num: int, stage_label: str):
                """callback показывает прогресс «чанков X/Y» в текущей строке статуса."""
                def _cb(done: int, total: int):
                    status.update(
                        label=f"📥 [{stage_num}/3] {stage_label} — "
                              f"чанков {done}/{total} (параллельно)",
                        state="running",
                    )
                return _cb

            for i, (label, kind, fetcher) in enumerate(stages, start=1):
                status.update(label=f"📥 [{i}/3] {label}…", state="running")
                try:
                    df = fetcher(
                        auto_creds, *auto_period,
                        progress_callback=_make_auto_progress(i, label),
                    )
                    _save_and_sync(kind, df, auto_period)
                    st.write(f"✅ {label}: {len(df)} строк")
                except Exception as ex:
                    errors_summary.append((kind, str(ex)))
                    st.write(f"⚠️ {label}: {ex}")

            if errors_summary and len(errors_summary) == 3:
                status.update(label="❌ Не удалось загрузить ни один отчёт", state="error")
                raise RuntimeError(errors_summary[0][1])
            elif errors_summary:
                status.update(
                    label=f"⚠️ Загружено частично ({3 - len(errors_summary)}/3 отчётов)",
                    state="complete",
                )
            else:
                status.update(label="✅ Готово — все 3 отчёта загружены", state="complete")
            st.rerun()
        except Exception as e:
            st.session_state["yd_quality_auto_failed"] = True
            status.update(label="❌ Подключение к Я.Директ упало", state="error")
            st.error(
                f"❌ **Подключение к Яндекс.Директ API упало**\n\n"
                f"```\n{e}\n```\n\n"
                f"**Возможные причины:**\n"
                f"- `YANDEX_DIRECT_TOKEN` истёк или неверен → получите новый на "
                f"https://oauth.yandex.ru/\n"
                f"- В OAuth-приложении нет права «Использование API Директа» (ошибка 53)\n"
                f"- Агентский аккаунт → добавьте `YANDEX_DIRECT_CLIENT_LOGIN` в Secrets (ошибка 8800)\n"
                f"- API ещё не модерирован (ошибка 58) → "
                f"direct.yandex.ru → Инструменты → Управление доступом → API → подать заявку"
            )

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

# Расхождение с шапкой главного дашборда — если расход с API < расхода
# в XLSX за общий период, скорее всего XLSX содержит архивные кампании
# которые API уже не отдаёт.
_qp_total_spend = (
    pd.to_numeric(_q_camp["spend_rub"], errors="coerce").sum()
    if "spend_rub" in _q_camp.columns else 0.0
)
if _qp_total_spend > 0:
    st.caption(
        f"ℹ️ **Расход {fmt_rub(_qp_total_spend)} = только Яндекс.Директ API.** "
        f"На главном дашборде расход может быть больше — там XLSX-выгрузки + API. "
        f"XLSX часто содержит архивные/закрытые кампании, которые API уже не возвращает. "
        f"Это не ошибка расчёта — это разный охват источников."
    )


# ─── Tabs ─────────────────────────────────────────────────────
quality_tabs = st.tabs([
    "🔬 Глубокая (drill-down)",
    "Все кампании",
    "Все ключи",
    "Все объявления",
])


# ====== Tab 0: ГЛУБОКАЯ АНАЛИТИКА (DRILL-DOWN) ===============
with quality_tabs[0]:
    st.caption(
        "Выберите кампанию → раскроется список групп объявлений → "
        "выберите группу → увидите объявления и ключевики этой группы."
    )

    if _q_camp.empty:
        st.info("Нет данных по кампаниям.")
    else:
        # Нормализуем числа
        _dd_camp = _q_camp.copy()
        for col in ("ctr", "conversion_rate", "bounce_rate", "avg_pageviews",
                    "conversions", "cost_per_conversion", "avg_cpc",
                    "spend_rub", "impressions", "clicks"):
            if col in _dd_camp.columns:
                _dd_camp[col] = pd.to_numeric(_dd_camp[col], errors="coerce")
        _dd_camp = _dd_camp.sort_values("spend_rub", ascending=False)

        _dd_kw = _q_kw.copy() if not _q_kw.empty else pd.DataFrame()
        _dd_ad = _q_ad.copy() if not _q_ad.empty else pd.DataFrame()
        for _df in (_dd_kw, _dd_ad):
            for col in ("ctr", "conversion_rate", "conversions",
                        "cost_per_conversion", "avg_cpc",
                        "spend_rub", "impressions", "clicks"):
                if col in _df.columns:
                    _df[col] = pd.to_numeric(_df[col], errors="coerce")

        # Список кампаний с расходом в подписи (sorted by spend desc)
        _camp_options = _dd_camp["campaign"].tolist()
        _camp_spend_map = dict(zip(_dd_camp["campaign"], _dd_camp["spend_rub"].fillna(0)))

        def _fmt_camp(name: str) -> str:
            sp = _camp_spend_map.get(name, 0)
            return f"{name[:80]} · {fmt_rub(sp)}"

        sel_camp = st.selectbox(
            "🎯 Кампания",
            options=_camp_options,
            format_func=_fmt_camp,
            key="dd_camp_select",
        )

        if sel_camp:
            # ─── KPI выбранной кампании ───────────────────────
            c_row = _dd_camp[_dd_camp["campaign"] == sel_camp].iloc[0]
            kpi_cols = st.columns(5)
            kpi_cols[0].markdown(kpi_card(
                "Расход", fmt_rub(c_row.get("spend_rub", 0)),
                f"{int(c_row.get('impressions', 0)):,} показов".replace(",", " "),
                kind="red",
            ), unsafe_allow_html=True)
            kpi_cols[1].markdown(kpi_card(
                "Кликов", fmt_num(c_row.get("clicks", 0)),
                f"CTR {c_row.get('ctr', 0):.2f}%",
                kind="primary",
            ), unsafe_allow_html=True)
            kpi_cols[2].markdown(kpi_card(
                "Средний CPC", fmt_rub(c_row.get("avg_cpc", 0)),
                "стоимость клика",
            ), unsafe_allow_html=True)
            kpi_cols[3].markdown(kpi_card(
                "Конверсии", fmt_num(c_row.get("conversions", 0) or 0),
                f"CR {c_row.get('conversion_rate', 0) or 0:.2f}%",
                kind="green" if (c_row.get("conversions", 0) or 0) > 0 else "red",
            ), unsafe_allow_html=True)
            kpi_cols[4].markdown(kpi_card(
                "CPL", fmt_rub(c_row.get("cost_per_conversion", 0) or 0),
                "стоимость цели",
            ), unsafe_allow_html=True)

            st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)

            # ─── Группы объявлений в этой кампании ────────────
            # Группы достаём из ad_report или keyword_report (что доступно)
            camp_ads_df = _dd_ad[_dd_ad["campaign"] == sel_camp] if "campaign" in _dd_ad.columns else pd.DataFrame()
            camp_kw_df = _dd_kw[_dd_kw["campaign"] == sel_camp] if "campaign" in _dd_kw.columns else pd.DataFrame()

            # Сводная по группам: предпочитаем суммы из объявлений (полнее),
            # но если их нет — берём из ключей. CTR/CPC пересчитываем из сумм.
            groups_src = camp_ads_df if not camp_ads_df.empty else camp_kw_df
            if groups_src.empty or "ad_group" not in groups_src.columns:
                st.info(
                    "Нет детализации по группам объявлений для этой кампании "
                    "(возможно, авто-таргетинг РСЯ или старые архивные данные)."
                )
            else:
                agg_dict = {c: "sum" for c in ("impressions", "clicks", "spend_rub", "conversions") if c in groups_src.columns}
                grp_summary = groups_src.groupby("ad_group", as_index=False).agg(agg_dict)
                if "impressions" in grp_summary and "clicks" in grp_summary:
                    grp_summary["ctr"] = (grp_summary["clicks"] / grp_summary["impressions"].replace(0, pd.NA) * 100).fillna(0)
                if "spend_rub" in grp_summary and "clicks" in grp_summary:
                    grp_summary["avg_cpc"] = (grp_summary["spend_rub"] / grp_summary["clicks"].replace(0, pd.NA)).fillna(0)
                if "conversions" in grp_summary and "spend_rub" in grp_summary:
                    grp_summary["cpl"] = (grp_summary["spend_rub"] / grp_summary["conversions"].replace(0, pd.NA))
                grp_summary = grp_summary.sort_values("spend_rub", ascending=False)

                st.markdown(f"**Группы объявлений в кампании** — {len(grp_summary)} шт.")
                grp_display = grp_summary.rename(columns={
                    "ad_group": "Группа",
                    "impressions": "Показы",
                    "clicks": "Клики",
                    "ctr": "CTR, %",
                    "spend_rub": "Расход, ₽",
                    "avg_cpc": "CPC, ₽",
                    "conversions": "Конв.",
                    "cpl": "CPL, ₽",
                })
                st.dataframe(
                    grp_display, use_container_width=True, hide_index=True,
                    column_config={
                        "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                        "CPC, ₽": st.column_config.NumberColumn(format="%.1f"),
                        "CTR, %": st.column_config.NumberColumn(format="%.2f"),
                        "CPL, ₽": st.column_config.NumberColumn(format="%.0f"),
                        "Конв.": st.column_config.NumberColumn(format="%.0f"),
                        "Показы": st.column_config.NumberColumn(format="%d"),
                        "Клики": st.column_config.NumberColumn(format="%d"),
                    },
                )

                # ─── Drill в группу ───────────────────────────
                group_options = grp_summary["ad_group"].tolist()
                _grp_spend_map = dict(zip(grp_summary["ad_group"], grp_summary["spend_rub"].fillna(0)))

                def _fmt_grp(name: str) -> str:
                    sp = _grp_spend_map.get(name, 0)
                    return f"{name[:80]} · {fmt_rub(sp)}"

                sel_group = st.selectbox(
                    "📁 Группа объявлений",
                    options=group_options,
                    format_func=_fmt_grp,
                    key=f"dd_grp_select_{sel_camp[:30]}",
                )

                if sel_group:
                    # Объявления + ключи в выбранной группе — 2 колонки
                    g_ads = camp_ads_df[camp_ads_df["ad_group"] == sel_group] if not camp_ads_df.empty else pd.DataFrame()
                    g_kw = camp_kw_df[camp_kw_df["ad_group"] == sel_group] if not camp_kw_df.empty else pd.DataFrame()

                    col_ads, col_kw = st.columns(2)

                    with col_ads:
                        st.markdown(f"**Объявления** ({len(g_ads)} шт.)")
                        if g_ads.empty:
                            st.info("Нет объявлений по этой группе.")
                        else:
                            g_ads_show = g_ads.sort_values("spend_rub", ascending=False)
                            ads_display = g_ads_show.rename(columns={
                                "ad_id": "AdId",
                                "impressions": "Показы",
                                "clicks": "Клики",
                                "ctr": "CTR, %",
                                "spend_rub": "Расход, ₽",
                                "avg_cpc": "CPC, ₽",
                                "conversions": "Конв.",
                                "conversion_rate": "CR, %",
                            })
                            cols = [c for c in ("AdId", "Показы", "Клики", "CTR, %",
                                                "Расход, ₽", "CPC, ₽", "Конв.", "CR, %")
                                    if c in ads_display.columns]
                            st.dataframe(
                                ads_display[cols], use_container_width=True, hide_index=True,
                                column_config={
                                    "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                                    "CPC, ₽": st.column_config.NumberColumn(format="%.1f"),
                                    "CTR, %": st.column_config.NumberColumn(format="%.2f"),
                                    "CR, %": st.column_config.NumberColumn(format="%.2f"),
                                    "Конв.": st.column_config.NumberColumn(format="%.0f"),
                                },
                            )

                    with col_kw:
                        st.markdown(f"**Ключевые слова** ({len(g_kw)} шт.)")
                        if g_kw.empty:
                            st.info("Нет ключей по этой группе.")
                        else:
                            g_kw_show = g_kw.sort_values("spend_rub", ascending=False)
                            kw_display = g_kw_show.rename(columns={
                                "criterion": "Ключевик",
                                "match_type": "Тип",
                                "impressions": "Показы",
                                "clicks": "Клики",
                                "ctr": "CTR, %",
                                "spend_rub": "Расход, ₽",
                                "avg_cpc": "CPC, ₽",
                                "conversions": "Конв.",
                                "cost_per_conversion": "CPL, ₽",
                            })
                            cols = [c for c in ("Ключевик", "Тип", "Показы", "Клики",
                                                "CTR, %", "Расход, ₽", "CPC, ₽",
                                                "Конв.", "CPL, ₽")
                                    if c in kw_display.columns]
                            st.dataframe(
                                kw_display[cols], use_container_width=True, hide_index=True,
                                column_config={
                                    "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                                    "CPC, ₽": st.column_config.NumberColumn(format="%.1f"),
                                    "CTR, %": st.column_config.NumberColumn(format="%.2f"),
                                    "CPL, ₽": st.column_config.NumberColumn(format="%.0f"),
                                    "Конв.": st.column_config.NumberColumn(format="%.0f"),
                                },
                            )

# ====== Tab 1: ВСЕ КАМПАНИИ (плоский отчёт) ===================
with quality_tabs[1]:
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


# ====== Tab 2: ВСЕ КЛЮЧЕВЫЕ СЛОВА ============================
with quality_tabs[2]:
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


# ====== Tab 3: ВСЕ ОБЪЯВЛЕНИЯ ================================
with quality_tabs[3]:
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
