import streamlit as st

from CONFIG import AUTH_SYSTEM_ENABLED
from frontend.st_utils import auth_system

def render_single_page_nav(nav_slot, pages):
    section, section_pages = next(iter(pages.items()))
    with nav_slot.container():
        st.caption(section)
        st.page_link(section_pages[0])
        st.divider()


def main():
    nav_slot = st.sidebar.empty()

    # Get the navigation structure based on auth state
    pages = auth_system()
    can_see_nav = not AUTH_SYSTEM_ENABLED or st.session_state.get("authentication_status", False)

    pg = st.navigation(pages, position="sidebar" if can_see_nav else "hidden")

    if can_see_nav and sum(len(p) for p in pages.values()) == 1:
        render_single_page_nav(nav_slot, pages)

    # Run the selected page
    pg.run()


if __name__ == "__main__":
    main()
