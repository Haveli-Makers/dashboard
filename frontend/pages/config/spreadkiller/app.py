import streamlit as st

from frontend.components.config_loader import get_default_config_loader
from frontend.components.save_config import render_save_config
from frontend.pages.config.spreadkiller.user_inputs import user_inputs
from frontend.st_utils import initialize_st_page

initialize_st_page(title="Spreadkiller", icon="🦈")

get_default_config_loader("spreadkiller")

inputs = user_inputs()
st.session_state["default_config"].update(inputs)

st.info("Backtesting is not enabled for this config.")
st.write("---")

render_save_config(
    st.session_state["default_config"]["id"],
    st.session_state["default_config"],
)
