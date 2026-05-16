"""
Бизнес-метрики поверх загруженных данных.

Все функции принимают уже подготовленные DataFrame'ы (см. data_loader.py)
и возвращают агрегаты, готовые к отображению.

Ключевое ограничение: в выгрузках нет источника трафика, поэтому источник
оплаты не идентифицируется per-client. Сопоставление с расходом на Директ
делается агрегированно по месяцу регистрации клиента.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------- helpers ----------

def _paid(orders: pd.DataFrame) -> pd.DataFrame:
    return orders.loc[orders["is_paid"]].copy()


def filter_orders_by_period(orders: pd.DataFrame,
                            date_from: pd.Timestamp | None,
                            date_to: pd.Timestamp | None) -> pd.DataFrame:
    df = orders
    if date_from is not None:
        df = df[df["payment_date"] >= pd.Timestamp(date_from)]
    if date_to is not None:
        df = df[df["payment_date"] <= pd.Timestamp(date_to)]
    return df


def filter_ads_by_period(ads: pd.DataFrame,
                         date_from: pd.Timestamp | None,
                         date_to: pd.Timestamp | None) -> pd.DataFrame:
    df = ads
    if date_from is not None:
        df = df[df["month"] >= pd.Timestamp(date_from).to_period("M").to_timestamp()]
    if date_to is not None:
        df = df[df["month"] <= pd.Timestamp(date_to).to_period("M").to_timestamp()]
    return df


# ---------- KPIs ----------

@dataclass
class KPI:
    spend: float
    revenue: float
    purchase_amount: float
    orders_paid: int
    orders_total: int
    unique_clients: int
    new_clients: int
    repeat_clients: int
    avg_check: float
    arpu: float
    romi_payment: float          # (revenue - spend) / spend
    romi_purchase: float         # (purchase - spend) / spend
    payment_to_purchase_gap: float  # 1 - payment/purchase (доля не дошедших до оплаты денег)
    avg_orders_per_client: float


def compute_kpi(orders: pd.DataFrame, ads: pd.DataFrame) -> KPI:
    paid = _paid(orders)
    spend = float(ads["spend_rub"].sum()) if not ads.empty else 0.0
    revenue = float(paid["payment_amount"].sum())
    purchase = float(paid["purchase_amount_rub"].sum())
    orders_paid = int(len(paid))
    orders_total = int(len(orders))
    uniq = int(paid["client_key"].nunique())

    # «Новый» = уникальный клиент, у которого в этом периоде есть оплата с пометкой «Новый»
    # (так помечает её сама админка UFO Hosting в момент первой оплаты клиента).
    # Совпадает с тем, как ту же метрику считают в выгрузках Excel.
    if not paid.empty:
        new_keys = set(paid.loc[paid["new_or_old"] == "Новый", "client_key"])
        new = len(new_keys)
        repeat = uniq - new
    else:
        new = repeat = 0

    avg_check = revenue / orders_paid if orders_paid else 0.0
    arpu = revenue / uniq if uniq else 0.0
    romi_p = (revenue - spend) / spend if spend else 0.0
    romi_pu = (purchase - spend) / spend if spend else 0.0
    gap = 1 - (revenue / purchase) if purchase else 0.0
    avg_ord = orders_paid / uniq if uniq else 0.0
    return KPI(spend, revenue, purchase, orders_paid, orders_total, uniq,
               new, repeat, avg_check, arpu, romi_p, romi_pu, gap, avg_ord)


# ---------- Когортный анализ ----------

def build_cohort_table(orders: pd.DataFrame,
                       basis: str = "registration") -> pd.DataFrame:
    """Когорта × месяц-смещение → доход.

    basis='registration' — когорта по месяцу регистрации клиента
    basis='first_payment' — когорта по месяцу первой оплаты в данных

    Возвращает pivot: rows=cohort_month, cols=months_offset (0,1,2...), values=revenue.
    """
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()

    if basis == "first_payment":
        first = paid.groupby("client_key")["payment_date"].min().rename("cohort_date")
    else:
        first = paid.groupby("client_key")["registration_date"].min().rename("cohort_date")
    paid = paid.join(first, on="client_key")
    paid["cohort_month"] = paid["cohort_date"].dt.to_period("M").dt.to_timestamp()

    paid["offset"] = (
        (paid["payment_month"].dt.year - paid["cohort_month"].dt.year) * 12
        + (paid["payment_month"].dt.month - paid["cohort_month"].dt.month)
    )
    paid = paid[paid["offset"] >= 0]
    if paid.empty:
        return pd.DataFrame()

    revenue = paid.groupby(["cohort_month", "offset"])["payment_amount"].sum().unstack(fill_value=0.0)
    revenue = revenue.sort_index()
    revenue.columns = [f"M+{c}" for c in revenue.columns]
    return revenue


def cohort_client_counts(orders: pd.DataFrame,
                         basis: str = "registration") -> pd.Series:
    """Размер каждой когорты (уникальных клиентов)."""
    paid = _paid(orders)
    if paid.empty:
        return pd.Series(dtype=int)
    if basis == "first_payment":
        first = paid.groupby("client_key")["payment_date"].min()
    else:
        first = paid.groupby("client_key")["registration_date"].min()
    s = first.dt.to_period("M").dt.to_timestamp().value_counts().sort_index()
    s.name = "clients"
    return s


def cohort_retention(orders: pd.DataFrame,
                     basis: str = "registration") -> pd.DataFrame:
    """Доля клиентов когорты, плативших в смещении M+k (от общего числа клиентов когорты)."""
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    if basis == "first_payment":
        first = paid.groupby("client_key")["payment_date"].min().rename("cohort_date")
    else:
        first = paid.groupby("client_key")["registration_date"].min().rename("cohort_date")
    paid = paid.join(first, on="client_key")
    paid["cohort_month"] = paid["cohort_date"].dt.to_period("M").dt.to_timestamp()
    paid["offset"] = (
        (paid["payment_month"].dt.year - paid["cohort_month"].dt.year) * 12
        + (paid["payment_month"].dt.month - paid["cohort_month"].dt.month)
    )
    paid = paid[paid["offset"] >= 0]

    cohort_sizes = paid.groupby("cohort_month")["client_key"].nunique()
    pivot = (paid.groupby(["cohort_month", "offset"])["client_key"]
             .nunique()
             .unstack(fill_value=0))
    ret = pivot.div(cohort_sizes, axis=0)
    ret.columns = [f"M+{c}" for c in ret.columns]
    return ret.sort_index()


# ---------- CAC, LTV, Payback ----------

def overlap_period(orders: pd.DataFrame, ads: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Период, где есть И расходы на рекламу, И платежи (помесячно)."""
    paid = _paid(orders)
    if paid.empty or ads.empty:
        return None
    pay_months = set(paid["payment_month"].dropna().unique())
    ad_months = set(ads["month"].dropna().unique())
    common = sorted(pay_months & ad_months)
    if not common:
        return None
    return (pd.Timestamp(common[0]), pd.Timestamp(common[-1]))


