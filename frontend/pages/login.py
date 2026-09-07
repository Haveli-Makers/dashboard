"""Sign-in screen shown to unauthenticated users (see frontend/st_utils.py:auth_system)."""
import html

import streamlit as st

from CONFIG import GOOGLE_ALLOWED_DOMAIN, GOOGLE_SSO_ENABLED
from frontend.st_utils import start_google_login


def _google_auth_configured() -> bool:
    try:
        _ = st.user  
    except Exception:
        return False
    return True


st.set_page_config(
    page_title="Sign in",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        [data-testid="stSidebar"] { display: none; }

        .login-hero { text-align: center; padding: 1rem 0 1.5rem; }
        .login-hero .login-icon { font-size: clamp(2.5rem, 8vw, 3.5rem); line-height: 1; }
        .login-hero h1 { font-size: clamp(1.5rem, 5vw, 2.2rem); margin: 0.5rem 0 0.25rem; }
        .login-hero p { color: #9a9a9a; font-size: clamp(0.9rem, 2.5vw, 1.05rem); margin: 0; }

        .login-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 16px;
            width: 100%;
            box-sizing: border-box;
            padding: clamp(1.5rem, 6vw, 2.25rem) clamp(1.25rem, 5vw, 2rem);
            box-shadow: 0 20px 40px rgba(102, 126, 234, 0.25);
            text-align: center;
            color: white;
            margin-bottom: 1.5rem;
        }
        .login-card.denied {
            background: linear-gradient(135deg, #b91c1c 0%, #7f1d1d 100%);
            box-shadow: 0 20px 40px rgba(185, 28, 28, 0.25);
        }
        .login-card .denied-email { font-weight: 600; word-break: break-all; }
        .login-card p {
            opacity: 0.9;
            margin-bottom: 1.5rem;
            font-size: clamp(0.9rem, 2.5vw, 1rem);
        }

        .st-key-google_login_button button {
            background: white;
            color: #3c4043;
            border: none;
            border-radius: 8px;
            padding: 0.7rem 1rem;
            font-weight: 600;
            font-size: clamp(0.9rem, 2.5vw, 1rem);
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
        }
        .st-key-google_login_button button:hover {
            background: #f7f7f7;
            color: #3c4043;
            border: none;
        }

        .login-footnote {
            text-align: center;
            margin-top: 1rem;
            color: #888;
            font-size: clamp(0.75rem, 2vw, 0.85rem);
            word-break: break-word;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(horizontal_alignment="center"):
    with st.container(width=480):
        st.markdown(
            """
            <div class="login-hero">
                <div class="login-icon">🤖</div>
                <h1>HaveliMakers Dashboard</h1>
                <p>Your command center for algorithmic trading excellence</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        denied_email = st.session_state.get("google_access_denied_email")

        if denied_email:
            st.markdown(
                f"""
                <div class="login-card denied">
                    <p>
                        Access is restricted to @{html.escape(GOOGLE_ALLOWED_DOMAIN)} accounts.<br>
                        <span class="denied-email">{html.escape(denied_email)}</span> isn't allowed - try a different account.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="login-card"><p>Sign in with your HaveliMakers Google account to continue</p></div>',
                unsafe_allow_html=True,
            )

        if not GOOGLE_SSO_ENABLED:
            st.warning("Google Sign-In is not enabled.")
        elif not _google_auth_configured():
            st.error("Google Sign-In isn't configured yet. Check .streamlit/secrets.toml.")
        else:
            with st.container(key="google_login_button", horizontal_alignment="center"):
                st.button("🔒  Sign in with Google", on_click=start_google_login, width="stretch")

