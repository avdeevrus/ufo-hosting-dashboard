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


def test_cohort_payback_preserves_spend_without_cohorts():
    """Расход в месяцы без платящих клиентов не должен «теряться» из pb.

    Регрессионный тест: до фикса hero «Вложено» показывал меньше шапки,
    потому что cohort_payback индексировался только по месяцам с
    регистрациями платящих клиентов.
    """
    # Добавим месяц мая 2026 с расходом 5000₽, но без клиентов
    ads_with_extra_month = pd.concat([
        make_ads(),
        pd.DataFrame({
            "month":     [pd.Timestamp("2026-05-01")],
            "campaign":  ["Поиск"],
            "spend_rub": [5000.0],
        }),
    ], ignore_index=True)

    pb = M.cohort_payback(make_orders(), ads_with_extra_month)
    # Расход в pb должен равняться полному расходу из ads
    assert pb["ad_spend"].sum() == ads_with_extra_month["spend_rub"].sum()
    # Месяц без клиентов должен быть в индексе с clients=0
    assert pd.Timestamp("2026-05-01") in pb.index
    assert pb.loc[pd.Timestamp("2026-05-01"), "clients"] == 0
    assert pb.loc[pd.Timestamp("2026-05-01"), "ad_spend"] == 5000.0


def test_cohort_payback_only_spend_no_orders():
    """Edge case: есть расход, но ни одной оплаты — не должно падать."""
    empty_orders = make_orders().iloc[0:0]
    pb = M.cohort_payback(empty_orders, make_ads())
    assert not pb.empty
    assert pb["ad_spend"].sum() == 3000.0
    assert (pb["clients"] == 0).all()


def test_has_attribution_false_without_utm():
    """Если в orders нет колонки utm_campaign — has_attribution = False."""
    assert M.has_attribution(make_orders()) is False


def test_has_attribution_false_when_utm_all_empty():
    """Колонка есть, но все значения пустые — has_attribution = False."""
    o = make_orders()
    o["utm_campaign"] = ""
    assert M.has_attribution(o) is False


def test_has_attribution_true_when_at_least_one_utm():
    o = make_orders()
    o["utm_campaign"] = ["Поиск vps", "", "", ""]
    assert M.has_attribution(o) is True


def test_roi_by_campaign_basic():
    """Доход атрибутируется к utm_campaign, расход — к ads.campaign."""
    o = make_orders()
    # Все клиенты пришли с одной кампании «Поиск vps»; одна оплата без UTM
    o["utm_campaign"] = ["Поиск vps", "Поиск vps", "Поиск vps", ""]
    o["utm_source"] = ["yandex", "yandex", "yandex", ""]
    o["utm_term"] = ["купить vps", "хостинг", "vps дешево", ""]

    ads = pd.DataFrame({
        "month":     pd.to_datetime(["2026-03-01", "2026-04-01"]),
        "campaign":  ["Поиск vps", "МК тест"],
        "spend_rub": [1000.0, 2000.0],
    })

    roi = M.roi_by_campaign(o, ads)
    assert not roi.empty
    # Должны быть строки для обеих кампаний (outer merge)
    campaigns = set(roi["campaign"])
    assert "Поиск vps" in campaigns
    assert "МК тест" in campaigns
    # «Поиск vps» — есть и доход и расход
    poisk = roi[roi["campaign"] == "Поиск vps"].iloc[0]
    assert poisk["revenue"] == 4500  # 1000+2000+1500 (3 paid с этой UTM)
    assert poisk["spend_rub"] == 1000
    assert abs(poisk["romi_pct"] - 350.0) < 0.1  # (4500-1000)/1000*100 = 350%
    # «МК тест» — только расход, нет оплат → revenue=0, romi отрицательный
    mk = roi[roi["campaign"] == "МК тест"].iloc[0]
    assert mk["revenue"] == 0
    assert mk["spend_rub"] == 2000


def test_roi_by_campaign_empty_without_utm():
    """Без utm_campaign roi_by_campaign возвращает пустой DataFrame."""
    roi = M.roi_by_campaign(make_orders(), make_ads())
    assert roi.empty


def test_roi_by_keyword_basic():
    """utm_term склеивается с criterion из keyword-отчёта."""
    o = make_orders()
    o["utm_campaign"] = ["Поиск vps"] * 3 + [""]
    o["utm_term"] = ["купить vps", "хостинг", "купить vps", ""]

    kw = pd.DataFrame({
        "campaign":  ["Поиск vps"] * 2,
        "criterion": ["купить vps", "хостинг"],
        "spend_rub": [500.0, 300.0],
        "clicks":    [100, 50],
    })

    roi = M.roi_by_keyword(o, kw)
    assert not roi.empty
    # «купить vps» — 2 оплаты (1000+1500) против 500 расхода → ROMI 400%
    kv = roi[roi["criterion"] == "купить vps"].iloc[0]
    assert kv["revenue"] == 2500
    assert kv["spend_rub"] == 500
    assert abs(kv["romi_pct"] - 400.0) < 0.1
