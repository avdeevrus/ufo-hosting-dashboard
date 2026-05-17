# ТЗ для разработчика — сквозная аналитика UFO Hosting

**Цель:** сохранять источник трафика (UTM-метки и ClientID Яндекс.Метрики)
для каждого нового клиента, чтобы потом видеть в дашборде ROMI per кампания
и per ключевая фраза.

**Срок:** 1-2 рабочих дня.

---

## 1. БД — миграция

В таблицу пользователей (`users` или как она называется в вашем проекте)
добавить 7 nullable-колонок:

```sql
ALTER TABLE users
  ADD COLUMN utm_source        VARCHAR(255) DEFAULT NULL,
  ADD COLUMN utm_medium        VARCHAR(255) DEFAULT NULL,
  ADD COLUMN utm_campaign      VARCHAR(500) DEFAULT NULL,
  ADD COLUMN utm_content       VARCHAR(500) DEFAULT NULL,
  ADD COLUMN utm_term          VARCHAR(500) DEFAULT NULL,
  ADD COLUMN yclid             VARCHAR(255) DEFAULT NULL,
  ADD COLUMN metrika_client_id VARCHAR(64)  DEFAULT NULL;

-- Индекс на utm_campaign для быстрой агрегации в дашборде
CREATE INDEX idx_users_utm_campaign ON users (utm_campaign);
```

**Почему такие лимиты:**
- `utm_campaign` / `utm_content` / `utm_term` могут быть длинными (название кампании Я.Директа + параметры) → 500
- `utm_source` / `utm_medium` короткие (yandex/google/cpc/email) → 255
- `metrika_client_id` — UUID-like, ~20-30 символов → 64 с запасом

---

## 2. Фронтенд

### 2.1. JS для захвата UTM из URL → в cookie

Файл уже готов: [`utm-capture.js`](utm-capture.js).
Встроить в `<head>` каждой страницы ufohosting.ru. Без зависимостей.

**Что именно делает:**
- При первом визите читает GET-параметры URL (`?utm_source=...&utm_campaign=...`)
- Сохраняет в cookie на 90 дней с `domain=.ufohosting.ru` (доступно на всех поддоменах)
- Дополнительно сохраняет `ufo_first_visit` (timestamp первого захода) на 365 дней

**Атрибуционная модель:** last-touch (каждый новый клик с UTM перезаписывает
cookie). Это стандарт индустрии. Если нужна first-touch — см. комментарий
в коде.

### 2.2. Форма регистрации

Пример готов: [`registration-form-snippet.html`](registration-form-snippet.html).

Что делать:
1. В форму добавить 8 hidden-полей (`utm_source`, ..., `metrika_client_id`,
   `first_visit_at`)
2. Перед submit'ом — JS заполняет их значениями из cookie
3. Для ClientID Метрики — асинхронный вызов `ym(COUNTER_ID, 'getClientID', cb)`

**Заменить в JS:** `YOUR_METRIKA_COUNTER_ID` → реальный ID счётчика
Яндекс.Метрики (число вроде 12345678).

---

## 3. Бэкенд

### 3.1. Контроллер регистрации

В endpoint `POST /api/register` (или как у вас называется) принять новые
POST-поля и сохранить в БД:

```python
# Псевдокод (Django/Flask/etc — адаптировать под ваш стек)
def register(request):
    user = User(
        email=request.POST['email'],
        password=hash_password(request.POST['password']),
        # ...
        utm_source=request.POST.get('utm_source', '')[:255] or None,
        utm_medium=request.POST.get('utm_medium', '')[:255] or None,
        utm_campaign=request.POST.get('utm_campaign', '')[:500] or None,
        utm_content=request.POST.get('utm_content', '')[:500] or None,
        utm_term=request.POST.get('utm_term', '')[:500] or None,
        yclid=request.POST.get('yclid', '')[:255] or None,
        metrika_client_id=request.POST.get('metrika_client_id', '')[:64] or None,
    )
    user.save()
```

