"""Unit-тесты для metrics.py — на синтетических данных, без зависимости от реальных файлов."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd

import metrics as M


def make_orders():
    """Минимальный синтетический набор: 3 клиента, 4 заказа (3 paid + 1 unpaid)."""
    return pd.DataFrame({
        "order_id":          ["1", "2", "3", "4"],
        "is_paid":           [True, True, True, False],
        "payment_amount":    [1000.0, 2000.0, 1500.0, 500.0],
        "purchase_amount_rub": [1100.0, 2200.0, 1650.0, 550.0],
        "new_or_old":        ["Новый", "Старый", "Новый", "Новый"],
        "client_key":        ["a@a", "b@b", "a@a", "c@c"],
        "client_name":       ["Alice", "Bob", "Alice", "Carol"],
        "email":             ["a@a", "b@b", "a@a", "c@c"],
        "payment_date":      pd.to_datetime(["2026-03-15", "2026-04-01", "2026-04-15", "2026-04-20"]),
        "payment_month":     pd.to_datetime(["2026-03-01", "2026-04-01", "2026-04-01", "2026-04-01"]),
        "registration_date": pd.to_datetime(["2026-03-15", "2025-12-01", "2026-03-15", "2026-04-20"]),
        "registration_month": pd.to_datetime(["2026-03-01", "2025-12-01", "2026-03-01", "2026-04-01"]),
        "product_family":    ["Naos", "Haedus", "Naos", "VPN"],
        "product_location":  ["NL", "DE", "NL", "—"],
        "product":           ["Naos[NL]", "Haedus[DE]", "Naos[NL]", "VPN"],
    })


def make_ads():
    return pd.DataFrame({
        "month":     pd.to_datetime(["2026-03-01", "2026-04-01"]),
        "campaign":  ["МК vps", "Поиск"],
        "spend_rub": [1000.0, 2000.0],
    })


def test_compute_kpi():
    k = M.compute_kpi(make_orders(), make_ads())
    assert k.spend == 3000
    assert k.revenue == 4500          # 1000 + 2000 + 1500
    assert k.orders_paid == 3         # один unpaid отфильтрован
    assert k.orders_total == 4
    assert k.unique_clients == 2      # a@a и b@b (c@c — unpaid)


def test_pareto_shares_sum_to_100():
    s = M.pareto_summary(make_orders())
    if not s:
        return
    total_pct_clients = s["A_share_clients"] + s["B_share_clients"] + s["C_share_clients"]
    total_pct_revenue = s["A_share_revenue"] + s["B_share_revenue"] + s["C_share_revenue"]
    assert abs(total_pct_clients - 100) < 0.5
    assert abs(total_pct_revenue - 100) < 0.5


def test_churn_groups_sum_to_total():
    s = M.churn_summary(make_orders())
    assert s["active"] + s["at_risk"] + s["churned"] == s["total_clients"]


def test_funnel_monotonic():
    fn = M.funnel(make_orders())
    assert not fn.empty
    # Воронка должна быть монотонно убывающей
    for i in range(1, len(fn)):
        assert fn.iloc[i]["count"] <= fn.iloc[i - 1]["count"]


def test_mrr_by_month():
    mrr = M.mrr_by_month(make_orders())
    assert not mrr.empty
    # MRR за апрель = 2000 + 1500 = 3500
    apr = mrr[mrr["payment_month"] == pd.Timestamp("2026-04-01")]
    assert float(apr["mrr"].iloc[0]) == 3500


def test_data_coverage():
    cov = M.data_coverage(make_orders(), make_ads())
    assert not cov.empty
    # Покрытие должно охватывать все месяцы между min и max
    assert (cov["has_orders"] & cov["has_ads"]).any()


def test_product_mix():
    pm = M.product_mix(make_orders(), by="product_family")
    assert not pm.empty
    # Сумма всех долей == 1
    assert abs(pm["share"].sum() - 1.0) < 0.01


def test_filter_orders_by_period():
    o = make_orders()
    filtered = M.filter_orders_by_period(
        o, pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-30")
    )
    assert len(filtered) == 3   # 3 заказа в апреле
    assert all(filtered["payment_date"].dt.month == 4)


def test_top_clients():
    tc = M.top_clients(make_orders(), n=5)
    assert not tc.empty
    # Alice: 1000+1500 = 2500, Bob: 2000 — Alice сверху
    assert tc.iloc[0]["client_key"] == "a@a"
    assert tc.iloc[0]["total_paid"] == 2500


def test_comparable_kpi_overlap():
    # Платежи: март-апрель; расходы: март-апрель → overlap есть
    ck = M.comparable_kpi(make_orders(), make_ads())
    assert ck is not None
    assert ck.spend == 3000
