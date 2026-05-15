"""
Streamlit-дашборд UFO Hosting: окупаемость рекламы и LTV клиентов.

Запуск:
    streamlit run src/app.py
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


# ============================================================
#                       Page config
# ============================================================

st.set_page_config(
    page_title="UFO Hosting — Окупаемость рекламы",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    [data-testid="stMetricValue"] { font-size: 1.7rem; }
    [data-testid="stMetricLabel"]  { font-size: 0.85rem; color: #5a5a5a; }
    h1 { font-weight: 700; }
    .kpi-note { color: #888; font-size: 0.78rem; margin-top: -0.4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
#                       Data loading
# ============================================================

@st.cache_data(show_spinner="Загружаю выгрузки заказов и отчёты по Директу…")
def load_all():
    orders = load_orders()
    ads = load_ads()
    return orders, ads


orders_all, ads_all = load_all()

if orders_all.empty:
    st.error(f"Не найдено CSV-выгрузок в `{ORDERS_DIR}`. Положите туда файлы и перезагрузите страницу.")
    st.stop()
if ads_all.empty:
    st.error(f"Не найдено XLSX-отчётов в `{ADS_DIR}`. Положите туда файлы и перезагрузите страницу.")
    st.stop()


# ============================================================
#                       Sidebar — фильтры
# ============================================================

with st.sidebar:
    st.title("🛰️ UFO Hosting")
    st.caption("Окупаемость Яндекс.Директ и аналитика LTV")
    st.divider()

    st.subheader("Период анализа")
    pay_min = orders_all["payment_date"].min().date()
    pay_max = orders_all["payment_date"].max().date()
    ad_min = ads_all["month"].min().date()
    ad_max = ads_all["month"].max().date()
    overall_min = min(pay_min, ad_min)
    overall_max = max(pay_max, ad_max)

    period = st.date_input(
        "Период (по дате платежа / месяцу расхода)",
        value=(overall_min, overall_max),
        min_value=overall_min,
        max_value=overall_max,
        format="DD.MM.YYYY",
    )
    if isinstance(period, tuple) and len(period) == 2:
        d_from, d_to = pd.Timestamp(period[0]), pd.Timestamp(period[1])
    else:
        d_from, d_to = pd.Timestamp(overall_min), pd.Timestamp(overall_max)

    st.subheader("Когортный анализ")
    cohort_basis = st.radio(
        "База когорты",
        ["registration", "first_payment"],
        format_func=lambda x: "По месяцу регистрации" if x == "registration" else "По месяцу первой оплаты",
        index=0,
        help=(
            "**Регистрация** — стандарт для SaaS/хостинга: показывает, как зарегистрированные в месяце M "
            "клиенты приносят деньги в M, M+1, M+2…\n\n"
            "**Первая оплата** — узкая когорта только из платящих клиентов, полезно когда регистрация и "
            "первый платёж сильно разнесены."
        ),
    )

    st.subheader("Атрибуция расхода на рекламу")
    paid_traffic_share = st.slider(
        "Доля платного трафика (%) от всех заходов",
        min_value=10, max_value=100, value=100, step=5,
        help=(
            "Если 100% — весь доход приписывается рекламе (оптимистичный ROMI). "
            "Если меньше — доход умножается на эту долю при сравнении с расходом "
            "(моделирует, что часть клиентов приходит из SEO / прямых заходов)."
        ),
    )
    attribution_factor = paid_traffic_share / 100.0

    st.divider()
    st.caption(
        f"📁 Заказов в данных: **{len(orders_all):,}**  \n"
        f"💰 Рекламных кампаний-месяцев: **{len(ads_all):,}**  \n"
        f"📅 Платежи: {pay_min:%d.%m.%Y} — {pay_max:%d.%m.%Y}  \n"
        f"📅 Реклама: {ad_min:%m.%Y} — {ad_max:%m.%Y}"
    )


orders = M.filter_orders_by_period(orders_all, d_from, d_to)
ads = M.filter_ads_by_period(ads_all, d_from, d_to)


# ============================================================
#                       Header
# ============================================================

st.title("Окупаемость рекламы и LTV клиентов")
st.caption(
    f"Период анализа: **{d_from:%d.%m.%Y} – {d_to:%d.%m.%Y}** · "
    f"Источник расхода: **Яндекс.Директ** · "
    f"Атрибуция платного трафика: **{paid_traffic_share}%**"
)


# ============================================================
#                       KPIs (сопоставимый)
# ============================================================

k_full = M.compute_kpi(orders, ads)
ck = M.comparable_kpi(orders, ads)

if ck is None:
    st.warning(
        "В выбранном периоде нет перекрытия между месяцами расходов и месяцами платежей. "
        "Расширьте диапазон или добавьте больше CSV-выгрузок."
    )
    ck = k_full

revenue_attr = ck.revenue * attribution_factor
romi_attr = (revenue_attr - ck.spend) / ck.spend if ck.spend else 0.0
ltv_to_cac = (ck.arpu / (ck.spend / max(ck.new_clients, 1))) if ck.new_clients else 0.0

st.subheader("Главные показатели — сопоставимый период")
st.caption(
    "Все KPI на этой плитке считаются только за месяцы, где есть И расход на Директ, "
    "И платежи в данных. Это «честное» сопоставление."
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Расход на Директ", f"{ck.spend:,.0f} ₽")
c2.metric("Доход (оплаты)", f"{ck.revenue:,.0f} ₽",
          delta=f"{(ck.revenue - ck.spend):+,.0f} ₽ к расходу")
c3.metric(
    f"ROMI (атрибуция {paid_traffic_share}%)",
    f"{romi_attr*100:+.1f}%",
    help="Return On Marketing Investment = (Доход×Атрибуция − Расход) / Расход",
)
c4.metric("Клиентов в периоде", f"{ck.unique_clients:,}",
          delta=f"новых: {ck.new_clients}, повторных: {ck.repeat_clients}")
c5.metric(
    "CAC (Cost per acquisition)",
    f"{(ck.spend / max(ck.new_clients,1)):,.0f} ₽",
    help="Расход / число новых клиентов (зарегистрировавшихся в этом периоде)",
)

c6, c7, c8, c9, c10 = st.columns(5)
c6.metric("Средний чек", f"{ck.avg_check:,.0f} ₽")
c7.metric("ARPU (доход/клиент)", f"{ck.arpu:,.0f} ₽")
c8.metric("Оплачено заказов", f"{ck.orders_paid:,}",
          delta=f"всего: {ck.orders_total}")
c9.metric("Оплат на клиента", f"{ck.avg_orders_per_client:.2f}")
c10.metric(
    "LTV / CAC",
    f"{ltv_to_cac:.2f}×",
    help="ARPU делённый на CAC. Целевое значение — выше 1×, отлично — выше 3×.",
)

with st.expander("ℹ️ Контекст всего периода (для справки)"):
    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.metric("Расход за весь период", f"{k_full.spend:,.0f} ₽")
    cc2.metric("Доход за весь период", f"{k_full.revenue:,.0f} ₽")
    cc3.metric("Сумма покупок (до оплаты)", f"{k_full.purchase_amount:,.0f} ₽")
    cc4.metric("Gap покупка → оплата", f"{k_full.payment_to_purchase_gap*100:.1f}%",
               help="Доля заказов, которые были в корзине, но не дошли до оплаты")
    st.caption(
        "⚠️ ROMI за «весь период» можно считать только когда есть платежи во ВСЕХ месяцах рекламы. "
        "Иначе он систематически занижен — поэтому здесь его не показываем."
    )


# ============================================================
#                       Tabs
# ============================================================

tab_dyn, tab_cohort, tab_payback, tab_repeat, tab_products, tab_clients, tab_ads, tab_data = st.tabs(
    ["📈 Динамика", "🔥 Когорты", "⏱ Окупаемость", "🔁 Повторные оплаты",
     "📦 Продукты", "👥 Топ-клиенты", "📢 Кампании", "🗂 Данные"]
)


# ---------- Динамика ----------

with tab_dyn:
    ms = M.monthly_summary(orders, ads)
    if ms.empty:
        st.info("В выбранном периоде нет данных для месячной сводки.")
    else:
        ms_disp = ms.copy()
        ms_disp["month_label"] = ms_disp["month"].dt.strftime("%b %Y")

        col1, col2 = st.columns([2, 1])
        with col1:
            fig = go.Figure()
            fig.add_bar(
                x=ms_disp["month_label"], y=ms_disp["spend"],
                name="Расход на Директ", marker_color="#e07a5f",
                hovertemplate="%{x}<br>Расход: %{y:,.0f} ₽<extra></extra>",
            )
            fig.add_bar(
                x=ms_disp["month_label"], y=ms_disp["revenue"],
                name="Доход (оплаты)", marker_color="#81b29a",
                hovertemplate="%{x}<br>Доход: %{y:,.0f} ₽<extra></extra>",
            )
            fig.add_scatter(
                x=ms_disp["month_label"], y=ms_disp["revenue_from_new"],
                name="Доход от новых клиентов M+0", mode="lines+markers",
                line=dict(color="#3d405b", width=3),
                hovertemplate="%{x}<br>От новых M+0: %{y:,.0f} ₽<extra></extra>",
            )
            fig.update_layout(
                title="Расход vs Доход по месяцам",
                barmode="group", height=440,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                yaxis_title="Рубли", xaxis_title=None,
                margin=dict(t=80, l=10, r=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig2 = go.Figure()
            fig2.add_bar(
                x=ms_disp["month_label"], y=ms_disp["new_clients"],
                marker_color="#f2cc8f", name="Новые клиенты",
                hovertemplate="%{x}<br>Новых: %{y}<extra></extra>",
            )
            fig2.add_scatter(
                x=ms_disp["month_label"], y=ms_disp["cac"],
                name="CAC", mode="lines+markers", yaxis="y2",
                line=dict(color="#e07a5f", width=3),
                hovertemplate="%{x}<br>CAC: %{y:,.0f} ₽<extra></extra>",
            )
            fig2.update_layout(
                title="Новые клиенты и CAC",
                yaxis_title="Клиентов",
                yaxis2=dict(title="CAC, ₽", overlaying="y", side="right"),
                height=440,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(t=80, l=10, r=10, b=10),
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(
            ms_disp[["month_label", "spend", "revenue", "new_clients",
                     "revenue_from_new", "cac", "romi", "m0_payback_ratio"]]
              .rename(columns={
                  "month_label": "Месяц",
                  "spend": "Расход, ₽",
                  "revenue": "Доход, ₽",
                  "new_clients": "Новых клиентов",
                  "revenue_from_new": "Доход от новых M+0, ₽",
                  "cac": "CAC, ₽",
                  "romi": "ROMI",
                  "m0_payback_ratio": "Окупаемость M+0",
              }),
            use_container_width=True, hide_index=True,
            column_config={
                "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Доход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Доход от новых M+0, ₽": st.column_config.NumberColumn(format="%.0f"),
                "CAC, ₽": st.column_config.NumberColumn(format="%.0f"),
                "ROMI": st.column_config.NumberColumn(format="%.1f%%"),
                "Окупаемость M+0": st.column_config.NumberColumn(format="%.1f%%"),
            }
        )


# ---------- Когорты ----------

with tab_cohort:
    metric_kind = st.radio(
        "Метрика когортной таблицы",
        ["Доход (₽)", "Retention (% клиентов когорты)"],
        horizontal=True,
    )
    only_recent = st.checkbox(
        "Показать только когорты с момента начала рекламы",
        value=True,
        help=(
            "В данных есть платежи от клиентов, регистрировавшихся ещё в 2019–2024. "
            "Их когорты слишком разрежены. По умолчанию показываем когорты с момента старта рекламы "
            f"({ads_all['month'].min():%m.%Y})."
        ),
    )

    if metric_kind.startswith("Доход"):
        table = M.build_cohort_table(orders, basis=cohort_basis)
    else:
        table = M.cohort_retention(orders, basis=cohort_basis)

    if table.empty:
        st.info("Недостаточно данных для построения когорт.")
    else:
        if only_recent:
            cutoff = ads_all["month"].min()
            table = table.loc[table.index >= cutoff]

        sizes = M.cohort_client_counts(orders, basis=cohort_basis)
        sizes = sizes.reindex(table.index).fillna(0).astype(int)

        # форматирование индекса
        table_disp = table.copy()
        table_disp.index = table_disp.index.strftime("%b %Y")
        table_disp.insert(0, "Клиентов в когорте", sizes.values)

        if metric_kind.startswith("Доход"):
            colormap = "YlGn"
            value_fmt = "{:,.0f}"
        else:
            table_disp.iloc[:, 1:] = (table_disp.iloc[:, 1:] * 100).round(1)
            colormap = "Blues"
            value_fmt = "{:.1f}"

        # heatmap из числовых колонок
        z_cols = [c for c in table_disp.columns if c.startswith("M+")]
        if z_cols:
            fig = px.imshow(
                table_disp[z_cols].values,
                x=z_cols, y=table_disp.index,
                color_continuous_scale=colormap,
                aspect="auto",
                labels=dict(x="Месяц от когорты", y="Когорта", color=metric_kind),
            )
            fig.update_layout(
                height=max(320, 40 * len(table_disp) + 120),
                title=f"Когорта × смещение — {metric_kind}",
                margin=dict(t=70, l=10, r=10, b=10),
            )
            fig.update_traces(
                hovertemplate="Когорта %{y}<br>%{x}<br>" + metric_kind + ": %{z:,.1f}<extra></extra>",
            )
            st.plotly_chart(fig, use_container_width=True)

        st.dataframe(table_disp, use_container_width=True)

        st.caption(
            "Толкование: строка — месяц регистрации, столбец — сколько месяцев прошло. "
            "Ячейка M+0 — деньги в месяце регистрации, M+1 — в следующем, и так далее. "
            "Чем светлее цвет в правой части таблицы — тем хуже retention когорты."
        )


# ---------- Окупаемость / Payback ----------

with tab_payback:
    pb = M.cohort_payback(orders, ads)
    if pb.empty:
        st.info("Нет данных для расчёта окупаемости когорт.")
    else:
        cutoff = ads_all["month"].min()
        pb_recent = pb.loc[pb.index >= cutoff].copy()

        col1, col2, col3 = st.columns(3)
        avg_cac = pb_recent["cac"].mean()
        avg_payback_pct = pb_recent["paid_back_pct_to_date"].mean()
        with_payback = pb_recent.dropna(subset=["payback_month"])
        avg_payback = with_payback["payback_month"].mean() if not with_payback.empty else None
        col1.metric("Средний CAC по когортам", f"{avg_cac:,.0f} ₽" if pd.notna(avg_cac) else "—")
        col2.metric(
            "Средний % окупаемости на сегодня",
            f"{avg_payback_pct*100:.1f}%" if pd.notna(avg_payback_pct) else "—",
            help="Сколько процентов CAC уже вернулось от когорты к моменту последних данных",
        )
        col3.metric(
            "Среднее число месяцев до окупаемости",
            f"{avg_payback:.1f} мес" if avg_payback is not None and pd.notna(avg_payback) else "не достигнута",
        )

        rev_cols = [c for c in pb_recent.columns if c.startswith("cum_M+")]
        offsets = [int(c.replace("cum_M+", "")) for c in rev_cols]

        fig = go.Figure()
        # CAC bars
        fig.add_bar(
            x=pb_recent.index.strftime("%b %Y"), y=pb_recent["cac"],
            name="CAC (расход / новых)", marker_color="#e07a5f",
            opacity=0.55,
            hovertemplate="%{x}<br>CAC: %{y:,.0f} ₽<extra></extra>",
        )
        # cumulative revenue per cohort, max offset available
        max_cum = pb_recent[rev_cols].apply(lambda row: row.max(skipna=True), axis=1)
        fig.add_scatter(
            x=pb_recent.index.strftime("%b %Y"), y=max_cum * paid_traffic_share / 100.0 / pb_recent["clients"].replace(0, 1),
            name=f"Доход на 1 клиента когорты (атриб. {paid_traffic_share}%)",
            mode="lines+markers", line=dict(color="#3d405b", width=3),
            hovertemplate="%{x}<br>Доход/клиент: %{y:,.0f} ₽<extra></extra>",
        )
        fig.update_layout(
            title="CAC vs накопленный доход на одного клиента когорты",
            height=420, barmode="group",
            yaxis_title="Рубли",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=80, l=10, r=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

        # таблица
        pb_show = pb_recent.copy()
        pb_show.index = pb_show.index.strftime("%b %Y")
        pb_show.index.name = "Когорта"
        pretty_cols = {
            "clients": "Клиентов",
            "ad_spend": "Расход в месяце, ₽",
            "cac": "CAC, ₽",
            "payback_month": "Окупилось через, мес",
            "paid_back_pct_to_date": "% возврата CAC к концу данных",
        }
        for c in rev_cols:
            pretty_cols[c] = c.replace("cum_M+", "Накоп. доход M+")
        pb_show = pb_show.rename(columns=pretty_cols)
        st.dataframe(pb_show, use_container_width=True)

        st.caption(
            "Окупаемость когорты = накопленный доход от клиентов когорты ≥ расход на их привлечение. "
            "Когорты последних 1–2 месяцев физически не могли окупиться — это нормально. "
            "Долгосрочный LTV хостинга в принципе достигается за 6–12 месяцев, поэтому ориентир — "
            "не «окупился ли месяц», а «растёт ли % возврата CAC от старых когорт к новым»."
        )


# ---------- Повторные оплаты ----------

with tab_repeat:
    rd = M.repeat_purchase_distribution(orders)
    paid = orders[orders["is_paid"]]

    col1, col2 = st.columns([2, 1])
    with col1:
        if not rd.empty:
            fig = px.bar(
                rd, x="orders_per_client", y="clients",
                text=rd["share"].apply(lambda x: f"{x*100:.1f}%"),
                color_discrete_sequence=["#81b29a"],
                labels={"orders_per_client": "Оплат на клиента", "clients": "Клиентов"},
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(
                title="Распределение клиентов по числу оплат",
                height=420, margin=dict(t=70, l=10, r=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        new_orders = (paid["new_or_old"] == "Новый").sum()
        old_orders = (paid["new_or_old"] == "Старый").sum()
        total = new_orders + old_orders
        new_share = new_orders / total if total else 0
        old_share = old_orders / total if total else 0
        st.metric("Доля повторных оплат", f"{old_share*100:.1f}%",
                  help=(
                      "Сколько оплат в периоде сделали клиенты, зарегистрировавшиеся до начала "
                      "этого периода. Это ключевой индикатор удержания — для хостинга 60-70% это сильный показатель."
                  ))
        st.metric("Доля новых клиентов в оплатах", f"{new_share*100:.1f}%")

        fig2 = px.pie(
            names=["Повторные", "Новые"],
            values=[old_orders, new_orders],
            color_discrete_sequence=["#81b29a", "#f2cc8f"],
            hole=0.5,
        )
        fig2.update_traces(textinfo="percent")
        fig2.update_layout(
            title="Структура оплат",
            height=300, margin=dict(t=50, l=10, r=10, b=10),
            showlegend=True,
        )
        st.plotly_chart(fig2, use_container_width=True)


# ---------- Продукты ----------

with tab_products:
    col1, col2 = st.columns(2)
    with col1:
        fam = M.product_mix(orders, by="product_family")
        if not fam.empty:
            top = fam.head(10)
            fig = px.bar(
                top, x="revenue", y="product_family", orientation="h",
                text=top["share"].apply(lambda x: f"{x*100:.1f}%"),
                color="revenue", color_continuous_scale="Teal",
                labels={"product_family": "Семейство", "revenue": "Доход, ₽"},
            )
            fig.update_layout(
                title="Доход по семействам продуктов",
                yaxis=dict(categoryorder="total ascending"),
                height=460, margin=dict(t=70, l=10, r=10, b=10),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(
                fam.rename(columns={
                    "product_family": "Семейство",
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
                },
            )

    with col2:
        loc = M.product_mix(orders, by="product_location")
        if not loc.empty:
            top_l = loc.head(12)
            fig = px.bar(
                top_l, x="revenue", y="product_location", orientation="h",
                text=top_l["share"].apply(lambda x: f"{x*100:.1f}%"),
                color="revenue", color_continuous_scale="Sunset",
                labels={"product_location": "Локация", "revenue": "Доход, ₽"},
            )
            fig.update_layout(
                title="Доход по локациям серверов",
                yaxis=dict(categoryorder="total ascending"),
                height=460, margin=dict(t=70, l=10, r=10, b=10),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True)

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
                },
            )


# ---------- Топ-клиенты ----------

with tab_clients:
    n_top = st.slider("Сколько топовых клиентов показать", 10, 100, 25, step=5)
    tc = M.top_clients(orders, n=n_top)
    if tc.empty:
        st.info("Нет данных по клиентам в выбранном периоде.")
    else:
        tc_disp = tc.copy()
        tc_disp["registration_date"] = tc_disp["registration_date"].dt.date
        tc_disp["first_payment"] = tc_disp["first_payment"].dt.date
        tc_disp["last_payment"] = tc_disp["last_payment"].dt.date
        st.dataframe(
            tc_disp.rename(columns={
                "client_key": "Клиент (email)",
                "client_name": "Имя",
                "registration_date": "Регистрация",
                "first_payment": "1-я оплата (в данных)",
                "last_payment": "Последняя оплата",
                "orders": "Оплат",
                "total_paid": "Сумма, ₽",
                "lifespan_days": "Стаж клиента, дней",
            }),
            use_container_width=True, hide_index=True,
            column_config={
                "Сумма, ₽": st.column_config.NumberColumn(format="%.0f"),
            }
        )

        median_lifespan = tc["lifespan_days"].median()
        median_orders = tc["orders"].median()
        c1, c2, c3 = st.columns(3)
        c1.metric("Медианный стаж топ-клиента", f"{int(median_lifespan)} дн")
        c2.metric("Медиана оплат у топа", f"{int(median_orders)}")
        c3.metric("Сумма от топ-N", f"{tc['total_paid'].sum():,.0f} ₽",
                  delta=f"{tc['total_paid'].sum()/k_full.revenue*100:.0f}% всего дохода")


# ---------- Кампании ----------

with tab_ads:
    cb = M.campaign_breakdown(ads)
    if cb.empty:
        st.info("В выбранном периоде нет данных по рекламным кампаниям.")
    else:
        col1, col2 = st.columns([3, 2])
        with col1:
            top_camp = cb.head(15)
            fig = px.bar(
                top_camp, x="spend", y="campaign", orientation="h",
                text=top_camp["share"].apply(lambda x: f"{x*100:.1f}%"),
                color="spend", color_continuous_scale="Reds",
                labels={"campaign": "Кампания", "spend": "Расход, ₽"},
            )
            fig.update_layout(
                title="Топ кампаний по расходу",
                yaxis=dict(categoryorder="total ascending"),
                height=560, margin=dict(t=70, l=10, r=10, b=10),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            mt = ads_monthly_totals(ads)
            if not mt.empty:
                mt["month_label"] = mt["month"].dt.strftime("%b %Y")
                fig = px.bar(
                    mt, x="month_label", y="spend_rub",
                    text=mt["spend_rub"].apply(lambda x: f"{x/1000:,.0f}K"),
                    color_discrete_sequence=["#e07a5f"],
                    labels={"month_label": "Месяц", "spend_rub": "Расход, ₽"},
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(
                    title="Расход на Директ по месяцам",
                    height=560, margin=dict(t=70, l=10, r=10, b=10),
                )
                st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            cb.rename(columns={
                "campaign": "Кампания",
                "spend": "Расход, ₽",
                "months_active": "Месяцев в работе",
                "share": "Доля от расхода",
            }),
            use_container_width=True, hide_index=True,
            column_config={
                "Расход, ₽": st.column_config.NumberColumn(format="%.0f"),
                "Доля от расхода": st.column_config.NumberColumn(format="%.2f%%"),
            }
        )


# ---------- Сырые данные ----------

with tab_data:
    st.subheader("Все оплаты в периоде")
    show_orders = orders[orders["is_paid"]][[
        "order_id", "payment_date", "registration_date", "new_or_old",
        "client_name", "email", "product", "product_family", "product_location",
        "payment_amount", "purchase_amount_rub",
    ]].copy()
    show_orders["payment_date"] = show_orders["payment_date"].dt.date
    show_orders["registration_date"] = show_orders["registration_date"].dt.date
    st.dataframe(show_orders, use_container_width=True, hide_index=True, height=380)

    st.download_button(
        "⬇️ Скачать оплаты (CSV)",
        data=show_orders.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"ufo_orders_{d_from:%Y%m%d}_{d_to:%Y%m%d}.csv",
        mime="text/csv",
    )

    st.subheader("Все рекламные строки в периоде")
    show_ads = ads[["month", "campaign", "spend_rub", "source_sheet"]].copy()
    show_ads["month"] = show_ads["month"].dt.strftime("%Y-%m")
    st.dataframe(show_ads, use_container_width=True, hide_index=True, height=380)
    st.download_button(
        "⬇️ Скачать расходы (CSV)",
        data=show_ads.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"ufo_ads_{d_from:%Y%m%d}_{d_to:%Y%m%d}.csv",
        mime="text/csv",
    )


# ============================================================
#                       Footer
# ============================================================

st.divider()
st.caption(
    "📁 Чтобы обновить данные — положите новые CSV в `data/orders/` и новый XLSX в `data/ads/`, "
    "затем нажмите **C** (Clear cache) в правом верхнем меню Streamlit и обновите страницу."
)
