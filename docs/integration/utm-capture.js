/**
 * UTM Capture для UFO Hosting
 *
 * Встроить в <head> каждой страницы ufohosting.ru.
 * Ловит utm_* + yclid + gclid из URL при первом визите → сохраняет в cookie
 * на 90 дней. Используется формой регистрации для атрибуции клиента
 * к конкретной рекламной кампании.
 *
 * Не зависит от jQuery / других библиотек. Можно положить в footer.js
 * проекта или хостить как отдельный файл.
 */
(function () {
  "use strict";

  // Ключи, которые ловим из URL и сохраняем в cookie
  var KEYS = [
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "yclid",       // Я.Директ click ID — даёт точную атрибуцию даже без UTM
    "gclid",       // Google Ads click ID (на будущее, если запустите Ads)
  ];

  // Срок жизни cookie: 90 дней
  var TTL_MS = 90 * 24 * 60 * 60 * 1000;

  // Замените на свой корневой домен. domain=.ufohosting.ru — cookie будет
  // доступна и на поддоменах (my.ufohosting.ru, account.ufohosting.ru).
  var COOKIE_DOMAIN = ".ufohosting.ru";

  try {
    var params = new URLSearchParams(window.location.search);
    var hasAny = KEYS.some(function (k) { return params.has(k); });
    if (!hasAny) return; // Нет UTM в URL — выходим

    var expires = new Date(Date.now() + TTL_MS).toUTCString();

    KEYS.forEach(function (k) {
      if (!params.has(k)) return;
      var value = params.get(k);
      if (!value) return;

      // Перезаписываем cookie — last-touch attribution (последний клик побеждает).
      // Если нужна first-touch — раскомментировать проверку существующего cookie.
      // if (document.cookie.match(new RegExp('(^|;)\\s*' + k + '=')))  return;

      document.cookie =
        k + "=" + encodeURIComponent(value) +
        "; path=/" +
        "; expires=" + expires +
        "; domain=" + COOKIE_DOMAIN +
        "; SameSite=Lax";
    });

    // Также сохраним «первый визит» отдельным cookie — может понадобиться
    // для multi-touch attribution в будущем.
    if (!document.cookie.match(/(^|;)\s*ufo_first_visit=/)) {
      document.cookie =
        "ufo_first_visit=" + Math.floor(Date.now() / 1000) +
        "; path=/" +
        "; expires=" + new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toUTCString() +
        "; domain=" + COOKIE_DOMAIN +
        "; SameSite=Lax";
    }
  } catch (e) {
    // Молча игнорируем — UTM capture не должен ломать сайт ни при каких ошибках
    if (window.console && console.warn) {
      console.warn("[ufo-utm-capture] error:", e);
    }
  }
})();
