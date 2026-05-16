"""
UFO Hosting — Управленческий дашборд окупаемости рекламы.

Запуск локально:    streamlit run src/app.py
Деплой в облако:    Streamlit Community Cloud (привязать GitHub-репо)
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import streamlit as st

# Базовая конфигурация страницы должна быть ПЕРВОЙ — чтобы при любых ошибках
# импорта пользователь видел хотя бы заголовок и сообщение.
st.set_page_config(
    page_title="UFO Hosting · Окупаемость рекламы",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
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
    .main .block-container {{
        padding-top: 1.4rem; padding-bottom: 2.4rem; max-width: 1500px;
    }}

    /* Заголовок */
    h1 {{
        font-weight: 700; letter-spacing: -0.4px; color: {PALETTE['text']};
    }}
    .ufo-hero {{
        display: flex; align-items: flex-end; justify-content: space-between;
        padding: 0.4rem 0 1.3rem 0;
        border-bottom: 1px solid {PALETTE['border']};
        margin-bottom: 1.6rem;
    }}
    .ufo-hero h1 {{ margin: 0; font-size: 1.75rem; color: {PALETTE['text']}; letter-spacing: -0.5px; }}
    .ufo-hero .ufo-sub {{
        color: {PALETTE['muted']}; font-size: 0.85rem; margin-top: 0.3rem;
        letter-spacing: 0.2px;
    }}
    .ufo-hero .ufo-period-badge {{
        background: {PALETTE['panel']}; color: {PALETTE['text']};
        padding: 0.45rem 0.9rem; border-radius: 6px; font-weight: 600;
        font-size: 0.82rem; border: 1px solid {PALETTE['border']};
        white-space: nowrap;
    }}

    /* KPI плитки */
    .kpi-card {{
        background: #ffffff;
        border: 1px solid {PALETTE['border']};
        border-radius: 10px;
        padding: 1.05rem 1.2rem;
        height: 100%;
        transition: border-color 0.15s ease;
    }}
    .kpi-card:hover {{ border-color: #8c959f; }}
    .kpi-card .kpi-label {{
        color: {PALETTE['muted']}; font-size: 0.72rem; text-transform: uppercase;
        letter-spacing: 0.4px; margin-bottom: 0.5rem; font-weight: 600;
    }}
    .kpi-card .kpi-value {{
        color: {PALETTE['text']}; font-size: 1.65rem; font-weight: 700; line-height: 1.15;
    }}
    .kpi-card .kpi-delta {{
        margin-top: 0.45rem; font-size: 0.78rem; color: {PALETTE['muted']};
    }}
    .kpi-card.primary .kpi-value {{ color: {PALETTE['primary']}; }}
    .kpi-card.green   .kpi-value {{ color: {PALETTE['green']}; }}
    .kpi-card.red     .kpi-value {{ color: {PALETTE['red']}; }}
    .kpi-card.orange  .kpi-value {{ color: {PALETTE['orange']}; }}
    .kpi-delta.up   {{ color: {PALETTE['green']}; font-weight: 600; }}
    .kpi-delta.down {{ color: {PALETTE['red']}; font-weight: 600; }}
    .kpi-delta.neutral {{ color: {PALETTE['muted']}; }}

    /* Секции */
    .section-title {{
        margin: 1.8rem 0 0.7rem 0; font-size: 0.92rem; font-weight: 700;
        color: {PALETTE['muted']}; text-transform: uppercase; letter-spacing: 0.5px;
    }}

    /* Sidebar */
    [data-testid="stSidebar"] {{
        background: {PALETTE['panel']}; border-right: 1px solid {PALETTE['border']};
    }}
    [data-testid="stSidebar"] h1 {{ font-size: 1.2rem; }}

    /* Дефолтные st.metric */
    [data-testid="stMetricValue"] {{ font-size: 1.5rem; font-weight: 700; }}
    [data-testid="stMetricLabel"] {{
        font-size: 0.72rem; color: {PALETTE['muted']};
        text-transform: uppercase; letter-spacing: 0.4px; font-weight: 600;
    }}

    .streamlit-expanderHeader {{ font-weight: 600; }}

    /* Footer */
    .ufo-footer {{
        color: {PALETTE['muted']}; font-size: 0.78rem; text-align: center;
        margin-top: 2rem; padding-top: 1rem;
        border-top: 1px solid {PALETTE['border']};
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
    if v is None or pd.isna(v):
        return "—"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f} млн{suffix}"
    if abs(v) >= 1_000:
        return f"{v/1_000:.0f}K{suffix}"
    return f"{v:,.0f}{suffix}".replace(",", " ")


def fmt_num(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{int(v):,}".replace(",", " ")


def kpi_card(label: str, value: str, delta: str = "", kind: str = "", delta_kind: str = "neutral"):
    """Карточка KPI с фиксированным стилем."""
    klass = f"kpi-card {kind}".strip()
    delta_html = f'<div class="kpi-delta {delta_kind}">{delta}</div>' if delta else ""
    return f"""
    <div class="{klass}">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value">{value}</div>
      {delta_html}
    </div>
    """


# ============================================================
#                       Persistent storage (HF Dataset)
# ============================================================

@st.cache_resource(show_spinner="Синхронизирую данные из облака…")
def _initial_storage_sync():
    if not storage.is_enabled():
        return {"enabled": False}
    storage.ensure_dataset_exists()
    return storage.sync_down()


_sync_info = _initial_storage_sync()


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
            st.caption(f"💾 Облако · {n_o_disk} файлов с заказами синхронизировано")
        if st.button("Обновить из облака", use_container_width=True, key="resync_btn", type="secondary"):
            st.cache_resource.clear()
            st.cache_data.clear()
            st.rerun()
    else:
        st.caption(f"Локально: {n_o_disk} файлов с заказами")

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
            if st.button("Подтянуть статистику", use_container_width=True, key="yd_sync_btn", type="primary"):
                try:
                    from yandex_direct import fetch_campaign_report, to_ads_dataframe
                    with st.spinner("Тяну отчёт из Я.Директ (до минуты)…"):
                        raw = fetch_campaign_report(
                            _yd_creds_global,
                            date_from=str(sync_from),
                            date_to=str(sync_to),
                        )
                        api_ads = to_ads_dataframe(raw)
                    if api_ads.empty:
                        st.warning("API вернул пустой отчёт.")
                    else:
                        st.session_state["yd_api_ads"] = api_ads
                        st.success(
                            f"Подтянуто {len(api_ads)} строк, "
                            f"{api_ads['spend_rub'].sum():,.0f} ₽".replace(",", " ")
                        )
                        st.cache_data.clear()
                        st.rerun()
                except Exception as e:
                    st.error(str(e))
            if "yd_api_ads" in st.session_state and not st.session_state["yd_api_ads"].empty:
                n = len(st.session_state["yd_api_ads"])
                st.caption(f"В сессии данных из API: {n} строк")

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
    st.stop()


# ============================================================
#                       Sidebar: фильтры (после загрузки)
# ============================================================

with placeholder_filters:
    st.markdown("**Фильтры**")

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
    overall_min = min(pay_min, ad_min)
    overall_max = max(pay_max, ad_max)

    period = st.date_input(
        "Период",
        value=(overall_min, overall_max),
        min_value=overall_min, max_value=overall_max,
        format="DD.MM.YYYY",
    )
    if isinstance(period, tuple) and len(period) == 2:
        d_from, d_to = pd.Timestamp(period[0]), pd.Timestamp(period[1])
    else:
        d_from, d_to = pd.Timestamp(overall_min), pd.Timestamp(overall_max)

    attribution_pct = st.slider(
        "Атрибуция платного трафика, %",
        min_value=10, max_value=100, value=100, step=5,
        help="100% = весь доход приписываем рекламе. Уменьшите, если значимая часть клиентов приходит из SEO/прямых.",
    )
    attribution_factor = attribution_pct / 100.0


orders = M.filter_orders_by_period(orders_all, d_from, d_to)
# объединяем XLSX и API данные
ads_combined = ads_all
if "yd_api_ads" in st.session_state and not st.session_state["yd_api_ads"].empty:
    ads_combined = pd.concat([ads_all, st.session_state["yd_api_ads"]], ignore_index=True)
    # дедуплицируем по (month, campaign) — API данные приоритетнее
    ads_combined = ads_combined.drop_duplicates(subset=["month", "campaign"], keep="last")
ads = M.filter_ads_by_period(ads_combined, d_from, d_to)
ads_all = ads_combined  # чтобы остальной код видел совместный набор


# ============================================================
#                       Hero
# ============================================================

period_label = f"{d_from:%d.%m.%Y} – {d_to:%d.%m.%Y}"
st.markdown(
    f"""
    <div class="ufo-hero">
      <div>
        <h1>Окупаемость рекламы</h1>
        <div class="ufo-sub">UFO Hosting · Яндекс.Директ · LTV / CAC / Retention</div>
      </div>
      <div class="ufo-period-badge">{period_label}</div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
