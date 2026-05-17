#!/usr/bin/env python3
"""
Загружает оплаты UFO Hosting в Я.Метрику как офлайн-конверсии.

Зачем: после загрузки Я.Директ видит реальный доход per кампания/ключ →
автостратегии оптимизируются на оплаты вместо кликов → CAC падает.

API: https://yandex.ru/dev/metrika/doc/api2/practice/upload-conversion.html

Запуск:
    python3 upload.py --csv path/to/orders.csv --days 7
    python3 upload.py --csv path/to/orders.csv --days 7 --dry-run

Environment:
    METRIKA_TOKEN        — OAuth токен со scope metrika:write
    METRIKA_COUNTER_ID   — ID счётчика Метрики (число)
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests


API_BASE = "https://api-metrika.yandex.net"

logger = logging.getLogger("ufo-conversions")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", required=True,
                   help="Путь к CSV «Содержимое заказов» с колонкой metrika_client_id")
    p.add_argument("--days", type=int, default=7,
                   help="Брать оплаты за последние N дней (по умолчанию 7)")
    p.add_argument("--target", default="payment",
                   help="ID цели в Метрике (по умолчанию 'payment')")
    p.add_argument("--dry-run", action="store_true",
                   help="Показать, что будет залито, но не отправлять")
    return p.parse_args()


def load_paid_orders(csv_path: str, days: int) -> pd.DataFrame:
    """Читает CSV, фильтрует оплаченные за последние N дней,
    оставляет только с metrika_client_id."""
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df.columns = [c.strip().strip('"').strip() for c in df.columns]

    # «Статус оплаты» == «Оплачен»
    is_paid = df["Статус оплаты"].str.strip().str.lower() == "оплачен"

    # «Дата платежа» в последние N дней
    pay_date = pd.to_datetime(df["Дата платежа"], errors="coerce")
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    is_recent = pay_date >= cutoff

    paid = df[is_paid & is_recent].copy()
    logger.info(f"Read {len(paid)} paid orders from CSV (last {days} days)")

    # Без ClientID — пропускаем (визита Метрики нет, заливать некуда)
    if "metrika_client_id" not in paid.columns:
        logger.error(
            "В CSV нет колонки 'metrika_client_id' — этап 1 (захват ClientID "
            "в форме регистрации) ещё не работает. См. ../README.md этап 1."
        )
        sys.exit(2)

    with_cid = paid["metrika_client_id"].astype(str).str.strip() != ""
    skipped = (~with_cid).sum()
    paid = paid[with_cid].copy()
    paid["payment_date_dt"] = pay_date[paid.index]
    paid["payment_amount_num"] = pd.to_numeric(
        paid["Сумма оплаты"].str.replace(r"[^\d.,-]", "", regex=True)
                              .str.replace(",", "."),
        errors="coerce",
    ).fillna(0)
    logger.info(
        f"Filtered to {len(paid)} with metrika_client_id "
        f"({skipped} без ClientID — пропущены)"
    )
    return paid


def build_conversions_csv(paid: pd.DataFrame, target: str) -> str:
    """Формирует CSV в формате Метрики:
    ClientId,Target,DateTime,Price,Currency
    (DateTime — Unix timestamp в секундах)
    """
    out = pd.DataFrame({
        "ClientId":  paid["metrika_client_id"].astype(str),
        "Target":    target,
        "DateTime":  paid["payment_date_dt"].astype("int64") // 10**9,
        "Price":     paid["payment_amount_num"].round(2),
        "Currency":  "RUB",
    })
    buf = io.StringIO()
    out.to_csv(buf, index=False)
    return buf.getvalue()


def upload_to_metrika(counter_id: str, token: str, csv_text: str) -> dict:
    """POST в /management/v1/counter/{id}/offline_conversions/upload"""
    url = f"{API_BASE}/management/v1/counter/{counter_id}/offline_conversions/upload"
    files = {"file": ("conversions.csv", csv_text, "text/csv")}
    params = {"client_id_type": "CLIENT_ID"}  # = Metrika ClientID (не USER_ID)
    headers = {"Authorization": f"OAuth {token}"}

    r = requests.post(url, params=params, files=files, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def main() -> None:
    args = parse_args()
    token = os.environ.get("METRIKA_TOKEN")
    counter_id = os.environ.get("METRIKA_COUNTER_ID")
    if not args.dry_run and (not token or not counter_id):
        logger.error("Нужны env-переменные METRIKA_TOKEN и METRIKA_COUNTER_ID "
                     "(или флаг --dry-run для проверки без отправки)")
        sys.exit(1)

    paid = load_paid_orders(args.csv, args.days)
    if paid.empty:
        logger.info("Нет оплат для загрузки — выходим.")
        return

    csv_text = build_conversions_csv(paid, args.target)

    if args.dry_run:
        logger.info("DRY-RUN — не отправляем в Метрику. Первые 5 строк CSV:")
        for line in csv_text.splitlines()[:6]:
            print("  " + line)
        logger.info(f"Всего к загрузке: {len(paid)} конверсий")
        return

    logger.info(f"Sending to Metrika counter {counter_id}, goal={args.target}...")
    result = upload_to_metrika(counter_id, token, csv_text)
    uploading = result.get("uploading", {})
    logger.info(
        f"✓ Uploaded {len(paid)} conversions, "
        f"id={uploading.get('id')}, status={uploading.get('status')}"
    )


if __name__ == "__main__":
    main()
