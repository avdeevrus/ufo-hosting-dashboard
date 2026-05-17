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
    # Сайдбар свёрнут по умолчанию — иначе он съедает 280px ширины
    # и большая treetable не помещается в один экран. Параметры
    # выгрузки (даты, кнопка «Подтянуть качество») переехали наверх
    # страницы. Сайдбар оставляем только для «Сбросить кэш / Выйти».
    initial_sidebar_state="collapsed",
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

# Компактный CSS специально для этой страницы — убираем лишний воздух
# между блоками, прижимаем шапку к топу, стилизуем дата-инпуты.
st.markdown(
    """
    <style>
      /* Минимум padding сверху, чтобы шапка была ближе к топу окна */
      .main .block-container,
      section.main > div > div > div.block-container,
      [data-testid="stMainBlockContainer"] {
          padding-top: 0.55rem !important;
          padding-bottom: 0.5rem !important;
      }
      /* Сжимаем зазоры между элементами */
      .element-container { margin-bottom: 0.35rem !important; }
      /* Компактные label у дата-инпутов */
      [data-testid="stDateInput"] label { font-size: 0.78rem !important; margin-bottom: 0.15rem !important; }
      /* Кнопка primary — выше плотности */
      [data-testid="stBaseButton-primary"] { font-weight: 600 !important; }
      /* Заголовки убираем большие margin */
      h1, h2, h3 { margin-top: 0.4rem !important; margin-bottom: 0.3rem !important; }
      /* KPI карточки — плотнее */
      .kpi-card { padding: 0.7rem 0.85rem !important; }
      .kpi-label { font-size: 0.7rem !important; }
      .kpi-value { font-size: 1.55rem !important; line-height: 1.1 !important; }
      .kpi-sub   { font-size: 0.72rem !important; }
      /* AgGrid внутри st-aggrid div — без лишних рамок */
      iframe[title="st_aggrid.agGrid"] { border: 1px solid #e1e4e8 !important; border-radius: 8px !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─── Hero (компактный header) ─────────────────────────────────
st.markdown(
    """
    <div style="display:flex; align-items:baseline; gap:0.7rem; padding:0.1rem 0 0.45rem;">
      <h1 style="margin:0; font-size:1.4rem; letter-spacing:-0.4px;">🎯 Качество рекламы</h1>
      <div style="color:#6a737d; font-size:0.78rem;">
        Яндекс.Директ · CTR · CPC · конверсии-цели · ключевики · объявления
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ─── Sidebar: только сервисные действия ───────────────────────
# Параметры выгрузки (даты + кнопка «Подтянуть качество») переехали
# наверх страницы, чтобы освободить ширину под treetable. В сайдбар
# (свёрнут по умолчанию) — только «Сбросить кэш» и «Выйти».
with st.sidebar:
    st.markdown("### ⚙️ Сервис")
    st.caption("Параметры выгрузки — в шапке страницы.")
    st.divider()
    render_cache_reset_button(key_prefix="quality")
    if os.environ.get("APP_PASSWORD"):
        st.divider()
        if st.button("🚪 Выйти", use_container_width=True, key="logout_btn",
                     help="Сбросить вход на этом устройстве."):
            st.session_state.pop("auth_ok", None)
            st.query_params.clear()
            st.rerun()


# ─── Топбар: даты + кнопка Подтянуть качество ─────────────────
# Горизонтальный блок над таблицей. Заменяет старый сайдбар.
_yd_creds_global = yd_creds()
_api_min = (pd.Timestamp.today().replace(day=1) - pd.DateOffset(years=3))

if not _yd_creds_global:
    st.warning(
        "API Яндекс.Директа не подключён. "
        "Добавьте `YANDEX_DIRECT_TOKEN` в Secrets.",
        icon="🔑",
    )
    q_from = _api_min
    q_to = pd.Timestamp.today()
else:
    # Соотношение колонок: даты компактные, кнопка пошире, справа кэш-инфо
    tb_c1, tb_c2, tb_c3, tb_c4 = st.columns([1.1, 1.1, 1.6, 2.2])
    with tb_c1:
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
    with tb_c2:
        q_to = st.date_input(
            "По дату",
            value=pd.Timestamp.today(),
            key="yd_quality_to",
            format="DD.MM.YYYY",
        )
    with tb_c3:
        # Тонкий спейсер чтобы кнопка совпала по высоте с date-инпутами
        st.markdown("<div style='height:1.45rem'></div>", unsafe_allow_html=True)
        _sync_clicked = st.button(
            "📥 Подтянуть качество",
            use_container_width=True, type="primary",
            key="yd_quality_sync",
        )
    with tb_c4:
        st.markdown("<div style='height:1.55rem'></div>", unsafe_allow_html=True)
        _, _cq_meta_pre = load_quality_cache("campaign_quality")
        if _cq_meta_pre:
            st.markdown(
                f"<div style='font-size:0.78rem; color:#57606a; padding-top:0.3rem;'>"
                f"📦 Кэш за <b>{_cq_meta_pre.get('period_from', '?')}</b> — "
                f"<b>{_cq_meta_pre.get('period_to', '?')}</b></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='font-size:0.78rem; color:#9ba3ab; padding-top:0.3rem;'>"
                "Кэш пуст — нажмите «Подтянуть качество»</div>",
                unsafe_allow_html=True,
            )

    if _sync_clicked:
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
                    """Callback который обновляет label статуса по мере
                    завершения чанков (параллельно)."""
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
            "📭 **Нет данных.** Выберите период в шапке страницы и нажмите "
            "**«Подтянуть качество»** — кампании, ключевики и объявления подтянутся "
            "из Яндекс.Директа.\n\n"
            "Что вы увидите:\n"
            "- **Кампании** — CTR, CPC, конверсии-цели Метрики, CPL, отказы, глубина просмотров\n"
            "- **Ключевые слова** — топ по расходу, топ по конверсиям, топ убыточных\n"
            "- **Объявления (креативы)** — A/B-сравнение по CTR и конверсиям\n"
        )
    st.stop()

