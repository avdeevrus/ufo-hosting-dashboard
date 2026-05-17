"""
UFO Hosting — Entrypoint мультистраничного приложения.

Запуск локально:    streamlit run src/app.py
Деплой в облако:    Streamlit Community Cloud (привязать GitHub-репо)

Структура (БЕЗ pages/ директории — иначе Streamlit Cloud конфликтует
с st.navigation и показывает дубли + название «app»):
  • _dashboard_main.py — главная страница (для руководителя)
  • _quality_page.py   — детальная аналитика Я.Директа
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="UFO Hosting · Дашборд",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Sys path для импортов из соседних модулей
sys.path.insert(0, str(Path(__file__).resolve().parent))


# Совместимость со старыми ссылками: до фикса url_path страница «Качество
# рекламы» имела URL /Качество_рекламы (URL-encoded кириллица). При заходе
# по старой ссылке Streamlit показывает модал «Page not found» поверх
# главной страницы. Перехватываем такие переходы JS-редиректом + скрываем
# модал на случай если редирект не успел.
_compat_js_and_css = """
<style>
/* Скрываем системный модал Streamlit «Page not found» — это безопасно,
   потому что Streamlit и так автоматически открывает главную страницу. */
div[role="dialog"]:has(h1) {
    /* Не трогаем обычные модалы — таргетим только тот, где написан текст */
}
</style>
<script>
(() => {
    try {
        const win = window.parent || window;
        const path = decodeURIComponent(win.location.pathname || '');
        // Старые URL содержали кириллицу: «Качество рекламы», «Качество_рекламы» и т.п.
        if (/[А-Яа-яЁё]/.test(path)) {
            // Сохраняем query (?t=...) — нужен для persistent login
            win.location.replace(win.location.origin + '/' + win.location.search);
            return;
        }
    } catch (e) {}
    // Если модал «Page not found» всё-таки появился — кликаем по крестику
    const closeStaleModal = () => {
        const docs = [document];
        try { docs.push((window.parent || window).document); } catch (e) {}
        for (const doc of docs) {
            const dialogs = doc.querySelectorAll('div[role="dialog"]');
            for (const d of dialogs) {
                if ((d.innerText || '').includes('Page not found')) {
                    const close = d.querySelector('button[aria-label="Close"], button[kind="header"]');
                    if (close) close.click();
                    else d.style.display = 'none';
                    return true;
                }
            }
        }
        return false;
    };
    // Запускаем сразу и наблюдаем за DOM на случай асинхронного появления
    closeStaleModal();
    const obs = new MutationObserver(() => closeStaleModal());
    try { obs.observe(document.body, { childList: true, subtree: true }); } catch (e) {}
    try {
        const parentDoc = (window.parent || window).document;
        if (parentDoc) obs.observe(parentDoc.body, { childList: true, subtree: true });
    } catch (e) {}
})();
</script>
"""
import streamlit.components.v1 as components  # noqa: E402
components.html(_compat_js_and_css, height=0)

# Регистрируем страницы через st.navigation. ВАЖНО: pages/ директории
# быть НЕ ДОЛЖНО — иначе Streamlit Cloud параллельно с явной навигацией
# вытаскивает её автоматически и в сайдбаре появляется «app» + дубли.
dashboard_page = st.Page(
    "_dashboard_main.py",
    title="Дашборд окупаемости",
    icon="📊",
    url_path="dashboard",
    default=True,
)
# url_path в латинице — критично! Без него Streamlit формирует URL из title
# («/Качество рекламы»), кириллица URL-encoded ломает внутренние эндпоинты
# Streamlit Cloud / HF Spaces (_stcore/host-config, _stcore/health → 404).
quality_page = st.Page(
    "_quality_page.py",
    title="Качество рекламы",
    icon="🎯",
    url_path="quality",
)

nav = st.navigation([dashboard_page, quality_page])
nav.run()
