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


# ============================================================
#       ИЕРАРХИЧЕСКАЯ ТАБЛИЦА: Кампания → Группа → Объявление
# ============================================================
# Одна большая treetable как в Roistat/CoMagic/Marilyn: плюсики
# раскрывают уровни. Все метрики видны на каждой строке. Никаких
# вкладок, никаких подкаталогов — один экран, полная картина.

if _q_camp.empty:
    st.info("Нет данных по кампаниям. Подтяните данные в сайдбаре.")
    st.stop()


# ─── Нормализация и агрегаты ──────────────────────────────────
def _to_num(df: pd.DataFrame, cols: tuple) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


_camp = _to_num(_q_camp.copy(), (
    "impressions", "clicks", "ctr", "spend_rub", "avg_cpc",
    "conversions", "conversion_rate", "cost_per_conversion",
    "bounce_rate", "avg_pageviews",
))
_ad = _to_num(_q_ad.copy(), (
    "impressions", "clicks", "ctr", "spend_rub", "avg_cpc",
    "conversions", "conversion_rate",
)) if not _q_ad.empty else pd.DataFrame()
_kw_all = _to_num(_q_kw.copy(), (
    "impressions", "clicks", "ctr", "spend_rub", "avg_cpc",
    "conversions", "conversion_rate", "cost_per_conversion",
)) if not _q_kw.empty else pd.DataFrame()


# ─── Сводные плитки сверху (как было) ─────────────────────────
total_spend  = float(_camp["spend_rub"].sum())   if "spend_rub" in _camp else 0.0
total_clicks = float(_camp["clicks"].sum())      if "clicks"    in _camp else 0.0
total_impr   = float(_camp["impressions"].sum()) if "impressions" in _camp else 0.0
total_conv   = float(_camp["conversions"].sum()) if "conversions" in _camp else 0.0
avg_ctr     = (total_clicks / total_impr * 100) if total_impr else 0
avg_cpc_t   = (total_spend / total_clicks)      if total_clicks else 0
avg_cpl     = (total_spend / total_conv)        if total_conv else 0

qc1, qc2, qc3, qc4 = st.columns(4)
qc1.markdown(kpi_card(
    "Расход", fmt_rub(total_spend),
    f"{int(total_impr):,} показов".replace(",", " "), kind="red",
), unsafe_allow_html=True)
qc2.markdown(kpi_card(
    "Кликов", fmt_num(total_clicks), f"CTR {avg_ctr:.2f}%", kind="primary",
), unsafe_allow_html=True)
qc3.markdown(kpi_card(
    "Средний CPC", fmt_rub(avg_cpc_t), "стоимость клика",
), unsafe_allow_html=True)
qc4.markdown(kpi_card(
    "Конверсии (цели)", fmt_num(total_conv),
    f"CPL {fmt_rub(avg_cpl)}" if total_conv else "цели Метрики не зафиксированы",
    kind="green" if total_conv > 0 else "red",
), unsafe_allow_html=True)


# ─── Строим иерархический DataFrame для AgGrid ────────────────
# Уровни: Кампания → Группа → Объявление. Метрики на каждой строке.
# Кампания: берём строку из _q_camp как есть (там полный набор метрик)
# Группа:   агрегируем _q_ad по (campaign, ad_group)
# Объявление: строка _q_ad

def _safe_div(a, b):
    return (a / b) if b else 0.0

rows = []
campaigns_sorted = _camp.sort_values("spend_rub", ascending=False)