**Важно:**
- Срез длин (`[:255]`, `[:500]`) — защита от слишком длинных значений
- `or None` чтобы пустые строки писались как NULL (чище для SQL агрегатов)
- НЕ валидировать формат UTM — Я.Директ может прислать любую ValueTrack-подстановку

### 3.2. Экспорт «Содержимое заказов»

В скрипт/endpoint, который генерирует CSV «Содержимое заказов» (тот самый,
который владелец дашборда выгружает из админки), добавить 7 колонок справа:

```sql
SELECT
  o.id                 AS "ID покупки",
  o.product            AS "Товар в заказе",
  -- ... все существующие колонки ...
  o.created_at         AS "Дата платежа",
  u.email              AS "Аккаунт",
  u.created_at         AS "Дата регистрации",
  -- ... NEW ↓ ↓ ↓
  u.utm_source         AS "utm_source",
  u.utm_medium         AS "utm_medium",
  u.utm_campaign       AS "utm_campaign",
  u.utm_content        AS "utm_content",
  u.utm_term           AS "utm_term",
  u.yclid              AS "yclid",
  u.metrika_client_id  AS "metrika_client_id"
FROM orders o
JOIN users u ON u.id = o.user_id
WHERE ...;
```

**Названия колонок в CSV:** ровно `utm_source`, `utm_medium`, `utm_campaign`,
`utm_content`, `utm_term`, `yclid`, `metrika_client_id` (lowercase, snake_case).
Дашборд уже умеет их парсить — см. `src/data_loader.py:attribution_columns`.

---

## 4. Я.Директ — настроить ValueTrack в ссылках кампаний

Чтобы в `utm_campaign` приходило не `{campaign_id}` буквально, а реальное
имя кампании — в каждом объявлении Я.Директа в поле «Ссылка» использовать:

```
https://ufohosting.ru/?utm_source=yandex&utm_medium=cpc&utm_campaign={campaign_name_lat}&utm_content={ad_id}&utm_term={keyword}&yclid={yclid}
```

**ValueTrack-параметры Я.Директа** (Яндекс подставляет автоматически):
- `{campaign_name_lat}` — название кампании латиницей (есть в Я.Директе как
  «Имя кампании (латиница)»; если поле пустое — подставится campaign_id)
- `{ad_id}` — ID объявления
- `{keyword}` — текст ключевой фразы, по которой был показ
- `{yclid}` — уникальный ID клика Я.Директа (для офлайн-конверсий)

Можно проставить через **«Шаблон отслеживания»** в настройках кампаний
оптом — не нужно править каждое объявление вручную. См.
https://yandex.ru/support/direct/statistics/url-parameters.html

---

## 5. Проверка после внедрения

1. Открыть в режиме инкогнито: `https://ufohosting.ru/?utm_source=test&utm_campaign=test_campaign&utm_term=test_keyword`
2. В DevTools → Application → Cookies — должны появиться cookie
   `utm_source=test`, `utm_campaign=test_campaign`, `utm_term=test_keyword`,
   `ufo_first_visit=...`
3. Зайти на форму регистрации (не закрывая окно браузера)
4. Зарегистрироваться тестовым email'ом
5. В БД `SELECT utm_*, yclid, metrika_client_id FROM users WHERE email='test...'`
   — должны быть заполнены значения из шага 1 + ClientID Метрики
6. Выгрузить CSV «Содержимое заказов» — там тоже должны быть колонки UTM

---

## 6. Что делать дальше

Когда п.1-5 готовы — **прислать Claude новую CSV-выгрузку**. Я подключу её
к дашборду и активирую блок «Сквозная аналитика → ROMI per кампания / per
ключ» (код уже готов в `src/metrics.py:roi_by_campaign`, `roi_by_keyword`).

Параллельно можно запустить **офлайн-конверсии в Я.Метрику** — отдельный
скрипт-cron, который ежедневно заливает оплаты в Метрику, чтобы Я.Директ
оптимизировал автостратегии на оплаты. См.
[`offline-conversions/README.md`](offline-conversions/README.md).
