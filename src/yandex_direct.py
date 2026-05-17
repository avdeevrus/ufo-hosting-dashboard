"""
Интеграция с Яндекс.Директ Reports API v5.

Чтобы это заработало:
  1. Зарегистрировать приложение в OAuth Яндекса: https://oauth.yandex.ru
     scope = `direct:api`
  2. Получить OAuth-токен.
  3. Положить токен в переменную окружения YANDEX_DIRECT_TOKEN
     (либо в Streamlit Secrets — `st.secrets["yandex_direct_token"]`).

Документация: https://yandex.ru/dev/direct/doc/reports/reports.html

Поддерживаемые отчёты:
  - CAMPAIGN_PERFORMANCE_REPORT   — расход + базовые метрики по кампаниям
  - CAMPAIGN_QUALITY_REPORT       — расширенный (CTR/CPC/Conv/Bounce)
  - CRITERIA_PERFORMANCE_REPORT   — ключевые слова / критерии таргетинга
  - AD_PERFORMANCE_REPORT         — объявления (креативы)

Без токена модуль не делает запросов — UI просто покажет, что нет подключения.
"""

from __future__ import annotations

import io
import os
import threading
import time
from dataclasses import dataclass

import pandas as pd
import requests


REPORTS_URL = "https://api.direct.yandex.com/json/v5/reports"


# ============================================================
#              Глобальный rate limiter + retry
# ============================================================
#
# Reports API: 20 запросов / 10 сек на метод. Превышение → ошибка 56.
# Берём с запасом 15/10 — оставляет место для polling 201/202 без
# выбивания лимита, когда параллельно тянутся 3 отчёта × N чанков.

_REPORTS_RATE_MAX_CALLS = 15
_REPORTS_RATE_WINDOW_SEC = 10.0
_POST_MAX_RETRIES = 6


class _SlidingWindowLimiter:
    """Thread-safe sliding-window лимитер.

    Гарантирует, что не более `max_calls` вызовов произойдёт за любое окно
    в `window_seconds` секунд. Если лимит достигнут — блокирует до момента,
    когда самый старый вызов «вытечет» из окна.
    """

    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls = max_calls
        self.window = window_seconds
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                cutoff = now - self.window
                # Чистим устаревшие записи (старше окна)
                self._calls = [t for t in self._calls if t > cutoff]
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                # Лимит выбран — ждём пока самый старый «вытечет» + 100ms запас
                wait = self._calls[0] + self.window - now + 0.1
            # Min sleep 0.1s — иначе при wait≈0 множественные потоки
            # входят в busy-wait по 50ms и нагружают CPU без пользы.
            time.sleep(max(0.1, wait))


_REPORTS_LIMITER = _SlidingWindowLimiter(
    max_calls=_REPORTS_RATE_MAX_CALLS,
    window_seconds=_REPORTS_RATE_WINDOW_SEC,
)


def _parse_api_error_code(r: requests.Response):
    """Достаёт error_code из JSON-ответа API. None если тела/кода нет."""
    try:
        r.encoding = "utf-8"
        return r.json().get("error", {}).get("error_code")
    except (ValueError, KeyError, AttributeError):
        return None


