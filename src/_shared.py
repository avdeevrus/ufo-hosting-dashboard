"""Общие helpers для всех страниц приложения.

Импортируется из app.py (главная) и из pages/* (доп. страницы Streamlit).
Содержит:
  • Палитру и Plotly-layout
  • Форматтеры чисел/денег/месяцев
  • kpi_card / sparkline
  • Password-gate
  • Файловый кэш аналитики качества Я.Директа
"""

from __future__ import annotations

import hashlib as _hashlib
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st


# ============================================================
#                       Палитра / Plotly
# ============================================================

PALETTE = {
    "bg": "#ffffff",
    "panel": "#f6f8fa",
    "border": "#d0d7de",
    "text": "#0d1117",
    "muted": "#57606a",
    "primary": "#1f6feb",
    "green": "#1a7f37",
    "red": "#cf222e",
    "orange": "#d97706",
    "purple": "#8250df",
}

PLOTLY_LAYOUT = dict(
    template="plotly_white",
    paper_bgcolor="#ffffff",
    plot_bgcolor="#ffffff",
    font=dict(color=PALETTE["text"],
              family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
              size=12),
    margin=dict(t=40, l=10, r=10, b=10),
    xaxis=dict(gridcolor="#eaeef2", zerolinecolor="#d0d7de", linecolor="#d0d7de"),
    yaxis=dict(gridcolor="#eaeef2", zerolinecolor="#d0d7de", linecolor="#d0d7de"),
)


# ============================================================
#                       Форматтеры
# ============================================================

def fmt_rub(v, suffix=" ₽"):
    """Деньги: до миллиона — точные цифры с пробелами, от миллиона — млн."""
    if v is None or pd.isna(v):
        return "—"
    av = abs(v)
    if av >= 1_000_000:
        return f"{v/1_000_000:.2f} млн{suffix}"
    return f"{v:,.0f}{suffix}".replace(",", " ")


