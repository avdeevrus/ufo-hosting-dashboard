# Офлайн-конверсии в Я.Метрику

Заливает оплаты UFO Hosting обратно в Я.Метрику как офлайн-конверсии.
После этого:
- В **Я.Метрике** → отчёты «Источники → ...» появится реальная выручка
  per канал
- В **Я.Директе** → Мастер отчётов → группировка «Условие показа» +
  метрика «Доход» — реальный доход per ключевая фраза
- **Автостратегии Я.Директа** начнут оптимизироваться на оплаты, а не на
  клики → CAC падает сам собой (обычно в 2-3× за месяц)

## Что нужно для запуска

1. **Метрика на сайте + ClientID в БД UFO Hosting** — см. этап 1 в
   [`../README.md`](../README.md). Без `metrika_client_id` в `users`
   скрипт не сможет связать оплаты с визитами.

2. **OAuth токен Метрики** со scope `metrika:write`:
   - Зайти на https://oauth.yandex.ru → Зарегистрировать новое приложение
   - Платформа: «Web-сервисы», Redirect URI: `https://oauth.yandex.ru/verification_code`
   - Доступы: «Яндекс.Метрика» → «Загрузка данных в Метрику»
   - После создания получить токен через
     `https://oauth.yandex.ru/authorize?response_type=token&client_id=YOUR_CLIENT_ID`
   - Положить токен в env-переменную `METRIKA_TOKEN`

3. **Counter ID** Метрики UFO Hosting — число вроде `12345678`, видно в
   metrika.yandex.ru → Настройки счётчика. Положить в env `METRIKA_COUNTER_ID`.

4. **Цель «Оплата»** в Метрике:
   - Настройки счётчика → Цели → Добавить цель
   - Тип: «JavaScript-событие»
   - Идентификатор цели: `payment` (используется в скрипте)
   - Описание: «Оплата заказа (офлайн-конверсия из БД)»

5. **Доступ к БД UFO Hosting или путь к свежему CSV** — нужно скрипту,
   чтобы взять список оплат. Два режима:
   - **Режим CSV** (проще): передаём путь к выгрузке `--csv path/to/orders.csv`
   - **Режим БД** (для продакшена): нужно настроить подключение в скрипте

## Запуск

### Разовый прогон (для проверки)

```bash
export METRIKA_TOKEN=y0_AgAAAAA...
export METRIKA_COUNTER_ID=12345678

python3 upload.py --csv ~/Downloads/orders_2026-05.csv --days 30 --dry-run
```

Флаги:
- `--csv PATH` — путь к CSV-выгрузке «Содержимое заказов» с `metrika_client_id`
- `--days N` — взять оплаты за последние N дней (по умолчанию 7)
- `--dry-run` — показать что будет залито, но не отправлять в Метрику
- `--target NAME` — имя цели в Метрике (по умолчанию `payment`)

### Cron (ежедневно в 3:00)

```cron
0 3 * * * METRIKA_TOKEN=y0_... METRIKA_COUNTER_ID=12345678 /usr/bin/python3 /opt/ufo/offline-conversions/upload.py --csv /opt/ufo/exports/latest.csv --days 7 >> /var/log/ufo-conversions.log 2>&1
```

## Что в логах

```
[2026-05-17 03:00:00] Read 245 paid orders from CSV (last 7 days)
[2026-05-17 03:00:00] Filtered to 198 with metrika_client_id (47 без ClientID — пропущены)
[2026-05-17 03:00:01] Sending to Metrika counter 12345678, goal=payment...
[2026-05-17 03:00:03] ✓ Uploaded 198 conversions, request_id=abc123def
```

## Troubleshooting

| Ошибка | Причина | Что делать |
|---|---|---|
| `400: invalid token` | OAuth токен истёк / неверный scope | Перевыпустить токен со scope `metrika:write` |
| `403: access denied to counter` | Токен не от владельца счётчика | Использовать токен пользователя с доступом «Редактирование» |
| `0 rows with metrika_client_id` | В CSV нет колонки или она пустая | Этап 1 (захват ClientID в форме) не работает — проверить регистрацию в DevTools |
| `409: goal not found` | Цель `payment` не создана в Метрике | Создать цель типа «JavaScript-событие» с ID `payment` |