def _post_with_retry(body: dict, headers: dict, *,
                     timeout: int = 90,
                     max_retries: int = _POST_MAX_RETRIES) -> requests.Response:
    """POST в Reports API с rate-limiting + retry на временные ошибки.

    Retry на: ошибку 56 (rate limit), 152 (отчёт уже строится),
    HTTP 429/5xx, сетевые таймауты/обрывы. Backoff экспоненциальный.
    Возвращает финальный Response (включая успешные 200/201/202 и
    не-retry-able ошибки — их разберёт вызывающий код).
    """
    last_exc: BaseException | None = None
    r: requests.Response | None = None   # инициализация — иначе при всех
                                         # сетевых сбоях получим UnboundLocalError
    for attempt in range(max_retries):
        _REPORTS_LIMITER.acquire()
        try:
            r = requests.post(REPORTS_URL, json=body, headers=headers, timeout=timeout)
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            last_exc = e
            # Сетевой сбой → backoff и retry
            time.sleep(min(30, 2 ** attempt + 1))
            continue

        # HTTP 429 Too Many Requests — Retry-After в секундах
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "11"))
            time.sleep(max(wait, 11))
            continue

        # HTTP 5xx — серверная ошибка Яндекса, имеет смысл повторить
        if 500 <= r.status_code < 600:
            time.sleep(min(30, 2 ** attempt + 1))
            continue

        # Прикладные ошибки в JSON — смотрим error_code
        if r.status_code >= 400:
            code = _parse_api_error_code(r)
            if code in (56, "56"):
                # Превышен лимит метода — ждём окно (10 сек) + запас
                time.sleep(_REPORTS_RATE_WINDOW_SEC + 1 + attempt)
                continue
            if code in (152, "152"):
                # Отчёт уже строится — подождём и повторим
                time.sleep(5 + 2 * attempt)
                continue

        return r

    # Все попытки исчерпаны. Если r ни разу не присвоен (только сетевые
    # сбои подряд) — поднимаем last_exc. Иначе возвращаем последний ответ
    # для разбора в _handle_api_error.
    if r is None:
        raise last_exc if last_exc is not None else RuntimeError(
            "Я.Директ API: нет ответа после всех попыток retry"
        )
    return r


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


# ============================================================
#                     Низкоуровневый запрос
# ============================================================

def _api_headers(creds: DirectCredentials) -> dict:
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
    return headers


def _handle_api_error(r: requests.Response) -> None:
    """Поднимает RuntimeError с человекочитаемым сообщением по ошибке API."""
    try:
        r.encoding = "utf-8"
        err = r.json().get("error", {})
        code = err.get("error_code")
        es = err.get("error_string", "")
        ed = err.get("error_detail", "")
        msg = f"Я.Директ API ошибка {code}: {es}"
        if ed:
            msg += f" — {ed}"
        if code in (53, "53"):
            msg += "\n→ В OAuth-приложении должно быть право «Использование API Директа»."
        elif code in (54, "54"):
            msg += "\n→ За период нет рекламных кампаний."
        elif code in (58, "58"):
            msg += (
                "\n→ Нужна модерация Яндекса: зайдите на direct.yandex.ru → "
                "Инструменты → Управление доступом → API → подайте заявку на доступ. "
                "Модерация до 1–2 рабочих дней. До этого момента используйте XLSX-выгрузки."
            )
        elif code in (8800, "8800"):
            msg += "\n→ Агентский аккаунт. Добавьте YANDEX_DIRECT_CLIENT_LOGIN в Space Secrets."
        elif code in (152, "152"):
            msg += "\n→ Отчёт уже строится, попробуйте через минуту."
        elif code in (56, "56"):
            msg += (
                "\n→ Превышен лимит частоты (20 req/10 sec). Все retry "
                "(6 раз с backoff) уже выполнены — подождите 1-2 минуты "
                "и нажмите «Подтянуть качество» ещё раз."
            )
        elif code in (4001, "4001"):
            # Самая частая причина 4001 — DateFrom раньше «3 года от текущего месяца»
            msg += (
                "\n→ API отдаёт статистику только за последние 3 года от текущего месяца. "
                "Уменьшите «С даты» в сайдбаре до значения не ранее этого ограничения."
            )
        elif code in (8000, "8000"):
            msg += (
                "\n→ Некорректный запрос (например, неверный ReportType или поля). "
                "Если ошибка повторяется — пришлите её Claude, он адаптирует код."
            )
        raise RuntimeError(msg)
    except (ValueError, KeyError):
        raise RuntimeError(f"Я.Директ API HTTP {r.status_code}: {r.text[:400]}")