def fmt_num(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{int(v):,}".replace(",", " ")


def plural_ru(n, one, few, many):
    """Русская плюрализация: 1 файл / 2 файла / 5 файлов."""
    n = abs(int(n))
    if n % 100 in (11, 12, 13, 14):
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


_RU_MONTHS_SHORT = ["", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
_RU_MONTHS_FULL = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
_RU_MONTHS_LOW = ["", "январь", "февраль", "март", "апрель", "май", "июнь",
                  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def fmt_month_ru(dt, kind="short_year"):
    """Форматирует месяц на русском.
    kind: 'short_year' → 'Авг 2025', 'full_year' → 'Август 2025', 'low_year' → 'август 2025'.
    """
    if pd.isna(dt):
        return "—"
    dt = pd.Timestamp(dt)
    if kind == "full_year":
        return f"{_RU_MONTHS_FULL[dt.month]} {dt.year}"
    if kind == "low_year":
        return f"{_RU_MONTHS_LOW[dt.month]} {dt.year}"
    return f"{_RU_MONTHS_SHORT[dt.month]} {dt.year}"


# ============================================================
#                       KPI-карточка / sparkline
# ============================================================

def make_sparkline_svg(values, color="#1f6feb", width=88, height=28, fill=True):
    """Inline SVG sparkline для KPI плитки."""
    if not values or len(values) < 2:
        return ""
    vals = [float(v) if v is not None and not pd.isna(v) else 0 for v in values]
    if all(v == 0 for v in vals):
        return ""
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) if mx > mn else max(abs(mx), 1)
    points = []
    pad = 3
    for i, v in enumerate(vals):
        x = pad + i / (len(vals) - 1) * (width - 2 * pad)
        y = height - pad - ((v - mn) / rng) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    line = " ".join(points)
    fill_poly = ""
    if fill:
        fill_points = f"{pad},{height - pad} {line} {width - pad},{height - pad}"
        fill_poly = f'<polygon points="{fill_points}" fill="{color}" fill-opacity="0.12"/>'
    last_x = pad + (len(vals) - 1) / (len(vals) - 1) * (width - 2 * pad)
    last_y = height - pad - ((vals[-1] - mn) / rng) * (height - 2 * pad)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="display:block; margin-top:0.35rem;">'
        f'{fill_poly}'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.2" fill="{color}"/>'
        f'</svg>'
    )


def kpi_card(label: str, value: str, delta: str = "", kind: str = "",
             delta_kind: str = "neutral", tooltip: str = "",
             spark_values=None, spark_color: str | None = None):
    """Карточка KPI с фиксированным стилем."""
    klass = f"kpi-card {kind}".strip()
    delta_html = f'<div class="kpi-delta {delta_kind}">{delta}</div>' if delta else ""
    tip_html = ""
    if tooltip:
        tip_safe = tooltip.replace('"', '&quot;').replace("\n", " ")
        tip_html = f'<span class="kpi-tip" data-tip="{tip_safe}">ⓘ</span>'
    spark_html = ""
    if spark_values and len(spark_values) >= 2:
        c = spark_color or {
            "green": PALETTE["green"], "red": PALETTE["red"],
            "primary": PALETTE["primary"], "orange": PALETTE["orange"],
        }.get(kind, PALETTE["muted"])
        spark_html = make_sparkline_svg(spark_values, color=c)
    return f"""
    <div class="{klass}">
      <div class="kpi-label">{label}{tip_html}</div>
      <div class="kpi-value">{value}</div>
      {delta_html}
      {spark_html}
    </div>
    """


# ============================================================
#                       Password gate
# ============================================================

def password_token(pwd: str) -> str:
    salted = ("ufo-hosting-dashboard-2026:" + pwd).encode("utf-8")
    return _hashlib.sha256(salted).hexdigest()[:24]


def check_password() -> bool:
    """Password-gate с persistence через URL-token. Возвращает True если доступ разрешён."""
    expected = os.environ.get("APP_PASSWORD")
    if not expected:
        return True
    expected_t = password_token(expected)

    if st.session_state.get("auth_ok"):
        return True
    url_token = st.query_params.get("t")
    if url_token == expected_t:
        st.session_state["auth_ok"] = True
        return True

    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] { display: none !important; }
        .main .block-container { max-width: 420px !important; margin: 6rem auto !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div style="text-align:center; margin-bottom:1.5rem;">
            <h2 style="margin:0;">UFO Hosting</h2>
            <div style="color:#57606a; font-size:0.9rem; margin-top:0.4rem;">Дашборд окупаемости рекламы</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    pwd = st.text_input("Пароль доступа", type="password", key="login_pwd")
    remember = st.checkbox("Запомнить меня на этом устройстве", value=True, key="login_remember")
    if pwd:
        if pwd == expected:
            st.session_state["auth_ok"] = True
            if remember:
                st.query_params["t"] = expected_t
            st.rerun()
        else:
            st.error("Неверный пароль", icon="🔒")
    st.caption("Доступ ограничен. Получите пароль у владельца дашборда.")
    return False


# ============================================================
#                       Кэш аналитики качества Я.Директа
# ============================================================

QUALITY_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "api_cache"
QUALITY_CACHE_FILES = {
    "campaign_quality": "yd_campaign_quality.json",
    "keywords": "yd_keywords.json",
    "ads_creatives": "yd_ads_creatives.json",
}


def save_quality_cache(kind: str, df: pd.DataFrame, period: tuple) -> None:
    QUALITY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = QUALITY_CACHE_DIR / QUALITY_CACHE_FILES[kind]
    payload = {
        "period_from": str(period[0]),
        "period_to": str(period[1]),
        "fetched_at": pd.Timestamp.now().isoformat(),
        "rows": df.to_dict(orient="records") if not df.empty else [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")


def load_quality_cache(kind: str) -> tuple[pd.DataFrame, dict]:
    """Возвращает (DataFrame, meta-info). Если файла нет — пустые объекты."""
    path = QUALITY_CACHE_DIR / QUALITY_CACHE_FILES[kind]
    if not path.exists():
        return pd.DataFrame(), {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows", [])
        df = pd.DataFrame(rows)
        meta = {k: payload.get(k) for k in ("period_from", "period_to", "fetched_at")}
        return df, meta
    except Exception:
        return pd.DataFrame(), {}


def reset_all_caches(*, clear_quality_files: bool = True) -> dict:
    """Сбрасывает Streamlit-кэши (data + resource) и опционально удаляет
    диск-кэш аналитики качества. Возвращает счётчик удалённых файлов.

    Используется кнопкой «Сбросить кэш» в сайдбаре.
    """
    st.cache_data.clear()
    st.cache_resource.clear()
    removed = 0
    if clear_quality_files and QUALITY_CACHE_DIR.exists():
        for fname in QUALITY_CACHE_FILES.values():
            p = QUALITY_CACHE_DIR / fname
            if p.exists():
                try:
                    p.unlink()
                    removed += 1
                except Exception:
                    pass
    return {"removed_files": removed}


def render_cache_reset_button(*, key_prefix: str = "global") -> None:
    """Рендерит кнопку «Сбросить кэш» с подтверждением через checkbox.
    Используется на любой странице — параметр key_prefix должен быть уникальным."""
    with st.expander("🔄 Сбросить кэш приложения", expanded=False):
        st.caption(
            "Очистит кэш Streamlit (включая API-кэш Я.Директа на диске). "
            "Все данные подтянутся заново при следующем запросе."
        )
        also_files = st.checkbox(
            "Удалить также кэш-файлы качества рекламы (yd_*.json)",
            value=True,
            key=f"{key_prefix}_reset_files",
        )
        if st.button(
            "Сбросить кэш сейчас",
            use_container_width=True,
            key=f"{key_prefix}_reset_btn",
            type="secondary",
        ):
            info = reset_all_caches(clear_quality_files=also_files)
            msg = "Кэш сброшен."
            if also_files and info["removed_files"]:
                msg += f" Удалено файлов: {info['removed_files']}."
            st.success(msg)
            st.rerun()


# ============================================================
#                       CSS (общий для всех страниц)
# ============================================================

def apply_base_styles() -> None:
    """Применяет базовые CSS-стили: палитра, шрифты, KPI-карточки, popover-период."""
    st.markdown(
        f"""
        <style>
        .stApp {{ background: {PALETTE['bg']}; }}
        .main .block-container,
        section.main > div > div > div.block-container,
        [data-testid="stMainBlockContainer"] {{
            padding-top: 1.1rem !important;
            padding-bottom: 2rem !important;
            padding-left: 1.6rem !important;
            padding-right: 1.6rem !important;
            max-width: none !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
        }}
        [data-testid="stSidebar"][aria-expanded="true"] {{
            min-width: 260px !important; max-width: 280px !important;
        }}
        [data-testid="stSidebar"] .block-container {{
            padding-top: 1.1rem !important; padding-left: 1rem !important;
            padding-right: 1rem !important;
        }}

        h1 {{ font-weight: 700; letter-spacing: -0.4px; color: {PALETTE['text']}; }}

        /* KPI плитки */
        .kpi-card {{
            background: #ffffff;
            border: 1px solid {PALETTE['border']};
            border-radius: 10px;
            padding: 0.85rem 1rem;
            height: 100%;
            transition: border-color 0.15s ease;
        }}
        .kpi-card:hover {{ border-color: #8c959f; }}
        .kpi-card .kpi-label {{
            color: {PALETTE['muted']}; font-size: 0.7rem; text-transform: uppercase;
            letter-spacing: 0.4px; margin-bottom: 0.35rem; font-weight: 600;
        }}
        .kpi-card .kpi-value {{
            color: {PALETTE['text']}; font-size: 1.55rem; font-weight: 700; line-height: 1.1;
        }}
        .kpi-card .kpi-delta {{
            margin-top: 0.35rem; font-size: 0.75rem; color: {PALETTE['muted']};
        }}
        .kpi-card.primary .kpi-value {{ color: {PALETTE['primary']}; }}
        .kpi-card.green   .kpi-value {{ color: {PALETTE['green']}; }}
        .kpi-card.red     .kpi-value {{ color: {PALETTE['red']}; }}
        .kpi-card.orange  .kpi-value {{ color: {PALETTE['orange']}; }}
        .kpi-delta.up   {{ color: {PALETTE['green']}; font-weight: 600; }}
        .kpi-delta.down {{ color: {PALETTE['red']}; font-weight: 600; }}
        .kpi-delta.neutral {{ color: {PALETTE['muted']}; }}

        [data-testid="stHorizontalBlock"] {{ gap: 0.7rem !important; }}

        .section-title {{
            margin: 1.2rem 0 0.55rem 0; font-size: 0.82rem; font-weight: 700;
            color: {PALETTE['muted']}; text-transform: uppercase; letter-spacing: 0.5px;
        }}

        [data-testid="stSidebar"] {{
            background: {PALETTE['panel']}; border-right: 1px solid {PALETTE['border']};
        }}
        [data-testid="stSidebar"] h1 {{ font-size: 1.15rem; }}
        [data-testid="stSidebar"] h3 {{ font-size: 1.05rem; margin: 0; }}

        .kpi-tip {{
            display: inline-block; margin-left: 0.35rem; cursor: help;
            color: {PALETTE['muted']}; font-size: 0.78rem; font-weight: 400;
            position: relative; line-height: 1; vertical-align: middle;
        }}
        .kpi-tip:hover::after {{
            content: attr(data-tip);
            position: absolute; bottom: calc(100% + 6px); left: 50%;
            transform: translateX(-50%);
            background: {PALETTE['text']}; color: #fff;
            padding: 0.5rem 0.7rem; border-radius: 6px; font-size: 0.72rem;
            line-height: 1.4; font-weight: 400;
            width: max-content; max-width: 260px;
            white-space: normal; text-transform: none; letter-spacing: 0;
            z-index: 1000; pointer-events: none;
            box-shadow: 0 6px 20px rgba(0,0,0,0.18);
        }}
        .kpi-tip:hover::before {{
            content: ""; position: absolute; bottom: calc(100% + 1px); left: 50%;
            transform: translateX(-50%);
            border: 5px solid transparent; border-top-color: {PALETTE['text']};
            z-index: 1000; pointer-events: none;
        }}

        /* ─── Адаптивность для всех страниц ───────────────── */
        @media (max-width: 1024px) {{
            .ufo-hero-text h1 {{ font-size: 1.5rem !important; }}
        }}
        @media (max-width: 900px) {{
            [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; }}
            [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
                flex: 1 1 calc(50% - 0.4rem) !important;
                min-width: calc(50% - 0.4rem) !important;
            }}
            .kpi-card {{ padding: 0.75rem 0.85rem; }}
            .kpi-card .kpi-value {{ font-size: 1.35rem !important; }}
        }}
        @media (max-width: 640px) {{
            .main .block-container,
            [data-testid="stMainBlockContainer"] {{
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }}
            [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
                flex: 1 1 100% !important;
                min-width: 100% !important;
            }}
            /* Streamlit dataframe — горизонтальный скролл вместо обрезания */
            [data-testid="stDataFrame"] {{ overflow-x: auto !important; }}
            /* Tabs scroll по горизонтали на мобильном */
            [data-testid="stTabs"] [role="tablist"] {{
                overflow-x: auto !important; flex-wrap: nowrap !important;
            }}
            [data-testid="stTabs"] [role="tab"] {{ flex-shrink: 0 !important; }}
            /* Заголовки секций — больше воздуха */
            .section-title {{ font-size: 0.74rem; }}
        }}
        @media (max-width: 420px) {{
            .main .block-container,
            [data-testid="stMainBlockContainer"] {{
                padding-left: 0.7rem !important;
                padding-right: 0.7rem !important;
            }}
        }}
        @media (min-width: 1800px) {{
            .main .block-container,
            [data-testid="stMainBlockContainer"] {{
                max-width: 1700px !important;
                margin-left: auto !important;
                margin-right: auto !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
