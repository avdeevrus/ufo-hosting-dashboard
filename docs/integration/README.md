# Сквозная аналитика UFO Hosting — план внедрения

Цель: связать каждого клиента с конкретной рекламной кампанией и ключевой фразой,
чтобы дашборд показывал реальный ROMI per кампания / per ключ, а Я.Директ
оптимизировал автостратегии на оплаты, а не на клики.

Используем **2 параллельных контура** (рекомендация Claude от 2026-05-17):

| Контур | Что даёт | Где видны данные |
|---|---|---|
| **Вариант 1 — UTM в выгрузке** | Точная атрибуция «клиент → кампания → ключ» в нашем дашборде | Стримлит UFO Hosting |
| **Вариант 3 — офлайн-конверсии Я.Метрики** | Я.Директ сам показывает доход per кампания и крутит автостратегии на оплаты | direct.yandex.ru → Мастер отчётов |

Оба варианта используют **общий первый шаг**: захват UTM/ClientID на сайте +
сохранение в БД UFO Hosting.

---

## Этап 1 — общий: захват UTM + ClientID на сайте (1.5 часа)

### 1.1. Подключить JS-скрипт захвата UTM

Файл: [`utm-capture.js`](utm-capture.js) — встроить в `<head>` каждой страницы
ufohosting.ru. Скрипт ловит `utm_*`, `yclid`, `gclid` из URL → сохраняет в cookie
на 90 дней.

### 1.2. На странице регистрации — получить Metrika ClientID

Добавить в форму регистрации:

```html
<input type="hidden" name="utm_source"        id="utm_source">
<input type="hidden" name="utm_medium"        id="utm_medium">
<input type="hidden" name="utm_campaign"      id="utm_campaign">
<input type="hidden" name="utm_content"       id="utm_content">
<input type="hidden" name="utm_term"          id="utm_term">
<input type="hidden" name="yclid"             id="yclid">
<input type="hidden" name="metrika_client_id" id="metrika_client_id">
```

И JS перед submit'ом формы:

```js
// Заполняем UTM из cookie
function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? decodeURIComponent(m.pop()) : '';
}
['utm_source','utm_medium','utm_campaign','utm_content','utm_term','yclid'].forEach(k => {
  const el = document.getElementById(k);
  if (el) el.value = getCookie(k);
});

// ClientID Метрики (заменить 12345678 на ваш Counter ID)
if (typeof ym === 'function') {
  ym(12345678, 'getClientID', function(clientID) {
    document.getElementById('metrika_client_id').value = clientID;
  });
}
```

### 1.3. Бэкенд: добавить колонки в таблицу users

```sql
ALTER TABLE users
  ADD COLUMN utm_source        VARCHAR(255) DEFAULT NULL,
  ADD COLUMN utm_medium        VARCHAR(255) DEFAULT NULL,
  ADD COLUMN utm_campaign      VARCHAR(500) DEFAULT NULL,
  ADD COLUMN utm_content       VARCHAR(500) DEFAULT NULL,
  ADD COLUMN utm_term          VARCHAR(500) DEFAULT NULL,
  ADD COLUMN yclid             VARCHAR(255) DEFAULT NULL,
  ADD COLUMN metrika_client_id VARCHAR(64)  DEFAULT NULL;
```

В контроллере регистрации — принять эти POST-поля и сохранить в БД.

---

## Этап 2 — Вариант 1: UTM в выгрузке (1 час)

В скрипте экспорта «Содержимое заказов» (тот самый CSV, который вы загружаете
в дашборд) добавить **7 колонок справа**, через JOIN `orders × users` по
`user_id`:

```
ID покупки, Товар в заказе, ..., Дата регистрации, ..., utm_source, utm_medium, utm_campaign, utm_content, utm_term, yclid, metrika_client_id
```

**Имена колонок** в CSV: ровно `utm_source`, `utm_medium`, `utm_campaign`,
`utm_content`, `utm_term`, `yclid`, `metrika_client_id` (lowercase, snake_case).
Дашборд их уже умеет парсить (см. `src/data_loader.py:attribution_columns`).

После того как первая выгрузка с UTM попадёт в дашборд — в нём автоматически
появится блок **«Сквозная аналитика → ROMI по кампаниям/ключам»** (код уже
заготовлен в `src/metrics.py:roi_by_campaign`, `roi_by_keyword`).

---

## Этап 3 — Вариант 3: офлайн-конверсии в Я.Метрику (2-3 часа)

Скрипт: [`offline-conversions/upload.py`](offline-conversions/upload.py)

Что делает:
1. Подключается к БД UFO Hosting (или читает свежую выгрузку CSV)
2. Берёт все новые оплаты за последние N дней (`is_paid = true`)
3. Формирует CSV формата Метрики:
   ```
   ClientId,Target,DateTime,Price,Currency
   12345678901,payment,1715944800,1500,RUB
   ```
4. Заливает через [Metrika Upload Conversion API](https://yandex.ru/dev/metrika/doc/api2/practice/upload-conversion.html)

**Настройка:**
1. На oauth.yandex.ru создать приложение, scope `metrika:write`
2. В Метрике (Настройки счётчика → Цели) создать цель `payment` типа «Оплата»
3. Запускать скрипт ежедневно через cron:
   ```
   0 3 * * * /usr/bin/python3 /opt/ufo/offline-conversions/upload.py
   ```

После этого в Я.Директе → Мастер отчётов → группировка «Условие показа» +
метрика «Доход» — будет реальная выручка per ключ.

---

## Этап 4 — Дашборд (моя сторона)

Когда вы пришлёте первую CSV-выгрузку с UTM-колонками — я подключусь и:
- Проверю что новые колонки парсятся корректно
- Активирую блок «Сквозная аналитика» в UI (код уже есть, только UI собрать)
- Доточу метрики на реальных данных

Код метрик уже в `src/metrics.py`:
- `has_attribution(orders)` — проверка наличия UTM
- `roi_by_campaign(orders, ads)` — ROMI per кампания
- `roi_by_keyword(orders, kw_quality)` — ROMI per ключевая фраза

---

## Сводный чек-лист

- [ ] **Этап 1.1** — встроить [`utm-capture.js`](utm-capture.js) в `<head>` сайта
- [ ] **Этап 1.2** — hidden-поля + JS в форме регистрации
- [ ] **Этап 1.3** — `ALTER TABLE users` + сохранение UTM в контроллере
- [ ] **Этап 2** — добавить 7 колонок UTM в экспорт CSV «Содержимое заказов»
- [ ] **Этап 3** — настроить cron `offline-conversions/upload.py`
- [ ] **Этап 4** — прислать новую выгрузку Claude → активируем блок в дашборде

**Ожидаемые сроки:** 1-2 рабочих дня разработчика + 0.5 дня моей работы.

**Что получите:** настоящая сквозная аналитика «рубль в Я.Директе → ключевая
фраза → клиент → его оплаты за всё время».
