"""
Persistent storage поверх Hugging Face Datasets.

Идея: дашборд работает на эфемерной FS (HF Space Docker), но мы храним
загруженные клиентами выгрузки в приватном HF Dataset. При старте Space
скачиваем все файлы в локальный кэш — парсеры видят их как обычные файлы
на диске. При загрузке нового файла через UI — заливаем в Dataset, чтобы
следующий пользователь его тоже видел.

Требует HF_TOKEN с правами write на namespace владельца Dataset.
В HF Space Secrets добавьте: `HF_TOKEN`.
"""

from __future__ import annotations

import os
from pathlib import Path

DATASET_REPO = "avdeevrus/ufo-hosting-data"  # private
DATASET_TYPE = "dataset"

CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
ORDERS_SUBDIR = "orders"
ADS_SUBDIR = "ads"


def _get_token() -> str | None:
    token = os.environ.get("HF_TOKEN")
    if token:
        return token
    try:
        import streamlit as st
        return st.secrets.get("HF_TOKEN")  # type: ignore[attr-defined]
    except Exception:
        return None


def is_enabled() -> bool:
    return _get_token() is not None


def _api():
    from huggingface_hub import HfApi
    return HfApi(token=_get_token())


def ensure_dataset_exists() -> bool:
    """Создаём private dataset, если его ещё нет. Идемпотентно."""
    token = _get_token()
    if not token:
        return False
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        api.create_repo(
            repo_id=DATASET_REPO,
            repo_type=DATASET_TYPE,
            private=True,
            exist_ok=True,
        )
        return True
    except Exception:
        return False


def sync_down() -> dict:
    """Скачиваем все файлы из dataset в локальный кэш data/.
    Возвращает счётчик скачанных файлов + диагностику."""
    token = _get_token()
    if not token:
        return {"orders": 0, "ads": 0, "enabled": False, "error": "no_token"}
    try:
        from huggingface_hub import HfApi, hf_hub_download
        api = HfApi(token=token)
        files = api.list_repo_files(repo_id=DATASET_REPO, repo_type=DATASET_TYPE)
    except Exception as e:
        return {"orders": 0, "ads": 0, "enabled": True, "error": f"list_failed: {type(e).__name__}: {str(e)[:200]}"}

    counts = {"orders": 0, "ads": 0, "enabled": True, "files_in_dataset": len(files)}
    last_err = None
    for f in files:
        if not (f.startswith(f"{ORDERS_SUBDIR}/") or f.startswith(f"{ADS_SUBDIR}/")):
            continue
        try:
            hf_hub_download(
                repo_id=DATASET_REPO,
                repo_type=DATASET_TYPE,
                filename=f,
                token=token,
                local_dir=str(CACHE_DIR),
            )
            if f.startswith(f"{ORDERS_SUBDIR}/"):
                counts["orders"] += 1
            else:
                counts["ads"] += 1
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:200]}"
            continue
    if last_err:
        counts["error"] = last_err
    return counts


def upload_orders_csv(filename: str, content: bytes) -> bool:
    return _upload(filename, content, ORDERS_SUBDIR)


def upload_ads_xlsx(filename: str, content: bytes) -> bool:
    return _upload(filename, content, ADS_SUBDIR)


def _upload(filename: str, content: bytes, subdir: str) -> bool:
    token = _get_token()
    if not token:
        return False
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        # сначала пишем локально (для текущей сессии)
        local_path = CACHE_DIR / subdir / filename
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)
        # потом отправляем в dataset
        api.upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=f"{subdir}/{filename}",
            repo_id=DATASET_REPO,
            repo_type=DATASET_TYPE,
        )
        return True
    except Exception as e:
        print(f"Upload failed: {e}")
        return False


def list_remote() -> list[str]:
    token = _get_token()
    if not token:
        return []
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        return api.list_repo_files(repo_id=DATASET_REPO, repo_type=DATASET_TYPE)
    except Exception:
        return []


def sync_api_cache_down():
    """Скачиваем api_cache/yd_rolling.json из dataset и возвращаем DataFrame
    с расходами Я.Директ (помесячно). Используется на старте Streamlit, чтобы
    дашборд видел свежие данные без ручного нажатия Sync."""
    import pandas as pd
    token = _get_token()
    if not token:
        return pd.DataFrame()
    try:
        from huggingface_hub import hf_hub_download
        local = hf_hub_download(
            repo_id=DATASET_REPO,
            repo_type=DATASET_TYPE,
            filename="api_cache/yd_rolling.json",
            token=token,
            local_dir=str(CACHE_DIR),
        )
        df = pd.read_json(local)
        if not df.empty and "month" in df.columns:
            df["month"] = pd.to_datetime(df["month"])
        return df
    except Exception:
        return pd.DataFrame()


# ─── Кэш «качества рекламы» (3 json'a) ───────────────────────
# Эти файлы — кэш CTR/CPC/конверсий по кампаниям, ключевикам и объявлениям.
# Они большие (несколько МБ) и долго грузятся из Я.Директа (3 года × 3 отчёта
# с лимитом 20 req/10 sec ≈ 30 секунд). На эфемерной FS Streamlit Cloud они
# стираются при каждом деплое → пользователь видит автозагрузку каждый раз.
# Заливаем в HF Dataset чтобы переживали рестарты контейнера.

QUALITY_CACHE_FILES = (
    "yd_campaign_quality.json",
    "yd_keywords.json",
    "yd_ads_creatives.json",
)


def sync_quality_cache_down() -> dict:
    """Скачиваем api_cache/yd_*.json с HF в локальный data/api_cache/.
    Вызывается при старте каждой страницы, чтобы автозагрузка не дёргалась
    после рестарта контейнера. Возвращает счётчик скачанных файлов."""
    token = _get_token()
    if not token:
        return {"downloaded": 0, "enabled": False}
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return {"downloaded": 0, "enabled": False, "error": "no_hf_hub"}

    downloaded = 0
    for fname in QUALITY_CACHE_FILES:
        try:
            hf_hub_download(
                repo_id=DATASET_REPO,
                repo_type=DATASET_TYPE,
                filename=f"api_cache/{fname}",
                token=token,
                local_dir=str(CACHE_DIR),
            )
            downloaded += 1
        except Exception:
            # 404/network/etc — файла просто нет на HF, это нормально
            continue
    return {"downloaded": downloaded, "enabled": True}


def sync_quality_cache_up(filename: str) -> bool:
    """Заливаем один файл из data/api_cache/ в HF Dataset.
    Вызывается после успешного fetch+save_quality_cache, чтобы следующая
    сессия / следующий деплой увидели свежий кэш."""
    token = _get_token()
    if not token:
        return False
    if filename not in QUALITY_CACHE_FILES:
        return False
    local_path = CACHE_DIR / "api_cache" / filename
    if not local_path.exists():
        return False
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        api.upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=f"api_cache/{filename}",
            repo_id=DATASET_REPO,
            repo_type=DATASET_TYPE,
        )
        return True
    except Exception as e:
        print(f"Upload quality cache failed: {e}")
        return False


def delete_remote(filename: str, subdir: str) -> bool:
    token = _get_token()
    if not token:
        return False
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        api.delete_file(
            path_in_repo=f"{subdir}/{filename}",
            repo_id=DATASET_REPO,
            repo_type=DATASET_TYPE,
        )
        local_path = CACHE_DIR / subdir / filename
        if local_path.exists():
            local_path.unlink()
        return True
    except Exception:
        return False