def comparable_kpi(orders: pd.DataFrame, ads: pd.DataFrame) -> KPI | None:
    """KPI только за перекрывающийся период (где есть и реклама, и платежи).
    Это и есть «честное» сопоставление расхода с доходом."""
    period = overlap_period(orders, ads)
    if period is None:
        return None
    o = filter_orders_by_period(orders, period[0], period[1] + pd.offsets.MonthEnd(0))
    a = filter_ads_by_period(ads, period[0], period[1])
    return compute_kpi(o, a)


def monthly_summary(orders: pd.DataFrame, ads: pd.DataFrame,
                    drop_empty: bool = True) -> pd.DataFrame:
    """Месячная сводка: расход, доход, новые клиенты, CAC, доход от новых клиентов этого месяца."""
    paid = _paid(orders)

    # доход за каждый месяц (по дате платежа)
    rev_by_month = paid.groupby("payment_month")["payment_amount"].sum()

    # новые клиенты по месяцу регистрации
    first_reg = paid.groupby("client_key")["registration_date"].min().dt.to_period("M").dt.to_timestamp()
    new_clients_by_month = first_reg.value_counts().sort_index()

    # доход от только новых клиентов этого месяца (платежи в момент регистрации)
    paid = paid.assign(reg_month=paid["registration_date"].dt.to_period("M").dt.to_timestamp())
    rev_from_new = (paid[paid["payment_month"] == paid["reg_month"]]
                    .groupby("payment_month")["payment_amount"].sum())

    spend_by_month = ads.groupby("month")["spend_rub"].sum() if not ads.empty else pd.Series(dtype=float)

    idx = sorted(set(rev_by_month.index)
                 | set(new_clients_by_month.index)
                 | set(spend_by_month.index))
    out = pd.DataFrame(index=idx)
    out.index.name = "month"
    out["spend"] = spend_by_month.reindex(idx).fillna(0)
    out["revenue"] = rev_by_month.reindex(idx).fillna(0)
    out["new_clients"] = new_clients_by_month.reindex(idx).fillna(0).astype(int)
    out["revenue_from_new"] = rev_from_new.reindex(idx).fillna(0)
    out["cac"] = np.where(out["new_clients"] > 0, out["spend"] / out["new_clients"], np.nan)
    out["romi"] = np.where(out["spend"] > 0, (out["revenue"] - out["spend"]) / out["spend"], np.nan)
    out["m0_payback_ratio"] = np.where(out["spend"] > 0, out["revenue_from_new"] / out["spend"], np.nan)
    if drop_empty:
        out = out[(out["spend"] > 0) | (out["revenue"] > 0)]
    return out.reset_index()