def _fetch_report(creds: DirectCredentials, body: dict,
                  max_wait_iters: int = 30) -> pd.DataFrame:
    """Generic: посылает body в Reports API, ждёт async-готовности и парсит TSV.

    Reports API возвращает 201/202 пока отчёт строится; повторяем до
    max_wait_iters раз с задержкой из заголовка retryIn. На 200 — парсим TSV.

    Все запросы идут через `_post_with_retry`, который соблюдает глобальный
    rate limit (15 req / 10 sec) и сам ретраит ошибки 56/152/429/5xx/сетевые.
    """
    headers = _api_headers(creds)
    for _ in range(max_wait_iters):
        r = _post_with_retry(body, headers, timeout=90)
        if r.status_code in (201, 202):
            wait = int(r.headers.get("retryIn", "5"))
            time.sleep(wait)
            continue
        if r.status_code == 200:
            return pd.read_csv(io.StringIO(r.text), sep="\t")
        if r.status_code >= 400:
            _handle_api_error(r)
        r.raise_for_status()
    raise TimeoutError("Не удалось получить отчёт Яндекс.Директ за разумное время")


def _build_body(report_type: str, field_names: list[str],
                date_from: str, date_to: str,
                *, include_vat: str = "YES",
                report_name: str | None = None) -> dict:
    name = report_name or f"{report_type}_{date_from}_{date_to}_{int(time.time())}"
    return {
        "params": {
            "SelectionCriteria": {"DateFrom": date_from, "DateTo": date_to},
            "FieldNames": field_names,
            "ReportName": name,
            "ReportType": report_type,
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": include_vat,
            "IncludeDiscount": "NO",
        }
    }


def _chunked_periods(date_from: str, date_to: str, chunk_days: int = 90):
    """Разбивает [date_from, date_to] на куски по chunk_days.

    Reports API имеет лимит 92 дня для KEYWORD/AD performance reports —
    если запросить больше, API молча обрезает или отдаёт пусто.
    """
    start = pd.Timestamp(date_from)
    end = pd.Timestamp(date_to)
    cur = start
    while cur <= end:
        chunk_end = min(cur + pd.Timedelta(days=chunk_days - 1), end)
        yield cur.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        cur = chunk_end + pd.Timedelta(days=1)


def _fetch_chunked(creds: DirectCredentials,
                   report_type: str,
                   field_names: list[str],
                   date_from: str, date_to: str,
                   *, max_workers: int = 3,
                   progress_callback=None) -> pd.DataFrame:
    """Тянет отчёт чанками по 90 дней ПАРАЛЛЕЛЬНО и склеивает в один DataFrame.

    Reports API асинхронный (201/202 пока строится → poll → 200 готово).
    Каждый чанк может занимать 10-60 секунд из-за polling. Если их 12+
    и тянуть последовательно — это легко 5-10 минут. Параллельно с 3 потоками
    (под глобальный rate limiter 15 req/10 sec) сокращает в 3×, не выбивая
    лимит API 56.

    progress_callback(done: int, total: int) — вызывается при завершении
    каждого чанка (потокобезопасно через lock).
    """
    import concurrent.futures
    import threading

    chunks_periods = list(_chunked_periods(date_from, date_to, chunk_days=90))
    total = len(chunks_periods)

    # Для маленьких периодов (1 чанк) параллелизация не нужна
    if total <= 1:
        if not chunks_periods:
            return pd.DataFrame()
        chunk_from, chunk_to = chunks_periods[0]
        body = _build_body(report_type, field_names, chunk_from, chunk_to)
        try:
            df = _fetch_report(creds, body)
        except RuntimeError as e:
            if "54" in str(e):
                return pd.DataFrame()
            raise
        if progress_callback:
            progress_callback(1, 1)
        return df if not df.empty else pd.DataFrame()

    results: list[pd.DataFrame | None] = [None] * total
    errors: list[BaseException] = []
    done_count = 0
    lock = threading.Lock()

    def _fetch_one(idx: int, chunk_from: str, chunk_to: str):
        nonlocal done_count
        body = _build_body(report_type, field_names, chunk_from, chunk_to)
        try:
            df = _fetch_report(creds, body)
            results[idx] = df
        except RuntimeError as e:
            if "54" in str(e):
                results[idx] = pd.DataFrame()  # пусто — не ошибка
            else:
                with lock:
                    errors.append(e)
        finally:
            with lock:
                # done_count считает ВСЕ обработанные чанки (успех + ошибки),
                # не только успешные — иначе при сбоях прогресс не дошёл бы
                # до total, и пользователю казалось бы что зависло. Итоговый
                # статус (сколько упало) показывается вызывающим кодом
                # (см. _quality_page.py — там errors_summary разбирается).
                done_count += 1
                if progress_callback:
                    try:
                        progress_callback(done_count, total)
                    except Exception:
                        pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch_one, i, cf, ct)
                   for i, (cf, ct) in enumerate(chunks_periods)]
        concurrent.futures.wait(futures)

    if errors and all(r is None or (isinstance(r, pd.DataFrame) and r.empty) for r in results):
        # Все чанки упали или ничего не вернули — поднимаем первую ошибку
        raise errors[0]

    valid = [r for r in results if r is not None and not r.empty]
    if not valid:
        return pd.DataFrame()
    return pd.concat(valid, ignore_index=True)