#                       Главные KPI
# ============================================================

ck = M.comparable_kpi(orders, ads)
kf = M.compute_kpi(orders, ads)
if ck is None:
    ck = kf

revenue_attr = ck.revenue * attribution_factor
net = revenue_attr - ck.spend
romi_pct = (net / ck.spend * 100) if ck.spend else 0.0
cac = ck.spend / max(ck.new_clients, 1)
ltv_cac = ck.arpu / cac if cac else 0.0

# Row 1 — главные 4 плитки
c1, c2, c3, c4 = st.columns(4)
c1.markdown(kpi_card(
    "Расход на Директ",
    fmt_rub(ck.spend),
    f"за {period_label}", kind="red", delta_kind="neutral",
), unsafe_allow_html=True)
c2.markdown(kpi_card(
    "Доход (оплаты)",
    fmt_rub(ck.revenue),
    f"{ck.orders_paid:,} оплат".replace(",", " "), kind="green",
), unsafe_allow_html=True)
romi_kind = "up" if net >= 0 else "down"
romi_arrow = "↑" if net >= 0 else "↓"
romi_color_kind = "green" if net >= 0 else "red"
c3.markdown(kpi_card(
    "ROMI",
    f"{romi_pct:+.1f}%",
    f"{romi_arrow} {fmt_rub(abs(net))} {'прибыли' if net >= 0 else 'к окупаемости'}",
    kind=romi_color_kind, delta_kind=romi_kind,
), unsafe_allow_html=True)
c4.markdown(kpi_card(
    "Клиентов",
    fmt_num(ck.unique_clients),
    f"новых: {ck.new_clients} · повторных: {ck.repeat_clients}",
    kind="primary",
), unsafe_allow_html=True)