# Caption «период данных» убран как дубль кэш-инфо в топбаре.
# Caption про расход 10.65 vs главный дашборд — компактно одной строкой
# с tooltip, чтобы не съедать вертикальное пространство.
_qp_total_spend = (
    pd.to_numeric(_q_camp["spend_rub"], errors="coerce").sum()
    if "spend_rub" in _q_camp.columns else 0.0
)
if _qp_total_spend > 0:
    st.markdown(
        f"<div style='font-size:0.75rem; color:#6a737d; margin:-0.1rem 0 0.5rem 0;' "
        f"title='На главном дашборде расход может быть больше — там XLSX-выгрузки + API. "
        f"XLSX часто содержит архивные/закрытые кампании, которые API уже не возвращает. "
        f"Это не ошибка расчёта — разный охват источников.'>"
        f"ℹ️ Расход <b>{fmt_rub(_qp_total_spend)}</b> = только Я.Директ API "
        f"(на главном дашборде может быть больше — там XLSX+API; наведите для деталей)"
        f"</div>",
        unsafe_allow_html=True,
    )


# ============================================================
#       ИЕРАРХИЧЕСКАЯ ТАБЛИЦА: Кампания → Группа → Объявление
# ============================================================
# Одна большая treetable как в Roistat/CoMagic/Marilyn: плюсики
# раскрывают уровни. Все метрики видны на каждой строке. Никаких
# вкладок, никаких подкаталогов — один экран, полная картина.

if _q_camp.empty:
    st.info("Нет данных по кампаниям. Подтяните данные кнопкой в шапке выше.")
    st.stop()


# ─── Нормализация и агрегаты ──────────────────────────────────
def _to_num(df: pd.DataFrame, cols: tuple) -> pd.DataFrame:
    """Приводит указанные колонки к числовым типам IN-PLACE и возвращает
    тот же df. Вызывающий код ОБЯЗАН передавать копию (`.copy()`) если
    оригинал важен — иначе мутируется кэшированный объект из
    `load_quality_cache`, что ломает другие страницы.
    """
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
    tooltip="Достижения целей Я.Метрики, отмеченных как «Основные» в кампаниях Я.Директа "
            "(обычно user_payment-paid — успешная оплата, или e_purchase — e-commerce покупка). "
            "Это не клики, а реальные целевые действия после клика. "
            "Какая именно цель учитывается — см. настройки каждой кампании в direct.yandex.ru.",
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

# Префиксы в имени узла на 3-м уровне — чтобы AgGrid визуально различал
# параллельные ветки «объявление» и «ключ» внутри одной группы.
AD_PREFIX = "📰 "
KW_PREFIX = "🔑 "