def cohort_payback(orders: pd.DataFrame, ads: pd.DataFrame) -> pd.DataFrame:
    """Для каждой когорты регистрации: CAC и накопленный доход по месяцам.
    Показывает, за сколько месяцев когорта окупила свою стоимость привлечения."""
    cohort_rev = build_cohort_table(orders, basis="registration")
    if cohort_rev.empty:
        return pd.DataFrame()
    cum = cohort_rev.cumsum(axis=1)
    cum.columns = [f"cum_{c}" for c in cohort_rev.columns]

    sizes = cohort_client_counts(orders, basis="registration")
    spend_by_month = ads.groupby("month")["spend_rub"].sum() if not ads.empty else pd.Series(dtype=float)

    df = cum.copy()
    df.insert(0, "clients", sizes.reindex(df.index).fillna(0).astype(int))
    df.insert(1, "ad_spend", spend_by_month.reindex(df.index).fillna(0.0))
    df.insert(2, "cac", np.where(df["clients"] > 0, df["ad_spend"] / df["clients"], np.nan))

    # месяц окупаемости
    rev_cols = [c for c in df.columns if c.startswith("cum_M+")]
    payback = []
    for idx, row in df.iterrows():
        spend = row["ad_spend"]
        if spend <= 0:
            payback.append(np.nan)
            continue
        found = None
        for c in rev_cols:
            offset = int(c.replace("cum_M+", ""))
            if row[c] >= spend:
                found = offset
                break
        payback.append(found if found is not None else np.nan)
    df["payback_month"] = payback
    df["paid_back_pct_to_date"] = np.where(
        df["ad_spend"] > 0,
        df[rev_cols].max(axis=1) / df["ad_spend"],
        np.nan,
    )
    return df


# ---------- Product / location mix ----------

def product_mix(orders: pd.DataFrame, by: str = "product_family") -> pd.DataFrame:
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    g = (paid.groupby(by)
         .agg(orders=("order_id", "count"),
              revenue=("payment_amount", "sum"),
              clients=("client_key", "nunique"))
         .sort_values("revenue", ascending=False)
         .reset_index())
    g["avg_check"] = g["revenue"] / g["orders"]
    g["share"] = g["revenue"] / g["revenue"].sum()
    return g