st.markdown("<div style='height: 0.8rem'></div>", unsafe_allow_html=True)

# Row 2 — второстепенные 4 плитки
c5, c6, c7, c8 = st.columns(4)
c5.markdown(kpi_card("CAC", fmt_rub(cac), "стоимость нового клиента"), unsafe_allow_html=True)
c6.markdown(kpi_card("ARPU", fmt_rub(ck.arpu), "доход на клиента"), unsafe_allow_html=True)
c7.markdown(kpi_card("Средний чек", fmt_rub(ck.avg_check), f"{ck.avg_orders_per_client:.2f} оплат/клиент"), unsafe_allow_html=True)
ltv_kind = "up" if ltv_cac >= 1 else "down"
ltv_color = "green" if ltv_cac >= 1 else "red"
c8.markdown(kpi_card(
    "LTV / CAC",
    f"{ltv_cac:.2f}×",
    "цель ≥ 1×, отлично ≥ 3×",
    kind=ltv_color, delta_kind=ltv_kind,
), unsafe_allow_html=True)


# ============================================================
#                       Сравнение с прошлым периодом
# ============================================================

# Сравнение всегда: последний месяц с платежами vs предпоследний
_paid_orders_all = orders_all[orders_all["is_paid"]]
pc = None
if not _paid_orders_all.empty:
    last_month_dt = _paid_orders_all["payment_date"].max().to_period("M").to_timestamp()
    last_from = last_month_dt
    last_to = last_month_dt + pd.offsets.MonthEnd(0)
    prev_from = (last_month_dt - pd.DateOffset(months=1))
    prev_to = last_month_dt - pd.Timedelta(days=1)
    cur_kpi = M.compute_kpi(
        M.filter_orders_by_period(orders_all, last_from, last_to),
        M.filter_ads_by_period(ads_all, last_from, last_to),
    )
    prev_kpi = M.compute_kpi(
        M.filter_orders_by_period(orders_all, prev_from, prev_to),
        M.filter_ads_by_period(ads_all, prev_from, prev_to),
    )

    def _dpct(a, b):
        if b is None or pd.isna(b) or b == 0:
            return None
        return (a - b) / abs(b) * 100

    RU_MONTHS_FULL = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                      "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    pc = {
        "current": cur_kpi, "previous": prev_kpi,
        "current_label": f"{RU_MONTHS_FULL[last_from.month]} {last_from.year}",
        "prev_label": f"{RU_MONTHS_FULL[prev_from.month]} {prev_from.year}",
        "deltas": {
            "spend": _dpct(cur_kpi.spend, prev_kpi.spend),
            "revenue": _dpct(cur_kpi.revenue, prev_kpi.revenue),
            "new_clients": _dpct(cur_kpi.new_clients, prev_kpi.new_clients),
            "arpu": _dpct(cur_kpi.arpu, prev_kpi.arpu),
            "avg_check": _dpct(cur_kpi.avg_check, prev_kpi.avg_check),
        },
    }

