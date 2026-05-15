"""
UFO Hosting — Управленческий дашборд окупаемости рекламы.

Запуск локально:    streamlit run src/app.py
Деплой в облако:    Streamlit Community Cloud (привязать GitHub-репо)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import (
    ADS_DIR, ORDERS_DIR,
    ads_monthly_totals, load_ads, load_orders,
)
import metrics as M
from yandex_direct import get_credentials as yd_creds


# ============================================================
#                       Конфигурация и стили
# ============================================================

st.set_page_config(
    page_title="UFO Hosting · Окупаемость рекламы",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

PALETTE = {
    "bg": "#0a0e27",
    "panel": "#141a3a",
    "text": "#e8ebf5",
    "muted": "#9ba3d4",
    "gold": "#f4c95d",
    "green": "#7ed7a0",
    "coral": "#ff8a73",
    "blue": "#7aa6ff",
    "violet": "#b294ff",
}

st.markdown(
    f"""
    <style>
    .stApp {{
        background: radial-gradient(circle at 15% 0%, #1a1f4a 0%, {PALETTE['bg']} 55%);
    }}
    .main .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px; }}

    /* Заголовок */
    h1 {{ font-weight: 800; letter-spacing: -0.5px; }}
    .ufo-hero {{
        display: flex; align-items: center; justify-content: space-between;
        padding: 1.1rem 1.4rem; border-radius: 16px;
        background: linear-gradient(135deg, rgba(244,201,93,0.10), rgba(122,166,255,0.06));
        border: 1px solid rgba(244,201,93,0.18);
        margin-bottom: 1.2rem;
    }}
    .ufo-hero h1 {{ margin: 0; font-size: 1.85rem; }}
    .ufo-hero .ufo-sub {{ color: {PALETTE['muted']}; font-size: 0.95rem; margin-top: 0.2rem; }}
    .ufo-hero .ufo-period-badge {{
        background: rgba(244,201,93,0.15); color: {PALETTE['gold']};
        padding: 0.35rem 0.8rem; border-radius: 999px; font-weight: 600; font-size: 0.85rem;
    }}

    /* KPI плитки */
    .kpi-card {{
        background: rgba(20, 26, 58, 0.65);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(155, 163, 212, 0.12);
        border-radius: 14px;
        padding: 1.1rem 1.2rem;
        height: 100%;
    }}
    .kpi-card .kpi-label {{
        color: {PALETTE['muted']}; font-size: 0.78rem; text-transform: uppercase;
        letter-spacing: 0.5px; margin-bottom: 0.45rem;
    }}
    .kpi-card .kpi-value {{
        color: {PALETTE['text']}; font-size: 1.85rem; font-weight: 700; line-height: 1.1;
    }}
    .kpi-card .kpi-delta {{
        margin-top: 0.4rem; font-size: 0.82rem;
    }}
    .kpi-card.primary {{ border: 1px solid rgba(244,201,93,0.35); }}
    .kpi-card.primary .kpi-value {{ color: {PALETTE['gold']}; }}
    .kpi-card.green .kpi-value  {{ color: {PALETTE['green']}; }}
    .kpi-card.coral .kpi-value  {{ color: {PALETTE['coral']}; }}
    .kpi-card.blue  .kpi-value  {{ color: {PALETTE['blue']}; }}
    .kpi-delta.up   {{ color: {PALETTE['green']}; }}
    .kpi-delta.down {{ color: {PALETTE['coral']}; }}
    .kpi-delta.neutral {{ color: {PALETTE['muted']}; }}

    /* Секции */
    .section-title {{
        margin: 1.6rem 0 0.8rem 0; font-size: 1.15rem; font-weight: 700;
        color: {PALETTE['text']}; display: flex; align-items: center; gap: 0.5rem;
    }}
    .section-title:before {{
        content: ""; width: 4px; height: 18px; border-radius: 2px;
        background: linear-gradient(180deg, {PALETTE['gold']}, {PALETTE['blue']});
    }}

    /* Sidebar */
    [data-testid="stSidebar"] {{ background: rgba(10, 14, 39, 0.95); }}
    [data-testid="stSidebar"] .stMarkdown h1 {{ font-size: 1.4rem; }}

    /* Сделать дефолтные st.metric менее «жирными» */
    [data-testid="stMetricValue"] {{ font-size: 1.6rem; font-weight: 700; }}
    [data-testid="stMetricLabel"] {{ font-size: 0.78rem; color: {PALETTE['muted']}; text-transform: uppercase; }}

    /* Меньше отступа в expander */
    .streamlit-expanderHeader {{ font-weight: 600; }}

    /* Footer */
    .ufo-footer {{
        color: {PALETTE['muted']}; font-size: 0.78rem; text-align: center;
        margin-top: 2rem; padding-top: 1rem;
        border-top: 1px solid rgba(155, 163, 212, 0.1);
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(20,26,58,0.4)",
    font=dict(color=PALETTE["text"], family="Inter, -apple-system, sans-serif"),
    margin=dict(t=50, l=10, r=10, b=10),
    xaxis=dict(gridcolor="rgba(155,163,212,0.08)", zerolinecolor="rgba(155,163,212,0.15)"),
    yaxis=dict(gridcolor="rgba(155,163,212,0.08)", zerolinecolor="rgba(155,163,212,0.15)"),
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
#                       Sidebar
# ============================================================

with st.sidebar:
    st.markdown("# 🛰️ UFO Hosting")
    st.caption("Окупаемость Яндекс.Директ и LTV клиентов")
    st.divider()

    st.markdown("**📥 Загрузить выгрузки**")
    uploaded_orders = st.file_uploader(
        "CSV выгрузки заказов",
        type=["csv"], accept_multiple_files=True,
        key="orders_upload",
        help="Можно загрузить сразу несколько файлов — дубликаты по ID покупки убираются автоматически.",
    )
    uploaded_ads = st.file_uploader(
        "XLSX отчёты Яндекс.Директ",
        type=["xlsx"], accept_multiple_files=True,
        key="ads_upload",
    )

    st.caption(
        f"Файлы на диске сервера:  \n"
        f"📁 заказов: {len(list(ORDERS_DIR.glob('*.csv')))}  \n"
        f"📁 рекламы: {len(list(ADS_DIR.glob('*.xlsx')))}"
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
if orders_all.empty and ads_all.empty:
    st.markdown(
        """
        <div class="ufo-hero">
          <div>
            <h1>🛰️ UFO Hosting · Дашборд окупаемости</h1>
            <div class="ufo-sub">Загрузите выгрузки в сайдбаре слева, чтобы увидеть отчёт.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        "**Что загружать:**\n\n"
        "• **CSV** — выгрузки «Содержимое заказов» из админки UFO Hosting (можно несколько за разные периоды)\n\n"
        "• **XLSX** — отчёты по рекламным кампаниям Яндекс.Директ (помесячно)\n\n"
        "Дашборд сам разберёт и склеит данные, дедуплицирует пересекающиеся периоды."
    )
    st.stop()


# ============================================================
#                       Sidebar: фильтры (после загрузки)
# ============================================================

with placeholder_filters:
    st.markdown("**🎛️ Фильтры**")

    pay_min = orders_all["payment_date"].min().date() if not orders_all.empty else ads_all["month"].min().date()
    pay_max = orders_all["payment_date"].max().date() if not orders_all.empty else ads_all["month"].max().date()
    ad_min = ads_all["month"].min().date() if not ads_all.empty else pay_min
    ad_max = ads_all["month"].max().date() if not ads_all.empty else pay_max
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

    st.divider()

    # Yandex Direct status
    yd = yd_creds()
    if yd:
        st.success("🔗 Я.Директ подключён")
        st.caption("Статистика будет тянуться напрямую из API (после реализации Sync).")
    else:
        st.caption(
            "🔌 Я.Директ API не подключён.  \n"
            "Чтобы включить — добавьте `YANDEX_DIRECT_TOKEN` в Streamlit Secrets."
        )


orders = M.filter_orders_by_period(orders_all, d_from, d_to)
ads = M.filter_ads_by_period(ads_all, d_from, d_to)


# ============================================================
#                       Hero
# ============================================================

period_label = f"{d_from:%d.%m.%Y} – {d_to:%d.%m.%Y}"
st.markdown(
    f"""
    <div class="ufo-hero">
      <div>
        <h1>🛰️ Окупаемость рекламы · UFO Hosting</h1>
        <div class="ufo-sub">Яндекс.Директ · LTV · CAC · Retention</div>
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
    f"за {period_label}", kind="coral", delta_kind="neutral",
), unsafe_allow_html=True)
c2.markdown(kpi_card(
    "Доход (оплаты)",
    fmt_rub(ck.revenue),
    f"{ck.orders_paid:,} оплат".replace(",", " "), kind="green",
), unsafe_allow_html=True)
romi_kind = "up" if net >= 0 else "down"
romi_arrow = "↑" if net >= 0 else "↓"
c3.markdown(kpi_card(
    "ROMI",
    f"{romi_pct:+.1f}%",
    f"{romi_arrow} {fmt_rub(abs(net))} {'прибыли' if net >= 0 else 'к окупаемости'}",
    kind="primary", delta_kind=romi_kind,
), unsafe_allow_html=True)
c4.markdown(kpi_card(
    "Клиентов",
    fmt_num(ck.unique_clients),
    f"новых: {ck.new_clients} · повторных: {ck.repeat_clients}",
    kind="blue",
), unsafe_allow_html=True)

st.markdown("<div style='height: 0.8rem'></div>", unsafe_allow_html=True)

# Row 2 — второстепенные 4 плитки
c5, c6, c7, c8 = st.columns(4)
c5.markdown(kpi_card("CAC", fmt_rub(cac), "стоимость нового клиента"), unsafe_allow_html=True)
c6.markdown(kpi_card("ARPU", fmt_rub(ck.arpu), "доход на клиента"), unsafe_allow_html=True)
c7.markdown(kpi_card("Средний чек", fmt_rub(ck.avg_check), f"{ck.avg_orders_per_client:.2f} оплат/клиент"), unsafe_allow_html=True)
ltv_kind = "up" if ltv_cac >= 1 else "down"
c8.markdown(kpi_card(
    "LTV / CAC",
    f"{ltv_cac:.2f}×",
    "цель ≥ 1×, отлично ≥ 3×",
    delta_kind=ltv_kind,
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
        name="Расход на Директ", marker_color=PALETTE["coral"],
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
        line=dict(color=PALETTE["gold"], width=3), marker=dict(size=8),
        hovertemplate="<b>%{x}</b><br>Новых клиентов: %{y}<extra></extra>",
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        height=420, barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis_title="Рубли",
        yaxis2=dict(
            title="Новых клиентов", overlaying="y", side="right",
            gridcolor="rgba(155,163,212,0.05)",
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
                PALETTE["gold"], PALETTE["blue"], PALETTE["green"],
                PALETTE["violet"], PALETTE["coral"], "#5fb3d4", "#d4945f", "#888fa8",
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
                f"""<div style='display:flex; justify-content:space-between; padding:0.4rem 0.6rem;
                margin-bottom:0.3rem; background:rgba(20,26,58,0.55); border-radius:8px;
                border:1px solid rgba(155,163,212,0.08);'>
                <div>
                  <div style='font-weight:600; color:{PALETTE['text']};'>{name}</div>
                  <div style='font-size:0.72rem; color:{PALETTE['muted']};'>{email} · {row['orders']} оплат</div>
                </div>
                <div style='text-align:right;'>
                  <div style='font-weight:700; color:{PALETTE['gold']};'>{fmt_rub(row['total_paid'])}</div>
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
        number={"suffix": "%", "font": {"color": PALETTE["gold"], "size": 36}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": PALETTE["muted"], "tickfont": {"color": PALETTE["muted"]}},
            "bar": {"color": PALETTE["gold"]},
            "bgcolor": "rgba(20,26,58,0.5)",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 30], "color": "rgba(255,138,115,0.18)"},
                {"range": [30, 60], "color": "rgba(244,201,93,0.18)"},
                {"range": [60, 100], "color": "rgba(126,215,160,0.18)"},
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
            [0.0, "rgba(20,26,58,0.4)"],
            [0.3, "rgba(122,166,255,0.4)"],
            [0.7, "rgba(244,201,93,0.6)"],
            [1.0, "rgba(126,215,160,0.95)"],
        ],
        hovertemplate="<b>Когорта %{y}</b><br>%{x}<br>Доход: %{z:,.0f} ₽<extra></extra>",
        showscale=False,
        textfont=dict(color=PALETTE["text"], size=11),
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
