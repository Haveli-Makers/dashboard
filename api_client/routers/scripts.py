from typing import Any, Dict, List

from .base import BaseRouter


class ScriptsRouter(BaseRouter):
    """Scripts router for script and script configuration management."""

    # Script Operations
    async def list_scripts(self) -> List[str]:
        """List all available scripts."""
        return await self._get("/scripts/")

    async def get_script(self, script_name: str) -> Dict[str, str]:
        """Get script content by name."""
        return await self._get(f"/scripts/{script_name}")

    async def create_or_update_script(self, script_name: str, script_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update a script."""
        return await self._post(f"/scripts/{script_name}", json=script_data)

    async def delete_script(self, script_name: str) -> Dict[str, Any]:
        """Delete a script."""
        return await self._delete(f"/scripts/{script_name}")

    async def get_script_config_template(self, script_name: str) -> Dict[str, Any]:
        """Get script configuration template with default values."""
        return await self._get(f"/scripts/{script_name}/config/template")

    async def run_script_instant(self, run_request: Dict[str, Any]) -> Dict[str, Any]:
        """Run a strategy script immediately."""
        return await self._post("/scripts/runs/instant", json=run_request)

    async def run_script(self, run_request: Dict[str, Any]) -> Dict[str, Any]:
        """Run a script once with an inline configuration."""
        return await self._post("/scripts/run", json=run_request)

    async def create_script_schedule(self, schedule_request: Dict[str, Any]) -> Dict[str, Any]:
        """Create a recurring script schedule."""
        return await self._post("/scripts/schedules/", json=schedule_request)

    async def list_script_schedules(self) -> List[Dict[str, Any]]:
        """List recurring script schedules."""
        return await self._get("/scripts/schedules/")

    async def delete_script_schedule(self, schedule_id: str) -> Dict[str, Any]:
        """Delete a recurring script schedule."""
        return await self._delete(f"/scripts/schedules/{schedule_id}")

    async def set_script_schedule_enabled(self, schedule_id: str, enabled: bool) -> Dict[str, Any]:
        """Pause (enabled=False) or resume (enabled=True) a recurring script schedule."""
        return await self._post(f"/scripts/schedules/{schedule_id}/enabled", json={"enabled": enabled})

    async def run_script_schedule_now(self, schedule_id: str) -> Dict[str, Any]:
        """Trigger a schedule immediately and store its history."""
        return await self._post(f"/scripts/schedules/{schedule_id}/run")

    async def get_script_schedule_history(self, schedule_id: str, limit: int = 50) -> Dict[str, Any]:
        """Get recent output history for a schedule."""
        return await self._get(f"/scripts/schedules/{schedule_id}/history", params={"limit": limit})

    # Script Configuration Operations
    async def list_script_configs(self) -> List[Dict]:
        """List all script configurations with metadata."""
        return await self._get("/scripts/configs/")

    async def get_script_config(self, config_name: str) -> Dict[str, Any]:
        """Get script configuration by config name."""
        return await self._get(f"/scripts/configs/{config_name}")

    async def create_or_update_script_config(self, config_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update script configuration."""
        return await self._post(f"/scripts/configs/{config_name}", json=config)

    async def delete_script_config(self, config_name: str) -> Dict[str, Any]:
        """Delete script configuration."""
        return await self._delete(f"/scripts/configs/{config_name}")