for _, cr in campaigns_sorted.iterrows():
    camp_name = cr.get("campaign", "—") or "—"
    row_c = {
        "path":         [str(camp_name)],
        "level":        "🎯 Кампания",
        "impressions":  float(cr.get("impressions", 0) or 0),
        "clicks":       float(cr.get("clicks", 0) or 0),
        "ctr":          float(cr.get("ctr", 0) or 0),
        "spend_rub":    float(cr.get("spend_rub", 0) or 0),
        "avg_cpc":      float(cr.get("avg_cpc", 0) or 0),
        "conversions":  float(cr.get("conversions", 0) or 0),
        "conversion_rate": float(cr.get("conversion_rate", 0) or 0),
        "cpl":          float(cr.get("cost_per_conversion", 0) or 0),
        "bounce_rate":  float(cr.get("bounce_rate", 0) or 0),
    }
    rows.append(row_c)

    # Группы внутри этой кампании
    if not _ad.empty:
        camp_ads = _ad[_ad["campaign"] == camp_name]
        if camp_ads.empty:
            continue
        for grp_name, grp_df in camp_ads.groupby("ad_group", sort=False):
            g_impr  = float(grp_df["impressions"].sum())
            g_clk   = float(grp_df["clicks"].sum())
            g_spnd  = float(grp_df["spend_rub"].sum())
            g_conv  = float(grp_df["conversions"].sum())
            rows.append({
                "path":         [str(camp_name), str(grp_name)],
                "level":        "📁 Группа",
                "impressions":  g_impr,
                "clicks":       g_clk,
                "ctr":          _safe_div(g_clk, g_impr) * 100,
                "spend_rub":    g_spnd,
                "avg_cpc":      _safe_div(g_spnd, g_clk),
                "conversions":  g_conv,
                "conversion_rate": _safe_div(g_conv, g_clk) * 100,
                "cpl":          _safe_div(g_spnd, g_conv),
                "bounce_rate":  0.0,
            })

            # Объявления внутри группы — сортируем по расходу
            grp_sorted = grp_df.sort_values("spend_rub", ascending=False)
            for _, ar in grp_sorted.iterrows():
                ad_id = ar.get("ad_id", "—")
                rows.append({
                    "path":         [str(camp_name), str(grp_name), f"#{ad_id}"],
                    "level":        "📰 Объявление",
                    "impressions":  float(ar.get("impressions", 0) or 0),
                    "clicks":       float(ar.get("clicks", 0) or 0),
                    "ctr":          float(ar.get("ctr", 0) or 0),
                    "spend_rub":    float(ar.get("spend_rub", 0) or 0),
                    "avg_cpc":      float(ar.get("avg_cpc", 0) or 0),
                    "conversions":  float(ar.get("conversions", 0) or 0),
                    "conversion_rate": float(ar.get("conversion_rate", 0) or 0),
                    "cpl":          0.0,
                    "bounce_rate":  0.0,
                })

tree_df = pd.DataFrame(rows)


# ─── Сама AgGrid treetable ────────────────────────────────────
st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)
st.markdown(
    '<div style="font-size:1.05rem; font-weight:600; margin-bottom:0.4rem;">'
    '📊 Кампания → Группа → Объявление</div>',
    unsafe_allow_html=True,
)
st.caption(
    "Раскрывайте плюсиками: уровень кампании → группы объявлений → объявления. "
    "Все метрики (показы, CTR, расход, CPC, конверсии, CR, CPL) сразу видны на каждой строке."
)

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
    AGGRID_AVAILABLE = True
except ImportError:
    AGGRID_AVAILABLE = False

if not AGGRID_AVAILABLE:
    st.warning(
        "Для иерархической таблицы нужен пакет **streamlit-aggrid** — он уже "
        "в requirements.txt, но контейнер ещё не перестроился. Подождите "
        "1-2 минуты после деплоя и обновите страницу."
    )
else:
    # JS-форматтеры для красивых чисел в ячейках
    fmt_money = JsCode("""
        function(params) {
            if (params.value == null || params.value === 0) return '';
            return Math.round(params.value).toLocaleString('ru-RU') + ' ₽';
        }
    """)
    fmt_int = JsCode("""
        function(params) {
            if (params.value == null || params.value === 0) return '';
            return Math.round(params.value).toLocaleString('ru-RU');
        }
    """)
    fmt_pct = JsCode("""
        function(params) {
            if (params.value == null || params.value === 0) return '';
            return params.value.toFixed(2) + '%';
        }
    """)
    fmt_cpc = JsCode("""
        function(params) {
            if (params.value == null || params.value === 0) return '';
            return params.value.toFixed(1) + ' ₽';
        }
    """)

    # JS для построения дерева (Tree Data Mode)
    get_data_path = JsCode("function(data) { return data.path; }")

    grid_options = {
        "treeData": True,
        "animateRows": True,
        "groupDefaultExpanded": 0,  # 0 = всё свернуто, 1 = до 1-го уровня
        "getDataPath": get_data_path,
        "autoGroupColumnDef": {
            "headerName": "Кампания / Группа / Объявление",
            "minWidth": 380,
            "pinned": "left",
            "cellRendererParams": {
                "suppressCount": True,  # не показывать "(N)" рядом с группой
            },
        },
        "defaultColDef": {
            "sortable": True,
            "resizable": True,
            "filter": False,
        },
        "columnDefs": [
            {"field": "level", "headerName": "Тип", "width": 130, "hide": True},
            {"field": "impressions",   "headerName": "Показы",     "valueFormatter": fmt_int,   "width": 110, "type": "numericColumn"},
            {"field": "clicks",        "headerName": "Клики",      "valueFormatter": fmt_int,   "width":  95, "type": "numericColumn"},
            {"field": "ctr",           "headerName": "CTR",        "valueFormatter": fmt_pct,   "width":  85, "type": "numericColumn"},
            {"field": "spend_rub",     "headerName": "Расход",     "valueFormatter": fmt_money, "width": 130, "type": "numericColumn"},
            {"field": "avg_cpc",       "headerName": "CPC",        "valueFormatter": fmt_cpc,   "width":  90, "type": "numericColumn"},
            {"field": "conversions",   "headerName": "Конв.",      "valueFormatter": fmt_int,   "width":  85, "type": "numericColumn"},
            {"field": "conversion_rate","headerName": "CR",        "valueFormatter": fmt_pct,   "width":  85, "type": "numericColumn"},
            {"field": "cpl",           "headerName": "CPL",        "valueFormatter": fmt_money, "width": 110, "type": "numericColumn"},
            {"field": "bounce_rate",   "headerName": "Отказы",     "valueFormatter": fmt_pct,   "width":  95, "type": "numericColumn"},
        ],
        "rowData": tree_df.to_dict(orient="records"),
    }

    AgGrid(
        tree_df,
        gridOptions=grid_options,
        allow_unsafe_jscode=True,
        height=720,
        theme="streamlit",
        update_mode="NO_UPDATE",
        fit_columns_on_grid_load=False,
    )