# ============================================================
#                     Базовый отчёт по кампаниям (для расходов)
# ============================================================

def fetch_campaign_report(creds: DirectCredentials,
                          date_from: str,
                          date_to: str,
                          _cache_buster: str = "") -> pd.DataFrame:
    """Базовый дневной отчёт: Date, CampaignName, Impressions, Clicks, Cost.

    Используется для расчёта помесячных расходов и совмещения с XLSX-выгрузкой.
    Возвращает DataFrame с колонками: date, campaign, impressions, clicks, spend_rub.
    """
    body = _build_body(
        "CAMPAIGN_PERFORMANCE_REPORT",
        ["Date", "CampaignName", "Impressions", "Clicks", "Cost"],
        date_from, date_to,
    )
    df = _fetch_report(creds, body)
    df = df.rename(columns={
        "Date": "date",
        "CampaignName": "campaign",
        "Impressions": "impressions",
        "Clicks": "clicks",
        "Cost": "spend_rub",
    })
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


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


# ============================================================
#                     Аналитика качества: кампании
# ============================================================

# Полный набор полей для CAMPAIGN_PERFORMANCE_REPORT (вкл. поведенческие и конверсии).
# Conversions/ConversionRate/CostPerConversion работают только если в Я.Метрике
# настроены цели и счётчик привязан к кампании. У UFO Hosting — есть.
CAMPAIGN_QUALITY_FIELDS = [
    "CampaignName", "CampaignType",
    "Impressions", "Clicks", "Ctr",
    "Cost", "AvgCpc",
    "Conversions", "ConversionRate", "CostPerConversion",
    "BounceRate", "AvgPageviews",
    "Sessions",  # для взвешивания BounceRate / AvgPageviews при склейке чанков
]


