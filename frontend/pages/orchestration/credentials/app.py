from typing import Any

import nest_asyncio
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

nest_asyncio.apply()

initialize_st_page(title="Credentials", icon="🔑")

# Page content
client = get_backend_api_client()
NUM_COLUMNS = 4


def get_all_connectors_config_map():
    # Get fresh client instance inside cached function
    connectors = client.connectors.list_connectors()
    config_map_dict = {}
    for connector_name in connectors:   # type: ignore
        try:
            config_map = client.connectors.get_config_map(connector_name=connector_name)
            config_map_dict[connector_name] = config_map
        except Exception as e:
            st.warning(f"Could not get config map for {connector_name}: {e}")
            config_map_dict[connector_name] = []
    return config_map_dict


def render_credential_row(account_name: str, credential_details: dict[str, Any]):
    connector_name = credential_details.get("connector_name", "")
    credential_type = credential_details.get("credential_type", "Master") 
    alias = credential_details.get("alias") 
    parameters = credential_details.get("parameters") or {}
    parameter_items = list(parameters.items())

    columns_spec = [2, *([3] * max(len(parameter_items), 1)), 2, 1]

    row_key = f"{account_name}_{connector_name}_{alias or 'master'}"

    with st.container(border=True):
        cols = st.columns(columns_spec, vertical_alignment="bottom")

        with cols[0]:
            st.text_input(
                "Connector",
                value=connector_name,
                disabled=True,
                key=f"{row_key}_connector",
            )

        if parameter_items:
            for index, (parameter_name, parameter_value) in enumerate(parameter_items, start=1):
                with cols[index]:
                    st.text_input(
                        parameter_name.replace("_", " ").title(),
                        value=str(parameter_value),
                        disabled=True,
                        key=f"{row_key}_{parameter_name}",
                    )
        else:
            with cols[1]:
                st.text_input(
                    "Parameters",
                    value="No parameters",
                    disabled=True,
                    key=f"{row_key}_parameters",
                )

        with cols[-2]:
            type_display = alias if alias else credential_type
            st.text_input(
                "Account Type",
                value=type_display,
                disabled=True,
                key=f"{row_key}_type",
            )

        with cols[-1]:
            st.write("")
            if st.button("🗑️", key=f"delete_credential_{row_key}"):
                client.accounts.delete_credential(account_name, alias or connector_name)
                st.rerun()


all_connector_config_map = get_all_connectors_config_map()

# Get fresh accounts list
accounts = client.accounts.list_accounts()


# Section to add credentials
@st.fragment
def add_credentials_section():
    st.header("Add Credentials")
    c1, c2 = st.columns([1, 1])
    with c1:
        account_name = st.text_input("Account")
        if account_name and account_name not in accounts:
            st.write("Account does not exists, will create a new one")
    with c2:
        all_connectors = list(all_connector_config_map.keys())
        coindcx_index = all_connectors.index("coindcx") if "coindcx" in all_connectors else None
        connector_name = st.selectbox("Select Connector", options=all_connectors, index=coindcx_index)
        config_map = all_connector_config_map.get(connector_name, [])

    credential_type = st.radio(
        "Credential Type",
        ["Master", "Sub-account"],
        horizontal=True,
        key=f"{connector_name}_credential_type",
    )
    alias = None
    if credential_type == "Sub-account":
        alias = st.text_input(
            "Alias",
            placeholder=f"{connector_name}_sub_1",
            help="Custom storage name for this sub-account credential (e.g. 'binance_sub_1234'). Must be unique per connector.",
            key=f"{connector_name}_alias",
        )

    st.write(f"Provide details for {connector_name}:")
    config_inputs = {}

    cols = st.columns(NUM_COLUMNS)
    for i, config in enumerate(config_map):
        with cols[i % (NUM_COLUMNS - 1)]:
            config_inputs[config] = st.text_input(config, type="password", key=f"{connector_name}_{config}")

    with cols[-1]:
        if st.button("Submit Credentials"):
            if credential_type == "Sub-account" and not alias:
                st.error("Please provide an alias for the sub-account credential.")
            else:
                if account_name not in accounts:  # type: ignore
                    client.accounts.add_account(account_name)
                response = client.accounts.add_credential(account_name, connector_name, config_inputs, alias=alias)
                st.write(response)
                st.rerun()


add_credentials_section()

st.markdown("---")


@st.fragment
def accounts_section():
    st.header("Existing Credentials")
    if not accounts:
        st.write("No accounts available.")
        return
    for account in accounts:   # type: ignore
        col_title, col_btn, _ = st.columns([3, 1, 8])
        with col_title:
            st.markdown(f"#### 🏦 {account}")
        with col_btn:
            st.write("")  # vertical alignment nudge
            if st.button("🗑️", key=f"delete_{account}"):
                client.accounts.delete_account(account)
                st.rerun()
        account_credentials = client.accounts.get_account_credentials_details(account)
        if account_credentials:
            for credential_details in account_credentials:
                render_credential_row(account, credential_details)
        else:
            st.write("No credentials configured.")
        st.markdown("---")


accounts_section()
