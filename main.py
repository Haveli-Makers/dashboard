import streamlit as st

from CONFIG import AUTH_SYSTEM_ENABLED
from frontend.st_utils import auth_system

def main():
    # Get the navigation structure based on auth state
    pages = auth_system()
    can_see_nav = not AUTH_SYSTEM_ENABLED or st.session_state.get("authentication_status", False)

    pg = st.navigation(pages, position="sidebar" if can_see_nav else "hidden")

    # Run the selected page
    pg.run()


if __name__ == "__main__":
    main()
