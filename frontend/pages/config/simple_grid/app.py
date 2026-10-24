import streamlit as st

from frontend.components.config_loader import get_default_config_loader
from frontend.components.save_config import render_save_config
from frontend.pages.config.simple_grid.user_inputs import user_inputs
from frontend.st_utils import initialize_st_page

initialize_st_page(title="Simple Grid", icon="🔳")

st.text(
    "Simple Grid runs one leg at a time and re-anchors on where the previous leg closed. "
    "Each leg is bracketed by a take profit and stop loss measured from its own fill price."
)

get_default_config_loader("simple_grid")

inputs = user_inputs()
st.session_state["default_config"].update(inputs)

st.info("Backtesting is not enabled for this config.")
st.write("---")

render_save_config(
    st.session_state["default_config"]["id"],
    st.session_state["default_config"],
)
