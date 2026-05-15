---
title: UFO Hosting · Dashboard
emoji: 🛰️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: Окупаемость Яндекс.Директ и LTV клиентов UFO Hosting
---

# 🛰️ UFO Hosting · Dashboard окупаемости рекламы

Управленческий дашборд: расходы на Яндекс.Директ ↔ реальные оплаты клиентов, LTV, CAC, payback, retention. Одна страница, светлая бизнес-тема, без перегруза.

## Что внутри

Главный экран показывает за выбранный период:

- 8 ключевых KPI крупно (Расход / Доход / ROMI / Клиентов / CAC / ARPU / Средний чек / LTV-to-CAC)
- Помесячная динамика расхода, дохода и новых клиентов
- Структура продаж по семействам продуктов
- Топ клиентов по LTV
- Gauge повторных оплат
- Когортный анализ дохода по месяцам регистрации

В свёрнутых секциях: помесячная таблица, разбивка по кампаниям Директа, локациям серверов, экспорт CSV.

## Деплой на Hugging Face Spaces (бесплатно, не засыпает)

1. Создайте аккаунт на [huggingface.co](https://huggingface.co) (можно войти через GitHub)
2. [huggingface.co/new-space](https://huggingface.co/new-space) → SDK: **Streamlit**, Hardware: **CPU basic (free)**
3. В созданном Space → раздел **Files** → нажать **«+ Add file»** → **«Upload files»** и загрузить всё содержимое этого репозитория

ИЛИ через git (быстрее, без UI):
```bash
git clone https://github.com/avdeevrus/ufo-hosting-dashboard
cd ufo-hosting-dashboard
git remote add hf https://huggingface.co/spaces/<ВАШ_HF_USER>/ufo-hosting-dashboard
git push hf main
```

Через 1-2 минуты дашборд будет жить по `https://huggingface.co/spaces/<user>/ufo-hosting-dashboard`.

## Запуск локально

```bash
./run.sh
```

Откроется на `http://localhost:8520`. При первом запуске поставит зависимости в `.venv/`.

## Загрузка данных

В сайдбаре раздел **📥 Загрузить выгрузки**:

- **CSV** — выгрузки «Содержимое заказов» из админки UFO Hosting (можно несколько за разные периоды, дубликаты по `ID покупки` автоматически убираются)
- **XLSX** — отчёты по рекламным кампаниям Яндекс.Директ помесячно

Дашборд парсит, склеивает, дедуплицирует и показывает обновлённые цифры сразу.

## Подключение Яндекс.Директ API (опционально)

Если хотите чтобы статистика подтягивалась напрямую из аккаунта Директа (а не из XLSX):

1. На [oauth.yandex.ru](https://oauth.yandex.ru) → «Создать приложение», scope `direct:api`
2. Получите OAuth-токен
3. В Space → Settings → **Secrets** → добавьте `YANDEX_DIRECT_TOKEN`
4. Перезапустите приложение

## Структура проекта

```
src/
├── app.py            ← Streamlit UI
├── data_loader.py    ← парсеры CSV + XLSX
├── metrics.py        ← KPI, когорты, payback
└── yandex_direct.py  ← модуль для API Я.Директ
.streamlit/
└── config.toml       ← светлая тема
```
