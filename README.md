# Hummingbot Dashboard

Hummingbot Dashboard is an open-source application designed to assist in the creation, backtesting, and optimization of a wide variety of algorithmic trading strategies. Once refined, these strategies can be deployed as [Hummingbot](https://github.com/hummingbot/hummingbot) instances in live trading modes, providing a seamless transition from strategy formulation to actual trading execution.

## Features

- **Bot Orchestration**: Deploy and manage multiple instances of Hummingbot
- **Strategy Backtesting and Optimization**: Evaluate the performance of your strategies against historical data and optimize them with Optuna
- **One-Click Deployment**: Seamlessly deploy your strategies as Hummingbot instances for paper or live trading.
- **Performance Analysis Monitoring**: Monitor and analyze the performance of your deployed strategies.
- **Credential Management**: Create and manage separate accounts for API keys
  
## Documentation

For detailed instructions and further information, visit our [documentation page](https://hummingbot.org/dashboard/).

## Installation

Currently, we recommend users to install Dashboard using the **[Deploy repo](https://github.com/hummingbot/deploy)** instead as this will automatically launch Dashboard along with the needed components in their own Docker containers. 

If you are a developer, and want to make changes to the code then we recommend using the Source installation below - please note that you will also need to launch the Backend API and Broker separately (either through source install or through Docker).   

1. **Install Dependencies**:
   - Docker Engine
   - Miniconda or Anaconda

2. **Clone Repository and Navigate to Directory**:
    ```bash
    git clone https://github.com/hummingbot/dashboard.git
    cd dashboard
    ```

3. **Create Conda Environment and Install Dependencies**:
    ```bash
    make install
    ```

4. **Activate the Isolated 'conda' Environment**:
    ```bash
    conda activate dashboard
    ```

5. **Start the Dashboard**:
    ```bash
    make run
    ```

For more detailed instructions on how to install and update the dashboard, refer to [INSTALLATION.md](INSTALLATION.md).


## Authentication

`AUTH_SYSTEM_ENABLED` now defaults to `True` (it previously defaulted to `False`). If you run the dashboard from source without setting this environment variable, and without the Google OAuth secrets described below, the dashboard will require login but have no way to authenticate — locking everyone out.

The `docker-compose.yml` in this repo already pins `AUTH_SYSTEM_ENABLED=False` explicitly, so existing Docker deployments using it are **not** affected until you opt in. If you deploy from source or from a different compose/env file, add `AUTH_SYSTEM_ENABLED=False` to your environment until you've completed the setup below.

Authentication now uses Streamlit's built-in Google SSO (`st.login`/`st.logout`). The previous username/password system (`credentials.yml`) has been removed.

**Setup:**

1. Create `.streamlit/secrets.toml` (git-ignored, never commit this file) with:
   ```toml
   [auth]
   redirect_uri = "http://localhost:8501/oauth2callback"
   cookie_secret = "<a-random-secret-string>"

   [auth.google]
   client_id = "<your-google-oauth-client-id>"
   client_secret = "<your-google-oauth-client-secret>"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
   Create the OAuth client credentials in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials), with `redirect_uri` added as an authorized redirect URI.
2. Set the relevant environment variables:
   - `AUTH_SYSTEM_ENABLED=True` — require login to use the dashboard.
   - `GOOGLE_SSO_ENABLED` — defaults to `True`; set to `False` to hide the Google sign-in button.
   - `GOOGLE_ALLOWED_DOMAIN` — defaults to `havelimakers.com`; restricts sign-in to that Google Workspace domain (leave empty to allow any Google account).

### Docker

- Ensure the dashboard container is not running.
- In `docker-compose.yml`, set `AUTH_SYSTEM_ENABLED=True` under the dashboard service's `environment` block.
- Make sure `.streamlit/secrets.toml` (see above) is present in the mounted dashboard directory.
- Relaunch Dashboard by running `bash setup.sh`.

### Source

- Open the `CONFIG.py` file located in the dashboard root folder.
- Locate the line `AUTH_SYSTEM_ENABLED = os.getenv("AUTH_SYSTEM_ENABLED", "True").lower() in ("true", "1", "t")`.

  ```
  CERTIFIED_EXCHANGES = ["ascendex", "binance", "bybit", "gate.io", "hitbtc", "huobi", "kucoin", "okx", "gateway"]
  CERTIFIED_STRATEGIES = ["xemm", "cross exchange market making", "pmm", "pure market making"]

  AUTH_SYSTEM_ENABLED = os.getenv("AUTH_SYSTEM_ENABLED", "True").lower() in ("true", "1", "t")

  BACKEND_API_HOST = os.getenv("BACKEND_API_HOST", "127.0.0.1")
  ```
- Authentication is now enabled by default, so you shouldn't need to change this line. If you want to disable it instead, set `AUTH_SYSTEM_ENABLED=False` in your environment (or `.env` file) rather than editing the default here.
- Make sure `.streamlit/secrets.toml` (see above) exists in the dashboard root folder.
- Save the CONFIG.py file if you made changes.
- Relaunch dashboard by running `make run`.

### Known Issues
- Refreshing the browser window may log you out and display the login screen again. This is a known issue that might be addressed in future updates.


## Latest Updates

Stay informed about the latest updates and enhancements to Hummingbot Dashboard by subscribing to our [newsletter](https://hummingbot.substack.com/).

## Contributing and Feedback

We welcome contributions from the community. Please read our [contributing guidelines](CONTRIBUTING.md) to get started.

Join our [Discord](https://discord.gg/hummingbot) community to discuss strategies, ask questions, and collaborate with other Hummingbot Dashboard users:

## License

Hummingbot Dashboard is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for more details.
