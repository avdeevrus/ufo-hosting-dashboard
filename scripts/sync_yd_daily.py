"""Ежедневная синхронизация Я.Директ → HF Dataset.

Запускается GitHub Action раз в сутки. Тянет статистику за последние
WINDOW_DAYS дней (rolling window) и сохраняет JSON в HF Dataset
по пути api_cache/yd_rolling.json.

Streamlit при старте подтягивает этот файл и совмещает с XLSX-данными,
поэтому дашборд всегда имеет актуальные расходы без ручной кнопки Sync.

Требуются env vars:
- YANDEX_DIRECT_TOKEN
- HF_TOKEN
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
from huggingface_hub import HfApi

from yandex_direct import (
    DirectCredentials,
    fetch_campaign_report,
    to_ads_dataframe,
)

WINDOW_DAYS = 60
DATASET_REPO = "avdeevrus/ufo-hosting-data"
DATASET_PATH = "api_cache/yd_rolling.json"


def main():
    yd_token = os.environ.get("YANDEX_DIRECT_TOKEN")
    hf_token = os.environ.get("HF_TOKEN")
    if not yd_token:
        print("ERROR: YANDEX_DIRECT_TOKEN not set")
        sys.exit(1)
    if not hf_token:
        print("ERROR: HF_TOKEN not set")
        sys.exit(1)

    date_to = date.today()
    date_from = date_to - timedelta(days=WINDOW_DAYS - 1)

    print(f"Fetching Я.Директ report: {date_from} → {date_to}")
    creds = DirectCredentials(
        token=yd_token,
        client_login=os.environ.get("YANDEX_DIRECT_CLIENT_LOGIN"),
    )
    report = fetch_campaign_report(creds, date_from=str(date_from), date_to=str(date_to))
    ads = to_ads_dataframe(report)

    if ads.empty:
        print("WARNING: API returned empty report. Aborting upload.")
        return

    out_dir = Path("data/api_cache")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "yd_rolling.json"
    serializable = ads.copy()
    serializable["month"] = serializable["month"].dt.strftime("%Y-%m-%d")
    serializable.to_json(out_path, orient="records", force_ascii=False, indent=2)
    print(f"Wrote {len(ads)} rows to {out_path}")

    api = HfApi(token=hf_token)
    api.upload_file(
        path_or_fileobj=str(out_path),
        path_in_repo=DATASET_PATH,
        repo_id=DATASET_REPO,
        repo_type="dataset",
        commit_message=f"Daily sync {date_to.isoformat()}: {len(ads)} rows ({date_from} - {date_to})",
    )
    print(f"Uploaded to https://huggingface.co/datasets/{DATASET_REPO}/blob/main/{DATASET_PATH}")
    print(
        f"Spend total: "
        + f"{ads['spend_rub'].sum():,.0f} ₽".replace(",", " ")
    )


if __name__ == "__main__":
    main()
