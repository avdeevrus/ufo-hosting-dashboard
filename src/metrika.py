"""
Интеграция с Яндекс.Метрика API v1.

Цель: показать источники трафика и воронку покупок в дашборде
**в дополнение** к данным CSV из BILLmanager.

Важно: данные Метрики по продажам могут расходиться с реальными
оплатами в CSV — Метрика считает хиты целей (могут быть двойные
срабатывания, отказы пагинации, реклоустеризация). Поэтому
**основа — всегда CSV**, Метрика только показывает «откуда пришёл клиент».

Атрибуция по умолчанию:
  - «Последний значимый переход» (LastSign) — как настроено
    в интерфейсе Метрики UFO Hosting
  - Кросс-девайс включён

Чтобы это заработало:
  1. На oauth.yandex.ru создать приложение со scope `metrika:read`
  2. Получить OAuth-токен → положить в Streamlit Secrets
     METRIKA_TOKEN = "y0_AgAAAA..."
  3. Положить Counter ID счётчика
     METRIKA_COUNTER_ID = 102931802

Документация API: https://yandex.ru/dev/metrika/doc/api2/api_v1/intro.html
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import pandas as pd


API_BASE = "https://api-metrika.yandex.net"

# Атрибуция по умолчанию — как настроена в web-интерфейсе клиента
DEFAULT_ATTRIBUTION = "LastSign"  # Последний значимый переход


@dataclass
class MetrikaCredentials:
    token: str
    counter_id: int


def get_credentials() -> MetrikaCredentials | None:
    """Берём токен и counter_id из env / Streamlit secrets."""
    token = os.environ.get("METRIKA_TOKEN")
    counter_raw = os.environ.get("METRIKA_COUNTER_ID")
    if not token or not counter_raw:
        try:
            import streamlit as st
            token = token or st.secrets.get("METRIKA_TOKEN")  # type: ignore[attr-defined]
            counter_raw = counter_raw or st.secrets.get("METRIKA_COUNTER_ID")  # type: ignore[attr-defined]
        except Exception:
            pass
    if not token or not counter_raw:
        return None
    try:
        counter_id = int(counter_raw)
    except (TypeError, ValueError):
        return None
    return MetrikaCredentials(token=token, counter_id=counter_id)


# ============================================================
#                       Низкоуровневый запрос
# ============================================================

def _request(creds: MetrikaCredentials, params: dict,
             endpoint: str = "/stat/v1/data",
             timeout: int = 60) -> dict:
    """GET в Reports API Метрики."""
    url = f"{API_BASE}{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"OAuth {creds.token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            err = json.loads(body)
        except json.JSONDecodeError:
            err = {"raw": body[:400]}
        raise RuntimeError(
            f"Metrika API HTTP {e.code}: {err.get('message') or err.get('errors') or err}"
        )


def _base_params(creds: MetrikaCredentials, date_from: str, date_to: str,
                 attribution: str = DEFAULT_ATTRIBUTION) -> dict:
    """Базовые параметры запроса с атрибуцией LastSign по умолчанию."""
    return {
        "ids": creds.counter_id,
        "date1": date_from,
        "date2": date_to,
        "attribution": attribution,
        "accuracy": "full",  # 100% выборка (не семплированные данные)
    }


# ============================================================
#                       Цели и конверсии
# ============================================================

# ID целей счётчика UFO Hosting (получены через goals API 17.05.2026).
# Если когда-нибудь сменятся ID — обновить здесь.
GOAL_IDS = {
    "register":     455520794,   # user_register — Регистрация в BM
    "auth":         455520828,   # user_auth — Авторизация в BM
    "order_click":  461641659,   # order_click — клик на «Заказ тарифа»
    "add_to_cart":  455520986,   # user_add-item-to-cart
    "cart_view":    455521039,   # user_visit__cart
    "go_to_pay":    455522242,   # user_wizard-start — переход к оплате
    "payment_paid": 455522254,   # user_payment-paid — Успешная оплата ⭐
    "payment_free": 455522298,   # user_payment-free — Активация триала
    "e_cart":       438516796,   # Ecommerce: добавление в корзину
    "e_purchase":   438516800,   # Ecommerce: покупка (с revenue) ⭐
}


def fetch_goal_summary(creds: MetrikaCredentials,
                       date_from: str, date_to: str) -> pd.DataFrame:
    """По всем ключевым целям: достижения, уникальные пользователи, доход.
    Используется для строки «воронка» в дашборде."""
    rows = []
    for goal_key, goal_id in GOAL_IDS.items():
        metrics = (f"ym:s:goal{goal_id}reaches,"
                   f"ym:s:goal{goal_id}users,"
                   f"ym:s:goal{goal_id}revenue")
        params = _base_params(creds, date_from, date_to)
        params["metrics"] = metrics
        try:
            d = _request(creds, params)
        except RuntimeError:
            continue
        totals = d.get("totals", [0, 0, 0])
        rows.append({
            "goal_key": goal_key,
            "goal_id": goal_id,
            "reaches": int(totals[0]),
            "users":   int(totals[1]),
            "revenue": float(totals[2]),
        })
    return pd.DataFrame(rows)


def fetch_revenue_by_source(creds: MetrikaCredentials,
                            date_from: str, date_to: str,
                            *, goal_id: int = GOAL_IDS["e_purchase"],
                            limit: int = 20) -> pd.DataFrame:
    """Доход и покупки разрезом по lastSourceEngine.
    Возвращает: source, revenue, purchases, visits."""
    metrics = (f"ym:s:goal{goal_id}revenue,"
               f"ym:s:goal{goal_id}reaches,"
               f"ym:s:visits")
    params = _base_params(creds, date_from, date_to)
    params.update({
        "metrics": metrics,
        "dimensions": "ym:s:lastSourceEngine",
        "limit": limit,
        "sort": f"-ym:s:goal{goal_id}revenue",
    })
    d = _request(creds, params)
    rows = []
    for row in d.get("data", []):
        rows.append({
            "source":    row["dimensions"][0].get("name", "—") or "—",
            "revenue":   float(row["metrics"][0]),
            "purchases": int(row["metrics"][1]),
            "visits":    int(row["metrics"][2]),
        })
    return pd.DataFrame(rows)


def fetch_revenue_by_direct_campaign(creds: MetrikaCredentials,
                                     date_from: str, date_to: str,
                                     *, goal_id: int = GOAL_IDS["e_purchase"],
                                     limit: int = 30) -> pd.DataFrame:
    """Доход и покупки по Я.Директ кампаниям (по lastDirectClickOrderName).
    Только визиты где traffic source = 'ad' (платная реклама)."""
    metrics = (f"ym:s:goal{goal_id}revenue,"
               f"ym:s:goal{goal_id}reaches,"
               f"ym:s:visits")
    params = _base_params(creds, date_from, date_to)
    params.update({
        "metrics": metrics,
        "dimensions": "ym:s:lastDirectClickOrderName",
        "filters": "ym:s:lastTrafficSource=='ad'",
        "limit": limit,
        "sort": f"-ym:s:goal{goal_id}revenue",
    })
    d = _request(creds, params)
    rows = []
    for row in d.get("data", []):
        camp = row["dimensions"][0].get("name", "(не определена)") or "(не определена)"
        rows.append({
            "campaign":  camp,
            "revenue":   float(row["metrics"][0]),
            "purchases": int(row["metrics"][1]),
            "visits":    int(row["metrics"][2]),
        })
    return pd.DataFrame(rows)


def fetch_funnel(creds: MetrikaCredentials,
                 date_from: str, date_to: str) -> pd.DataFrame:
    """Воронка: визит → клик на заказ → корзина → переход к оплате → оплата.
    Возвращает DataFrame: stage, users, conv_from_prev.
    """
    summary = fetch_goal_summary(creds, date_from, date_to)
    if summary.empty:
        return pd.DataFrame()
    by_key = {row["goal_key"]: row["users"] for _, row in summary.iterrows()}

    # Общие визиты — нужны как первая ступень
    metrics = "ym:s:visits,ym:s:users"
    params = _base_params(creds, date_from, date_to)
    params["metrics"] = metrics
    try:
        d = _request(creds, params)
        total_users = int(d.get("totals", [0, 0])[1])
    except RuntimeError:
        total_users = 0

    stages = [
        ("Уникальные посетители",  total_users),
        ("Клик на «Заказ тарифа»", by_key.get("order_click", 0)),
        ("Добавили в корзину",     by_key.get("add_to_cart", 0)),
        ("Перешли к оплате",       by_key.get("go_to_pay", 0)),
        ("Оплатили",               by_key.get("payment_paid", 0)),
    ]
    rows = []
    prev = None
    for stage, n in stages:
        # Защита от TypeError (prev=None для 1-го этапа) и от деления на 0.
        # ВАЖНО: prev обновляем всегда, даже если n=0, иначе следующий
        # этап считает % от ещё более раннего prev, что искажает воронку.
        if prev is None or prev <= 0:
            conv = 100.0 if prev is None else 0.0
        else:
            conv = n / prev * 100
        rows.append({"stage": stage, "users": n, "conv_from_prev_pct": conv})
        prev = n
    return pd.DataFrame(rows)