def fetch_campaign_quality(creds: DirectCredentials,
                           date_from: str,
                           date_to: str,
                           *, progress_callback=None) -> pd.DataFrame:
    """Расширенный отчёт по кампаниям за период: CTR, CPC, Conv, поведенческие.

    За большие периоды (>92 дней) Reports API может вернуть пусто/обрезать —
    тянем чанками по 90 дней (параллельно) и склеиваем агрегатом по кампании.
    """
    df = _fetch_chunked(creds, "CAMPAIGN_PERFORMANCE_REPORT",
                        CAMPAIGN_QUALITY_FIELDS, date_from, date_to,
                        progress_callback=progress_callback)
    if df.empty:
        return df
    df = df.rename(columns={
        "CampaignName": "campaign",
        "CampaignType": "campaign_type",
        "Impressions": "impressions",
        "Clicks": "clicks",
        "Ctr": "ctr",
        "Cost": "spend_rub",
        "AvgCpc": "avg_cpc",
        "Conversions": "conversions",
        "ConversionRate": "conversion_rate",
        "CostPerConversion": "cost_per_conversion",
        "BounceRate": "bounce_rate",
        "AvgPageviews": "avg_pageviews",
        "Sessions": "sessions",
    })
    # API возвращает «--» для пустых значений (когда нет конверсий или поведенческих)
    for col in ("ctr", "avg_cpc", "conversions", "conversion_rate",
                "cost_per_conversion", "bounce_rate", "avg_pageviews"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("impressions", "clicks", "spend_rub", "sessions"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Если было несколько чанков, одна кампания может быть в нескольких строках:
    # агрегируем суммы и пересчитываем средние ВЗВЕШЕННО по визитам/кликам.
    # Простое mean неверно: если кампания в одном периоде имела 1000 визитов
    # с bounce 20%, а в другом 100 с bounce 80% — простое среднее даст 50%,
    # реальное взвешенное = (1000·20 + 100·80)/1100 ≈ 25%.
    group_cols = [c for c in ("campaign", "campaign_type") if c in df.columns]
    if group_cols and len(df) > df[group_cols].drop_duplicates().shape[0]:
        # Для взвешивания нужны pre-aggregated «вес × метрика». Считаем
        # отдельные столбцы _weighted перед groupby.
        weight_col = "sessions" if "sessions" in df.columns and df["sessions"].sum() > 0 else "clicks"
        for behavior_col in ("bounce_rate", "avg_pageviews"):
            if behavior_col in df.columns and weight_col in df.columns:
                df[f"_w_{behavior_col}"] = df[behavior_col] * df[weight_col]

        agg = {c: "sum" for c in ("impressions", "clicks", "spend_rub",
                                  "conversions", "sessions") if c in df.columns}
        # Взвешенные числители суммируем — потом делим на сумму весов
        for behavior_col in ("bounce_rate", "avg_pageviews"):
            wcol = f"_w_{behavior_col}"
            if wcol in df.columns:
                agg[wcol] = "sum"
        df = df.groupby(group_cols, as_index=False).agg(agg)

        # Пересчёт средних
        if "impressions" in df and "clicks" in df:
            df["ctr"] = (df["clicks"] / df["impressions"].replace(0, pd.NA) * 100).fillna(0)
        if "spend_rub" in df and "clicks" in df:
            df["avg_cpc"] = (df["spend_rub"] / df["clicks"].replace(0, pd.NA)).fillna(0)
        if "conversions" in df and "clicks" in df:
            df["conversion_rate"] = (df["conversions"] / df["clicks"].replace(0, pd.NA) * 100).fillna(0)
        if "conversions" in df and "spend_rub" in df:
            df["cost_per_conversion"] = (df["spend_rub"] / df["conversions"].replace(0, pd.NA))
        # Взвешенные поведенческие
        weight_series = df[weight_col] if weight_col in df.columns else None
        for behavior_col in ("bounce_rate", "avg_pageviews"):
            wcol = f"_w_{behavior_col}"
            if wcol in df.columns and weight_series is not None:
                df[behavior_col] = (df[wcol] / weight_series.replace(0, pd.NA)).fillna(0)
                df.drop(columns=[wcol], inplace=True)
    return df


# ============================================================
#                     Аналитика качества: ключевые слова
# ============================================================

KEYWORD_REPORT_FIELDS = [
    "CampaignName", "AdGroupName",
    "Criterion", "MatchType",
    "Impressions", "Clicks", "Ctr",
    "Cost", "AvgCpc",
    "Conversions", "ConversionRate", "CostPerConversion",
]


def fetch_keyword_report(creds: DirectCredentials,
                         date_from: str,
                         date_to: str,
                         *, progress_callback=None) -> pd.DataFrame:
    """Отчёт по ключевым словам за период. Агрегат, без разреза по дням.

    В Reports API правильное имя отчёта для ключевиков —
    CRITERIA_PERFORMANCE_REPORT (KEYWORD_PERFORMANCE_REPORT не существует
    и вызывает ошибку 8000 «ReportType содержит неверное значение»).

    Reports API имеет лимит 92 дня для большинства отчётов — тянем
    чанками по 90 дней (параллельно), агрегируем по
    (campaign, ad_group, criterion, match_type).
    """
    df = _fetch_chunked(creds, "CRITERIA_PERFORMANCE_REPORT",
                        KEYWORD_REPORT_FIELDS, date_from, date_to,
                        progress_callback=progress_callback)
    if df.empty:
        return df
    df = df.rename(columns={
        "CampaignName": "campaign",
        "AdGroupName": "ad_group",
        "Criterion": "criterion",
        "MatchType": "match_type",
        "Impressions": "impressions",
        "Clicks": "clicks",
        "Ctr": "ctr",
        "Cost": "spend_rub",
        "AvgCpc": "avg_cpc",
        "Conversions": "conversions",
        "ConversionRate": "conversion_rate",
        "CostPerConversion": "cost_per_conversion",
    })
    for col in ("ctr", "avg_cpc", "conversions", "conversion_rate", "cost_per_conversion"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("impressions", "clicks", "spend_rub"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Агрегируем результаты чанков: ключевик может встречаться в нескольких
    # чанках (если работал > 90 дней) — суммируем числа, средние пересчитываем.
    group_cols = [c for c in ("campaign", "ad_group", "criterion", "match_type") if c in df.columns]
    if group_cols:
        agg_sum = {c: "sum" for c in ("impressions", "clicks", "spend_rub", "conversions") if c in df.columns}
        df = df.groupby(group_cols, as_index=False).agg(agg_sum)
        # Пересчитываем CTR / CPC / CR / CPL из суммированных
        if "impressions" in df and "clicks" in df:
            df["ctr"] = (df["clicks"] / df["impressions"].replace(0, pd.NA) * 100).fillna(0)
        if "spend_rub" in df and "clicks" in df:
            df["avg_cpc"] = (df["spend_rub"] / df["clicks"].replace(0, pd.NA)).fillna(0)
        if "conversions" in df and "clicks" in df:
            df["conversion_rate"] = (df["conversions"] / df["clicks"].replace(0, pd.NA) * 100).fillna(0)
        if "conversions" in df and "spend_rub" in df:
            df["cost_per_conversion"] = (df["spend_rub"] / df["conversions"].replace(0, pd.NA))
    return df


# ============================================================
#                     Аналитика качества: объявления (креативы)
# ============================================================

AD_REPORT_FIELDS = [
    "CampaignName", "AdGroupName", "AdId",
    "Impressions", "Clicks", "Ctr",
    "Cost", "AvgCpc",
    "Conversions", "ConversionRate",
]


def fetch_ad_report(creds: DirectCredentials,
                    date_from: str,
                    date_to: str,
                    *, progress_callback=None) -> pd.DataFrame:
    """Отчёт по объявлениям за период. Тянем чанками по 90 дней
    (лимит AD_PERFORMANCE_REPORT в Reports API), параллельно, и склеиваем.
    """
    df = _fetch_chunked(creds, "AD_PERFORMANCE_REPORT",
                        AD_REPORT_FIELDS, date_from, date_to,
                        progress_callback=progress_callback)
    if df.empty:
        return df
    df = df.rename(columns={
        "CampaignName": "campaign",
        "AdGroupName": "ad_group",
        "AdId": "ad_id",
        "Impressions": "impressions",
        "Clicks": "clicks",
        "Ctr": "ctr",
        "Cost": "spend_rub",
        "AvgCpc": "avg_cpc",
        "Conversions": "conversions",
        "ConversionRate": "conversion_rate",
    })
    for col in ("ctr", "avg_cpc", "conversions", "conversion_rate"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("impressions", "clicks", "spend_rub"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Агрегация чанков по (campaign, ad_group, ad_id)
    group_cols = [c for c in ("campaign", "ad_group", "ad_id") if c in df.columns]
    if group_cols:
        agg_sum = {c: "sum" for c in ("impressions", "clicks", "spend_rub", "conversions") if c in df.columns}
        df = df.groupby(group_cols, as_index=False).agg(agg_sum)
        if "impressions" in df and "clicks" in df:
            df["ctr"] = (df["clicks"] / df["impressions"].replace(0, pd.NA) * 100).fillna(0)
        if "spend_rub" in df and "clicks" in df:
            df["avg_cpc"] = (df["spend_rub"] / df["clicks"].replace(0, pd.NA)).fillna(0)
        if "conversions" in df and "clicks" in df:
            df["conversion_rate"] = (df["conversions"] / df["clicks"].replace(0, pd.NA) * 100).fillna(0)
    return df
