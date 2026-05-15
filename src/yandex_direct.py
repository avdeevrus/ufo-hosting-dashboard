"""
Заготовка интеграции с Яндекс.Директ Reports API v5.

Чтобы это заработало, нужно:
  1. Зарегистрировать приложение в OAuth Яндекса: https://oauth.yandex.ru
     scope = `direct:api`
  2. Получить OAuth-токен (обычная пользовательская авторизация — кнопкой в браузере).
  3. Положить токен в переменную окружения YANDEX_DIRECT_TOKEN
     (либо в Streamlit Secrets — `st.secrets["yandex_direct_token"]`).

Документация: https://yandex.ru/dev/direct/doc/reports/reports.html

Без токена модуль не делает запросов — UI просто покажет, что нет подключения.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import pandas as pd
import requests


REPORTS_URL = "https://api.direct.yandex.com/json/v5/reports"


@dataclass
class DirectCredentials:
    token: str
    client_login: str | None = None  # для агентов; для прямого аккаунта оставить None


def get_credentials() -> DirectCredentials | None:
    """Берём токен из env / Streamlit secrets, если есть."""
    token = os.environ.get("YANDEX_DIRECT_TOKEN")
    if not token:
        try:
            import streamlit as st
            token = st.secrets.get("yandex_direct_token")  # type: ignore[attr-defined]
        except Exception:
            token = None
    if not token:
        return None
    login = os.environ.get("YANDEX_DIRECT_CLIENT_LOGIN")
    return DirectCredentials(token=token, client_login=login)


def fetch_campaign_report(creds: DirectCredentials,
                          date_from: str,
                          date_to: str) -> pd.DataFrame:
    """Тянем отчёт по кампаниям за период (YYYY-MM-DD).
    Возвращаем DataFrame с колонками: date, campaign, impressions, clicks, spend_rub.
    """
    import io
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
        "processingMode": "auto",
        "returnMoneyInMicros": "false",
        "skipReportHeader": "true",
        "skipColumnHeader": "false",
        "skipReportSummary": "true",
    }
    if creds.client_login:
        headers["Client-Login"] = creds.client_login

    body = {
        "params": {
            "SelectionCriteria": {"DateFrom": date_from, "DateTo": date_to},
            "FieldNames": ["Date", "CampaignName", "Impressions", "Clicks", "Cost"],
            "ReportName": f"campaigns_{date_from}_{date_to}_{int(time.time())}",
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": "YES",
            "IncludeDiscount": "NO",
        }
    }

    # Reports API асинхронный: до 5 повторов с ожиданием
    for _ in range(20):
        r = requests.post(REPORTS_URL, json=body, headers=headers, timeout=60)
        if r.status_code in (201, 202):
            wait = int(r.headers.get("retryIn", "5"))
            time.sleep(wait)
            continue
        if r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text), sep="\t")
            df = df.rename(columns={
                "Date": "date",
                "CampaignName": "campaign",
                "Impressions": "impressions",
                "Clicks": "clicks",
                "Cost": "spend_rub",
            })
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            return df
        r.raise_for_status()
    raise TimeoutError("Не удалось получить отчёт Яндекс.Директ за разумное время")


def to_ads_dataframe(report_df: pd.DataFrame) -> pd.DataFrame:
    """Конвертируем дневной отчёт API в наш ads-формат (помесячный)."""
    if report_df is None or report_df.empty:
        return pd.DataFrame()
    df = report_df.copy()
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    g = (df.groupby(["month", "campaign"], as_index=False)
         .agg(spend_rub=("spend_rub", "sum")))
    g["source_file"] = "Yandex.Direct API"
    g["source_sheet"] = "API"
    return g