def top_clients(orders: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    g = (paid.groupby("client_key")
         .agg(client_name=("client_name", "first"),
              registration_date=("registration_date", "min"),
              first_payment=("payment_date", "min"),
              last_payment=("payment_date", "max"),
              orders=("order_id", "count"),
              total_paid=("payment_amount", "sum"))
         .sort_values("total_paid", ascending=False)
         .head(n)
         .reset_index())
    g["lifespan_days"] = (g["last_payment"] - g["registration_date"]).dt.days
    return g


def repeat_purchase_distribution(orders: pd.DataFrame) -> pd.DataFrame:
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    by_client = paid.groupby("client_key").size()
    dist = by_client.value_counts().sort_index().rename_axis("orders_per_client").reset_index(name="clients")
    dist["share"] = dist["clients"] / dist["clients"].sum()
    return dist


def campaign_breakdown(ads: pd.DataFrame) -> pd.DataFrame:
    if ads.empty:
        return pd.DataFrame()
    g = (ads.groupby("campaign")
         .agg(spend=("spend_rub", "sum"),
              months_active=("month", "nunique"))
         .sort_values("spend", ascending=False)
         .reset_index())
    g["share"] = g["spend"] / g["spend"].sum()
    return g


# ---------- Сравнение периодов ----------

def previous_period(date_from: pd.Timestamp, date_to: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Тот же интервал, что и [from, to], но заканчивающийся за день до from."""
    length = date_to - date_from
    prev_to = date_from - pd.Timedelta(days=1)
    prev_from = prev_to - length
    return prev_from, prev_to


def period_comparison(orders: pd.DataFrame, ads: pd.DataFrame,
                      date_from: pd.Timestamp, date_to: pd.Timestamp) -> dict:
    """Сравнение текущего периода с эквивалентным предыдущим. Возвращает
    словарь с current/previous KPI и относительными дельтами."""
    prev_from, prev_to = previous_period(date_from, date_to)
    cur_o = filter_orders_by_period(orders, date_from, date_to)
    cur_a = filter_ads_by_period(ads, date_from, date_to)
    prev_o = filter_orders_by_period(orders, prev_from, prev_to)
    prev_a = filter_ads_by_period(ads, prev_from, prev_to)
    cur = compute_kpi(cur_o, cur_a)
    prev = compute_kpi(prev_o, prev_a)

    def delta_pct(a, b):
        if b == 0 or b is None or pd.isna(b):
            return None
        return (a - b) / abs(b) * 100

    return {
        "current": cur, "previous": prev,
        "prev_period": (prev_from, prev_to),
        "deltas": {
            "spend": delta_pct(cur.spend, prev.spend),
            "revenue": delta_pct(cur.revenue, prev.revenue),
            "unique_clients": delta_pct(cur.unique_clients, prev.unique_clients),
            "new_clients": delta_pct(cur.new_clients, prev.new_clients),
            "avg_check": delta_pct(cur.avg_check, prev.avg_check),
            "arpu": delta_pct(cur.arpu, prev.arpu),
        },
    }


# ---------- Воронка ----------

def funnel(orders: pd.DataFrame) -> pd.DataFrame:
    """Регистрации → Платящие → Повторные → Топ-плательщики (≥5 оплат)."""
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    reg_clients = orders["client_key"].nunique()
    paying = paid["client_key"].nunique()
    by_client = paid.groupby("client_key").size()
    repeat = (by_client >= 2).sum()
    loyal = (by_client >= 5).sum()
    return pd.DataFrame([
        {"stage": "Зарегистрированы", "count": reg_clients},
        {"stage": "Хотя бы 1 оплата", "count": paying},
        {"stage": "Повторная (2+)", "count": repeat},
        {"stage": "Лояльные (5+)", "count": loyal},
    ])


# ---------- Распределение чеков ----------

def check_distribution(orders: pd.DataFrame, max_bins: int = 20) -> pd.DataFrame:
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    amounts = paid["payment_amount"].dropna()
    if amounts.empty:
        return pd.DataFrame()
    # квантильные границы для адекватной шкалы (отрезаем 1% выбросов)
    p99 = amounts.quantile(0.99)
    clipped = amounts.clip(upper=p99)
    bins = pd.cut(clipped, bins=max_bins)
    dist = bins.value_counts().sort_index().reset_index()
    dist.columns = ["bin", "count"]
    dist["bin_mid"] = dist["bin"].apply(lambda x: (x.left + x.right) / 2)
    dist["bin_label"] = dist["bin"].apply(lambda x: f"{x.left:,.0f}–{x.right:,.0f}".replace(",", " "))
    return dist


# ---------- Сезонность ----------

RU_WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def seasonality_weekday(orders: pd.DataFrame) -> pd.DataFrame:
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    paid = paid.copy()
    paid["weekday"] = paid["payment_date"].dt.weekday
    g = (paid.groupby("weekday")
         .agg(orders=("order_id", "count"),
              revenue=("payment_amount", "sum"))
         .reindex(range(7), fill_value=0)
         .reset_index())
    g["weekday_label"] = g["weekday"].apply(lambda i: RU_WEEKDAYS[i])
    return g


def seasonality_day_of_month(orders: pd.DataFrame) -> pd.DataFrame:
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    paid = paid.copy()
    paid["day"] = paid["payment_date"].dt.day
    g = (paid.groupby("day")
         .agg(orders=("order_id", "count"),
              revenue=("payment_amount", "sum"))
         .reindex(range(1, 32), fill_value=0)
         .reset_index())
    return g


# ---------- LTV-прогноз ----------

def cohort_ltv_forecast(orders: pd.DataFrame, horizon_months: int = 12) -> pd.DataFrame:
    """Прогноз накопленной выручки на клиента когорты на N месяцев вперёд.
    Простая модель: M+k для k > max_observed экстраполируется через
    усреднённое отношение M+1/M+0 от наблюдаемых когорт."""
    cohort_rev = build_cohort_table(orders, basis="registration")
    if cohort_rev.empty:
        return pd.DataFrame()
    sizes = cohort_client_counts(orders, basis="registration").reindex(cohort_rev.index).fillna(0)

    # доход на клиента когорты, кумулятивно
    rev_per_client = cohort_rev.div(sizes.replace(0, np.nan), axis=0).fillna(0)
    cum_per_client = rev_per_client.cumsum(axis=1)

    # средний прирост между смежными месяцами (доход в M+k минус M+k-1)
    delta = rev_per_client.copy()
    if delta.shape[1] > 1:
        avg_delta = []
        for i in range(1, delta.shape[1]):
            col = delta.iloc[:, i].replace(0, np.nan).dropna()
            avg_delta.append(col.mean())
        # ожидаемый «хвост»: средний прирост из имеющихся, decay 0.9 в месяц
        if avg_delta:
            base_delta = np.median([d for d in avg_delta if not np.isnan(d)] or [0])
        else:
            base_delta = 0
    else:
        base_delta = 0

    result = cum_per_client.copy()
    last_col = result.shape[1]
    # дополним столбцы до horizon_months
    decay = 0.9
    for k in range(last_col, horizon_months + 1):
        col_name = f"M+{k}"
        future_increment = base_delta * (decay ** (k - last_col))
        result[col_name] = result.iloc[:, -1] + future_increment

    result = result.round(0)
    return result


# ---------- Покрытие данными ----------

def data_coverage(orders: pd.DataFrame, ads: pd.DataFrame) -> pd.DataFrame:
    """Помесячная карта покрытия: что есть в CSV (платежи) и в Я.Директ (расходы).
    Возвращает DataFrame с колонками: month, has_orders, has_ads, orders_count, ads_spend."""
    paid = _paid(orders)
    pay_months = set(paid["payment_month"].dropna().unique()) if not paid.empty else set()
    ad_months = set(ads["month"].dropna().unique()) if not ads.empty else set()

    all_months = pay_months | ad_months
    if not all_months:
        return pd.DataFrame()

    months_sorted = sorted(all_months)
    # дополним пропуски: от min до max — все месяцы
    full_range = pd.date_range(
        start=min(months_sorted), end=max(months_sorted), freq="MS"
    )

    orders_by_month = (paid.groupby("payment_month").size()
                       if not paid.empty else pd.Series(dtype=int))
    spend_by_month = (ads.groupby("month")["spend_rub"].sum()
                      if not ads.empty else pd.Series(dtype=float))

    rows = []
    for m in full_range:
        has_o = m in pay_months
        has_a = m in ad_months
        rows.append({
            "month": m,
            "has_orders": has_o,
            "has_ads": has_a,
            "orders_count": int(orders_by_month.get(m, 0)) if has_o else 0,
            "ads_spend": float(spend_by_month.get(m, 0.0)) if has_a else 0.0,
        })
    return pd.DataFrame(rows)


# ---------- Churn-анализ ----------

def churn_analysis(orders: pd.DataFrame,
                   at_risk_days: int = 30,
                   churned_days: int = 90,
                   ref_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """Сегментирует клиентов по «здоровью»:
    - Активный: последняя оплата ≤ at_risk_days назад
    - Под риском: last_payment в окне (at_risk_days, churned_days]
    - Отток: last_payment > churned_days назад
    Reference date = max payment_date (если нет — сегодня)."""
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    if ref_date is None:
        ref_date = paid["payment_date"].max()
    last = (paid.groupby("client_key")
              .agg(client_name=("client_name", "first"),
                   first_payment=("payment_date", "min"),
                   last_payment=("payment_date", "max"),
                   orders=("order_id", "count"),
                   total_paid=("payment_amount", "sum"))
              .reset_index())
    last["days_since_last"] = (ref_date - last["last_payment"]).dt.days
    def _segment(d):
        if d <= at_risk_days:
            return "Активный"
        if d <= churned_days:
            return "Под риском"
        return "Отток"
    last["segment"] = last["days_since_last"].apply(_segment)
    return last.sort_values("total_paid", ascending=False)


def churn_summary(orders: pd.DataFrame, at_risk_days: int = 30, churned_days: int = 90) -> dict:
    df = churn_analysis(orders, at_risk_days, churned_days)
    if df.empty:
        return {"active": 0, "at_risk": 0, "churned": 0, "churn_rate": 0.0, "at_risk_revenue": 0.0}
    n_total = len(df)
    n_active = int((df["segment"] == "Активный").sum())
    n_risk = int((df["segment"] == "Под риском").sum())
    n_churn = int((df["segment"] == "Отток").sum())
    at_risk_revenue = float(df.loc[df["segment"] == "Под риском", "total_paid"].sum())
    churn_rate = n_churn / n_total * 100 if n_total else 0.0
    return {
        "active": n_active,
        "at_risk": n_risk,
        "churned": n_churn,
        "churn_rate": churn_rate,
        "at_risk_revenue": at_risk_revenue,
        "total_clients": n_total,
    }


# ---------- MRR и Net Revenue Retention ----------

def mrr_by_month(orders: pd.DataFrame) -> pd.DataFrame:
    """Помесячная выручка (proxy для MRR в SaaS-смысле — мы считаем фактические
    оплаты за месяц). Возвращает: month, mrr, new_mrr (от новых клиентов),
    expansion_mrr (от старых), prev_mrr, growth_pct."""
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    # доход за каждый месяц
    rev_by_month = paid.groupby("payment_month")["payment_amount"].sum()
    # от новых клиентов
    paid = paid.assign(reg_month=paid["registration_date"].dt.to_period("M").dt.to_timestamp())
    new_rev = (paid[paid["payment_month"] == paid["reg_month"]]
                .groupby("payment_month")["payment_amount"].sum())
    out = pd.DataFrame({"mrr": rev_by_month})
    out["new_mrr"] = new_rev.reindex(out.index).fillna(0)
    out["expansion_mrr"] = out["mrr"] - out["new_mrr"]
    out["prev_mrr"] = out["mrr"].shift(1)
    out["growth_pct"] = (out["mrr"] - out["prev_mrr"]) / out["prev_mrr"].replace(0, np.nan) * 100
    return out.reset_index()


def net_revenue_retention(orders: pd.DataFrame) -> pd.DataFrame:
    """Для каждой когорты регистрации: NRR в M+1 = доход в M+1 / доход в M+0 × 100%.
    Показывает «удержание выручки» (не клиентов!) — есть ли expansion."""
    cohort_rev = build_cohort_table(orders, basis="registration")
    if cohort_rev.empty or cohort_rev.shape[1] < 2:
        return pd.DataFrame()
    m0 = cohort_rev.iloc[:, 0]
    nrr = pd.DataFrame({"M+0": m0})
    for i, col in enumerate(cohort_rev.columns[1:], start=1):
        nrr[col] = cohort_rev[col] / m0.replace(0, np.nan) * 100
    return nrr.round(1)


# ---------- Pareto-сегментация клиентов ----------

def pareto_segmentation(orders: pd.DataFrame) -> pd.DataFrame:
    """ABC-классификация: A (top 20% клиентов, ~80% выручки), B (следующие 30%),
    C (оставшиеся ~50%). Помогает решить кого удерживать в первую очередь."""
    paid = _paid(orders)
    if paid.empty:
        return pd.DataFrame()
    by_client = (paid.groupby("client_key")
                   .agg(client_name=("client_name", "first"),
                        orders=("order_id", "count"),
                        total_paid=("payment_amount", "sum"))
                   .reset_index()
                   .sort_values("total_paid", ascending=False))
    total = by_client["total_paid"].sum()
    if total <= 0:
        return by_client
    by_client["cum_share"] = by_client["total_paid"].cumsum() / total
    by_client["rank_share"] = (by_client.reset_index().index + 1) / len(by_client)

    def _abc(row):
        if row["cum_share"] <= 0.80:
            return "A"
        if row["cum_share"] <= 0.95:
            return "B"
        return "C"

    by_client["segment"] = by_client.apply(_abc, axis=1)
    return by_client


def pareto_summary(orders: pd.DataFrame) -> dict:
    """Сводка по Pareto: количество клиентов и доход по каждому сегменту."""
    df = pareto_segmentation(orders)
    if df.empty:
        return {}
    total_clients = len(df)
    total_revenue = float(df["total_paid"].sum())
    out = {"total_clients": total_clients, "total_revenue": total_revenue}
    for seg in ("A", "B", "C"):
        sub = df[df["segment"] == seg]
        out[f"{seg}_clients"] = int(len(sub))
        out[f"{seg}_revenue"] = float(sub["total_paid"].sum())
        out[f"{seg}_share_clients"] = len(sub) / total_clients * 100 if total_clients else 0
        out[f"{seg}_share_revenue"] = sub["total_paid"].sum() / total_revenue * 100 if total_revenue else 0
    return out