for _, cr in campaigns_sorted.iterrows():
    camp_name = str(cr.get("campaign", "—") or "—")
    # ─── Уровень 1: Кампания ─────────────────────────────────
    rows.append({
        "path":         [camp_name],
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
    })

    # Все группы этой кампании — берём union из _ad и _kw_all
    camp_ads = _ad[_ad["campaign"] == camp_name] if not _ad.empty else pd.DataFrame()
    camp_kws = _kw_all[_kw_all["campaign"] == camp_name] if not _kw_all.empty else pd.DataFrame()
    group_names = set()
    if not camp_ads.empty:
        group_names.update(camp_ads["ad_group"].dropna().astype(str).unique())
    if not camp_kws.empty:
        group_names.update(camp_kws["ad_group"].dropna().astype(str).unique())

    for grp_name in sorted(group_names):
        grp_ads = camp_ads[camp_ads["ad_group"] == grp_name] if not camp_ads.empty else pd.DataFrame()
        grp_kws = camp_kws[camp_kws["ad_group"] == grp_name] if not camp_kws.empty else pd.DataFrame()

        # ─── Уровень 2: Группа (агрегат из объявлений) ───────
        # Метрики берём из объявлений (полные); если объявлений нет,
        # пересчитываем из ключевиков (тоже даёт impressions/clicks/spend).
        src = grp_ads if not grp_ads.empty else grp_kws
        g_impr = float(src["impressions"].sum()) if "impressions" in src else 0.0
        g_clk  = float(src["clicks"].sum())      if "clicks"      in src else 0.0
        g_spnd = float(src["spend_rub"].sum())   if "spend_rub"   in src else 0.0
        g_conv = float(src["conversions"].sum()) if "conversions" in src else 0.0
        rows.append({
            "path":         [camp_name, str(grp_name)],
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

        # ─── Уровень 3a: Объявления внутри группы ────────────
        for _, ar in grp_ads.sort_values("spend_rub", ascending=False).iterrows():
            ad_id = ar.get("ad_id", "—")
            rows.append({
                "path":         [camp_name, str(grp_name), f"{AD_PREFIX}#{ad_id}"],
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

        # ─── Уровень 3b: Ключевые фразы внутри группы ────────
        # Ключи в Я.Директе привязаны к ГРУППЕ (а не к объявлению),
        # поэтому на 3-м уровне параллельно с объявлениями. У ключа
        # имя = criterion (текст фразы); добавляем тип соответствия
        # в скобках если есть.
        for _, kr in grp_kws.sort_values("spend_rub", ascending=False).iterrows():
            crit = str(kr.get("criterion", "—") or "—")
            mt = kr.get("match_type", "") or ""
            label = f"{KW_PREFIX}{crit}" + (f" [{mt}]" if mt else "")
            rows.append({
                "path":         [camp_name, str(grp_name), label],
                "level":        "🔑 Ключ",
                "impressions":  float(kr.get("impressions", 0) or 0),
                "clicks":       float(kr.get("clicks", 0) or 0),
                "ctr":          float(kr.get("ctr", 0) or 0),
                "spend_rub":    float(kr.get("spend_rub", 0) or 0),
                "avg_cpc":      float(kr.get("avg_cpc", 0) or 0),
                "conversions":  float(kr.get("conversions", 0) or 0),
                "conversion_rate": float(kr.get("conversion_rate", 0) or 0),
                "cpl":          float(kr.get("cost_per_conversion", 0) or 0),
                "bounce_rate":  0.0,
            })

tree_df = pd.DataFrame(rows)


# ─── Сама AgGrid treetable ────────────────────────────────────
# Заголовок секции убран — название уже в первой колонке таблицы.
# Подсказка про плюсики — компактно одной строкой.
st.markdown(
    "<div style='font-size:0.75rem; color:#6a737d; margin:0.4rem 0 0.3rem 0;'>"
    "💡 Раскрывайте строки кампаний плюсиками: <b>группы объявлений → "
    "📰 объявления и 🔑 ключевые фразы</b>. Все метрики видны на каждой строке."
    "</div>",
    unsafe_allow_html=True,
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
        # autoGroupColumnDef — это первая колонка дерева (имя кампании/
        # группы/объявления). Закреплена слева, flex=2 — занимает в 2 раза
        # больше места чем обычная колонка метрики.
        "autoGroupColumnDef": {
            "headerName": "Кампания / Группа / Объявление / Ключ",
            "minWidth": 320,
            "flex": 2.5,
            "pinned": "left",
            "cellRendererParams": {
                "suppressCount": True,  # не показывать "(N)" рядом с группой
            },
        },
        "defaultColDef": {
            "sortable": True,
            "resizable": True,
            "filter": False,
            "flex": 1,           # все колонки делят оставшееся место поровну
            "minWidth": 80,      # но не уже 80px (иначе цифры обрежутся)
            "cellStyle": {"textAlign": "right", "fontVariantNumeric": "tabular-nums"},
        },
        "rowHeight": 32,         # компактнее
        "headerHeight": 36,
        # headerTooltip — при наведении на заголовок колонки в AgGrid
        # показывается подсказка. Объясняем что именно показывает каждая метрика.
        "columnDefs": [
            {"field": "level", "headerName": "Тип", "hide": True},
            {"field": "impressions",    "headerName": "Показы",  "valueFormatter": fmt_int,   "type": "numericColumn", "minWidth":  95,
             "headerTooltip": "Сколько раз объявление было показано пользователям в поиске или РСЯ."},
            {"field": "clicks",         "headerName": "Клики",   "valueFormatter": fmt_int,   "type": "numericColumn", "minWidth":  85,
             "headerTooltip": "Сколько раз пользователи кликнули по объявлению и перешли на сайт."},
            {"field": "ctr",            "headerName": "CTR",     "valueFormatter": fmt_pct,   "type": "numericColumn", "minWidth":  75,
             "headerTooltip": "Click-Through Rate = клики / показы × 100%. Кликабельность объявления. Для поиска норма 5-15%, для РСЯ 0.3-1%."},
            {"field": "spend_rub",      "headerName": "Расход",  "valueFormatter": fmt_money, "type": "numericColumn", "minWidth": 115, "flex": 1.3,
             "headerTooltip": "Сумма списаний за клики в Я.Директе (с НДС)."},
            {"field": "avg_cpc",        "headerName": "CPC",     "valueFormatter": fmt_cpc,   "type": "numericColumn", "minWidth":  85,
             "headerTooltip": "Cost Per Click = расход / клики. Средняя цена клика."},
            {"field": "conversions",    "headerName": "Конв.",   "valueFormatter": fmt_int,   "type": "numericColumn", "minWidth":  75,
             "headerTooltip": "Достижения целей Я.Метрики, отмеченных как ОСНОВНЫЕ в настройках кампании Я.Директа. В UFO Hosting обычно это user_payment-paid (успешная оплата) и/или e_purchase. Не путать с кликами — конверсия = клиент сделал целевое действие."},
            {"field": "conversion_rate","headerName": "CR",      "valueFormatter": fmt_pct,   "type": "numericColumn", "minWidth":  75,
             "headerTooltip": "Conversion Rate = конверсии / клики × 100%. Какая доля кликнувших дошла до целевого действия. >5% хорошо, <1% плохо."},
            {"field": "cpl",            "headerName": "CPL",     "valueFormatter": fmt_money, "type": "numericColumn", "minWidth": 100,
             "headerTooltip": "Cost Per Lead = расход / конверсии. Сколько стоит привлечь 1 клиента, который сделал целевое действие. Чем меньше — тем эффективнее."},
            {"field": "bounce_rate",    "headerName": "Отказы",  "valueFormatter": fmt_pct,   "type": "numericColumn", "minWidth":  80,
             "headerTooltip": "% визитов длительностью <15 секунд (одна страница, без действий). >40% — плохо (нерелевантные клики). <20% — хорошо."},
        ],
    }

    # streamlit-aggrid==0.3.4.post3, передаём DataFrame.
    # fit_columns_on_grid_load=True — растягивает колонки по flex
    # на всю ширину контейнера, без горизонтального скролла.
    AgGrid(
        tree_df,
        gridOptions=grid_options,
        allow_unsafe_jscode=True,
        height=720,
        theme="streamlit",
        fit_columns_on_grid_load=True,
    )

    # ─── Видимая шпаргалка прямо под таблицей ─────────────────
    # Раньше была через st.expander (скрытая) — пользователь не находил.
    # Теперь — всегда видимая компактная плашка с расшифровкой ключевых
    # метрик прямо здесь.
    st.markdown(
        """
        <div style='background:#f6f8fa; border:1px solid #e1e4e8; border-radius:8px;
                    padding:0.7rem 1rem; margin-top:0.8rem; font-size:0.82rem;
                    line-height:1.5; color:#24292f;'>
          <b>📖 Что означают колонки:</b><br>
          <b>CTR</b> = клики ÷ показы (кликабельность; <b>норма Поиск 5–15%, РСЯ 0.3–1%</b>) ·
          <b>CPC</b> = расход ÷ клики (цена клика) ·
          <b>Конв.</b> = достижения целей Я.Метрики, отмеченных как «Основные» в кампании
          (в UFO Hosting обычно <code>user_payment-paid</code> или <code>e_purchase</code>) ·
          <b>CR</b> = конверсии ÷ клики (<b>норма &gt;5% хорошо, &lt;1% плохо</b>) ·
          <b>CPL</b> = расход ÷ конверсии (цена 1 клиента; <b>сравнивайте с LTV</b>) ·
          <b>Отказы</b> = % визитов &lt;15 сек (<b>&lt;20% хорошо, &gt;40% плохо</b>)
          <br><br>
          <b>⚠️ Что именно считается конверсией в каждой кампании</b> —
          смотри direct.yandex.ru → кампания → <b>Стратегия → Цели</b>.
          Все 24 цели UFO Hosting — в metrika.yandex.ru → Настройка → Цели.
        </div>
        """,
        unsafe_allow_html=True,
    )