if pc:
    st.markdown(
        f'<div class="section-title">{pc["current_label"]} vs {pc["prev_label"]}</div>',
        unsafe_allow_html=True,
    )

    def _delta_html(label, current_fmt, delta_val, *, invert=False):
        if delta_val is None or pd.isna(delta_val):
            return kpi_card(label, current_fmt, "—", delta_kind="neutral")
        arrow = "↑" if delta_val >= 0 else "↓"
        # invert=True если для метрики «расход» рост — это плохо
        positive = (delta_val >= 0) if not invert else (delta_val <= 0)
        delta_kind = "up" if positive else "down"
        return kpi_card(
            label, current_fmt,
            f"{arrow} {abs(delta_val):.1f}% vs прошлый",
            delta_kind=delta_kind,
        )

    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    cc1.markdown(_delta_html(
        "Расход",
        fmt_rub(pc["current"].spend),
        pc["deltas"]["spend"], invert=True,
    ), unsafe_allow_html=True)
    cc2.markdown(_delta_html(
        "Доход",
        fmt_rub(pc["current"].revenue),
        pc["deltas"]["revenue"],
    ), unsafe_allow_html=True)
    cc3.markdown(_delta_html(
        "Новых клиентов",
        fmt_num(pc["current"].new_clients),
        pc["deltas"]["new_clients"],
    ), unsafe_allow_html=True)
    cc4.markdown(_delta_html(
        "ARPU",
        fmt_rub(pc["current"].arpu),
        pc["deltas"]["arpu"],
    ), unsafe_allow_html=True)
    cc5.markdown(_delta_html(
        "Средний чек",
        fmt_rub(pc["current"].avg_check),
        pc["deltas"]["avg_check"],
    ), unsafe_allow_html=True)


# ============================================================
#                       Главный график: динамика
# ============================================================

st.markdown('<div class="section-title">Динамика по месяцам</div>', unsafe_allow_html=True)

ms = M.monthly_summary(orders, ads)
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
                  <div style='font-size:0.72rem; color:{PALETTE['muted']};'>{email} · {row['orders']} оплат</div>
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
        f"**{old_orders_cnt:,}** повторных · **{new_orders_cnt:,}** новых оплат  \n"
        f"Для хостинга 60%+ — сильный показатель удержания.".replace(",", " ")
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

ctx_full = M.compute_kpi(orders, ads)
st.markdown(
    f'<div class="ufo-footer">'
    f'Контекст всего периода: расход {fmt_rub(ctx_full.spend)} · '
    f'доход {fmt_rub(ctx_full.revenue)} · '
    f'gap покупка→оплата {ctx_full.payment_to_purchase_gap*100:.1f}%'
    f'</div>',
    unsafe_allow_html=True,
)