# ============================================================
#                        КЛЮЧЕВЫЕ СЛОВА
# ============================================================
# Ключи показываем под основной таблицей — для конкретной кампании,
# выбранной пользователем (а не сразу все 5000+ строк).

if _kw_all.empty:
    st.info("📭 Нет данных по ключевикам.")
else:
    st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:1.05rem; font-weight:600; margin-bottom:0.4rem;">'
        '🔑 Ключевые слова</div>',
        unsafe_allow_html=True,
    )

    # Фильтры: кампания + представление
    kw_camps = ["Все кампании"] + sorted(_kw_all["campaign"].dropna().unique().tolist())
    kw_f1, kw_f2 = st.columns([2, 3])
    sel_kw_camp = kw_f1.selectbox("Кампания", options=kw_camps, key="kw_camp_filter")
    kw_view = kw_f2.radio(
        "Что показать",
        ["Топ-30 по расходу",
         "Топ-30 с конверсиями",
         "Топ-30 убыточных (клики > 30, конв. = 0)"],
        horizontal=True, key="kw_view_mode",
    )

    _kw = _kw_all if sel_kw_camp == "Все кампании" else _kw_all[_kw_all["campaign"] == sel_kw_camp]

    if kw_view == "Топ-30 по расходу":
        kw_show = _kw.sort_values("spend_rub", ascending=False).head(30)
    elif kw_view == "Топ-30 с конверсиями":
        kw_show = (_kw[_kw["conversions"] > 0]
                   .sort_values("conversions", ascending=False).head(30))
    else:
        kw_show = (_kw[(_kw["clicks"] > 30) & (_kw["conversions"].fillna(0) == 0)]
                   .sort_values("spend_rub", ascending=False).head(30))

    if kw_show.empty:
        st.info("По выбранному фильтру нет данных.")
    else:
        display_cols = {
            "criterion":   "Ключевик / фраза",
            "campaign":    "Кампания",
            "ad_group":    "Группа",
            "match_type":  "Тип",
            "impressions": "Показы",
            "clicks":      "Клики",
            "ctr":         "CTR, %",
            "spend_rub":   "Расход, ₽",
            "avg_cpc":     "CPC, ₽",
            "conversions": "Конв.",
            "conversion_rate":     "CR, %",
            "cost_per_conversion": "CPL, ₽",
        }
        available = [c for c in display_cols if c in kw_show.columns]
        st.dataframe(
            kw_show[available].rename(columns=display_cols),
            use_container_width=True, hide_index=True,
            column_config={
                "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "CPC, ₽":    st.column_config.NumberColumn(format="%.1f"),
                "CTR, %":    st.column_config.NumberColumn(format="%.2f"),
                "CR, %":     st.column_config.NumberColumn(format="%.2f"),
                "Конв.":     st.column_config.NumberColumn(format="%.0f"),
                "CPL, ₽":    st.column_config.NumberColumn(format="%.0f"),
            },
        )

        if kw_view.startswith("Топ-30 убыточных") and not kw_show.empty:
            waste = kw_show["spend_rub"].sum()
            st.caption(
                f"💸 Эти {len(kw_show)} ключевиков съели **{fmt_rub(waste)}** "
                f"без единой конверсии. Кандидаты на минус-слова или удаление."
            )
