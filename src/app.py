import streamlit as st

st.set_page_config(
    page_title="UFO Hosting · Test",
    page_icon="🛰️",
    layout="wide",
)

st.title("🛰️ Тестовый запуск")
st.success("Streamlit Cloud работает! Сейчас восстановим основной дашборд.")
st.write(f"Python: ", st.__version__)
