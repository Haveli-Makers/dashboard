import importlib
import sys
from typing import Dict, TypedDict

import streamlit as st

from frontend.st_utils import initialize_st_page


class ConfigMetadata(TypedDict):
    module: str
    slug: str
    icon: str


CONFIG_PAGES: Dict[str, ConfigMetadata] = {
    "Grid Strike": {"module": "frontend.pages.config.grid_strike.app", "slug": "grid_strike", "icon": "🎳"},
    "PMM Simple": {"module": "frontend.pages.config.pmm_simple.app", "slug": "pmm_simple", "icon": "👨‍🏫"},
    "PMM Dynamic": {"module": "frontend.pages.config.pmm_dynamic.app", "slug": "pmm_dynamic", "icon": "👩‍🏫"},
    "D-Man Maker V2": {"module": "frontend.pages.config.dman_maker_v2.app", "slug": "dman_maker_v2", "icon": "🤖"},
    "Bollinger V1": {"module": "frontend.pages.config.bollinger_v1.app", "slug": "bollinger_v1", "icon": "📈"},
    "MACD_BB V1": {"module": "frontend.pages.config.macd_bb_v1.app", "slug": "macd_bb_v1", "icon": "📊"},
    "SuperTrend V1": {"module": "frontend.pages.config.supertrend_v1.app", "slug": "supertrend_v1", "icon": "👨‍🔬"},
    "XEMM Controller": {"module": "frontend.pages.config.xemm_controller.app", "slug": "xemm_controller", "icon": "⚡️"},
    "Spreadkiller V1": {"module": "frontend.pages.config.spreadkiller_v1.app", "slug": "spreadkiller_v1", "icon": "🦈"},
}

DEFAULT_CONFIG_NAME = "Grid Strike"


def _format_option(option: str) -> str:
    meta = CONFIG_PAGES[option]
    return f"{meta['icon']} {option}"


def _resolve_initial_selection() -> str:
    requested_slug = st.query_params

    if requested_slug:
        for name, meta in CONFIG_PAGES.items():
            if meta["slug"] == requested_slug:
                return name

    stored_selection = st.session_state.get("config_generator_selection")
    if stored_selection in CONFIG_PAGES:
        return stored_selection

    return DEFAULT_CONFIG_NAME


def _apply_query_param(slug: str) -> None:
    current_slug = st.query_params
    if current_slug != slug:
        st.query_params = slug


def _render_config_page(module_path: str, display_name: str) -> None:
    try:
        if module_path in sys.modules:
            importlib.reload(sys.modules[module_path])
        else:
            importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        st.error(f"Unable to load {display_name} config generator module: {exc}")
    except Exception as exc:  # pragma: no cover - surface unexpected issues to the UI
        st.exception(exc)


def main():
    initialize_st_page(title=None, icon="🧩", layout="wide", show_readme=False)

    st.sidebar.header("Config Generator")

    options = list(CONFIG_PAGES.keys())
    initial_selection = _resolve_initial_selection()
    if initial_selection not in CONFIG_PAGES:
        initial_selection = DEFAULT_CONFIG_NAME
    initial_index = options.index(initial_selection)

    selected_name = st.sidebar.selectbox(
        "Select a configuration",
        options=options,
        index=initial_index,
        key="config_generator_selection",
        format_func=_format_option,
    )

    selection_meta = CONFIG_PAGES[selected_name]
    _apply_query_param(selection_meta["slug"])

    st.sidebar.caption(
        f"Shareable link parameter: `?config={selection_meta['slug']}`"
    )

    _render_config_page(selection_meta["module"], selected_name)


if __name__ == "__main__":
    main()
