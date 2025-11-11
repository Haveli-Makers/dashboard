import streamlit as st

from frontend.st_utils import initialize_st_page

initialize_st_page(
    layout="wide",
    show_readme=False
)

# Custom CSS for enhanced styling
st.markdown("""
<style>
    .hero-container {
        text-align: center;
        padding: 3rem 0 2rem;
    }

    .hero-title {
        font-size: 3rem;
        margin-bottom: 0.5rem;
    }

    .hero-subtitle {
        font-size: 1.2rem;
        color: #888;
        margin-bottom: 2rem;
    }

    .construction-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        color: white;
        text-align: center;
        margin: 0 auto;
        max-width: 640px;
        box-shadow: 0 20px 40px rgba(102, 126, 234, 0.25);
    }

    .construction-card h2 {
        font-size: 2rem;
        margin-bottom: 1rem;
    }

    .construction-card p {
        font-size: 1.1rem;
        line-height: 1.6;
    }
</style>
""", unsafe_allow_html=True)

# Hero Section
st.markdown("""
<div class="hero-container">
    <h1 class="hero-title">🤖 HaveliMakers Dashboard</h1>
    <p class="hero-subtitle">Your command center for algorithmic trading excellence</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="construction-card">
    <h2>🚧 Under Construction</h2>
    <p>
        We're busy building the next-generation HaveliMakers experience.
        Check back soon for live trading analytics, bot controls, and
        performance insights tailored to your strategies.
    </p>
    <p style="margin-top: 1.5rem; opacity: 0.8;">
        Have questions or want early access? Contact the team at
        <a href="mailto:support@havelimakers.com" style="color: #fff; font-weight: 600;">support@havelimakers.com</a>.
    </p>
</div>
""", unsafe_allow_html=True)
