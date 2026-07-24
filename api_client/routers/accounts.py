from typing import Any, Dict, List, Optional
import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .base import BaseRouter


class AccountsRouter(BaseRouter):
    """Accounts router for account and credential management operations."""

    # Account Operations
    async def list_accounts(self) -> List[str]:
        """List all account names."""
        return await self._get("/accounts/")

    async def add_account(self, account_name: str) -> Dict[str, Any]:
        """Create new account."""
        return await self._post("/accounts/add-account", params={"account_name": account_name})

    async def delete_account(self, account_name: str) -> Dict[str, Any]:
        """Delete account."""
        return await self._post("/accounts/delete-account", params={"account_name": account_name})

    # Credentials Management
    async def list_account_credentials(self, account_name: str) -> List[str]:
        """List connector names that have credentials configured for an account."""
        return await self._get(f"/accounts/{account_name}/credentials")

    async def get_account_credentials_details(self, account_name: str) -> List[Dict[str, Any]]:
        """Fetch credential details for an account, including masked parameter values."""
        return await self._get(f"/accounts/{account_name}/credentials/details")

    async def _get_server_public_key(self):
        """Fetch and load the server RSA public key."""
        response = await self._get("/accounts/public-key")
        pem = response["public_key"].encode()
        return serialization.load_pem_public_key(pem)

    def _encrypt_value(self, public_key, value: str) -> str:
        """RSA-OAEP/SHA-256 encrypt a string and return base64-encoded ciphertext."""
        ciphertext = public_key.encrypt(
            value.encode(),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(ciphertext).decode()

    async def add_credential(
        self,
        account_name: str,
        connector_name: str,
        credentials: Dict[str, Any],
        alias: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add or update connector credentials for an account, encrypting values with RSA-OAEP."""
        public_key = await self._get_server_public_key()
        encrypted = {
            k: self._encrypt_value(public_key, v) if isinstance(v, str) else v
            for k, v in credentials.items()
        }
        params = {"alias": alias} if alias else None
        return await self._post(
            f"/accounts/add-credential/{account_name}/{connector_name}",
            json={"credentials": encrypted, "encrypted": True},
            params=params,
        )

    async def delete_credential(self, account_name: str, connector_name: str, alias: Optional[str] = None) -> Dict[str, Any]:
        """Delete connector credentials for an account."""
        params = {"alias": alias} if alias else None
        return await self._post(f"/accounts/delete-credential/{account_name}/{connector_name}", params=params)

    # Gateway Wallet Management
    async def add_gateway_wallet(
        self,
        chain: str,
        private_key: str
    ) -> Dict[str, Any]:
        """
        Add a wallet to Gateway. Gateway handles encryption and storage internally.

        Args:
            chain: Blockchain chain (e.g., 'solana', 'ethereum')
            private_key: Private key for the wallet

        Returns:
            Wallet information from Gateway including address
        """
        return await self._post(
            "accounts/gateway/add-wallet",
            json={"chain": chain, "private_key": private_key}
        )

    async def remove_gateway_wallet(
        self,
        chain: str,
        address: str
    ) -> Dict[str, Any]:
        """
        Remove a wallet from Gateway.

        Args:
            chain: Blockchain chain (e.g., 'solana', 'ethereum')
            address: Wallet address to remove

        Returns:
            Success message
        """
        return await self._delete(f"accounts/gateway/{chain}/{address}")

    async def list_gateway_wallets(self) -> List[Dict]:
        """List all wallets."""
        return await self._get("/accounts/gateway/wallets/")
