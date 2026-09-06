"""Synchronous wrapper for HummingbotAPIClient."""
import asyncio
import threading
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar

from .client import HummingbotAPIClient

if TYPE_CHECKING:
    from .routers.accounts import AccountsRouter
    from .routers.archived_bots import ArchivedBotsRouter
    from .routers.backtesting import BacktestingRouter
    from .routers.bot_orchestration import BotOrchestrationRouter
    from .routers.connectors import ConnectorsRouter
    from .routers.controllers import ControllersRouter
    from .routers.docker import DockerRouter
    from .routers.gateway import GatewayRouter
    from .routers.gateway_clmm import GatewayCLMMRouter
    from .routers.gateway_swap import GatewaySwapRouter
    from .routers.market_data import MarketDataRouter
    from .routers.portfolio import PortfolioRouter
    from .routers.scripts import ScriptsRouter
    from .routers.trading import TradingRouter

T = TypeVar('T')


def sync_wrapper(async_func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to convert async methods to sync."""
    @wraps(async_func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(async_func(*args, **kwargs))
        finally:
            loop.close()
    return wrapper


class SyncHummingbotAPIClient:
    """Synchronous wrapper for HummingbotAPIClient.

    The async client and its aiohttp session live on a private event loop that
    runs in a dedicated daemon thread. Every sync call submits its coroutine to
    that loop with ``run_coroutine_threadsafe`` and blocks on the result.

    This is deliberately *not* ``loop.run_until_complete`` on a shared loop:
    Streamlit can start a new script run (on another ScriptRunner thread) while a
    previous slow call is still in flight, and two ``run_until_complete`` calls on
    the same loop raise "This event loop is already running". Submitting to a
    background loop instead lets overlapping calls queue safely.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        username: str = "admin",
        password: str = "admin",
        timeout: Optional[float] = None,
        user_email: Optional[str] = None,
    ):
        """Initialize the sync client with connection parameters.

        Args:
            base_url: The base URL of the Hummingbot API
            username: The username for authentication
            password: The password for authentication
            timeout: Optional timeout in seconds (defaults to 300 seconds)
            user_email: Signed-in user's email, sent as X-User-Email for the
                backend's audit log (see api_client/client.py).
        """
        self._base_url = base_url
        self._username = username
        self._password = password
        self._timeout = timeout
        self._user_email = user_email
        self._async_client: Optional[HummingbotAPIClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

        # Type hints for dynamically created attributes
        if TYPE_CHECKING:
            self.accounts: AccountsRouter
            self.archived_bots: ArchivedBotsRouter
            self.backtesting: BacktestingRouter
            self.bot_orchestration: BotOrchestrationRouter
            self.connectors: ConnectorsRouter
            self.controllers: ControllersRouter
            self.docker: DockerRouter
            self.gateway: GatewayRouter
            self.gateway_swap: GatewaySwapRouter
            self.gateway_clmm: GatewayCLMMRouter
            self.market_data: MarketDataRouter
            self.portfolio: PortfolioRouter
            self.scripts: ScriptsRouter
            self.trading: TradingRouter

    # ------------------------------------------------------------------ helpers

    def _run_loop_forever(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro) -> Any:
        """Run a coroutine on the background loop and block for its result."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    # ------------------------------------------------------------ context mgmt

    def __enter__(self) -> 'SyncHummingbotAPIClient':
        """Start the background loop and initialize the async client."""
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop_forever,
            name="hbot-api-client-loop",
            daemon=True,
        )
        self._loop_thread.start()

        import aiohttp
        timeout_obj = aiohttp.ClientTimeout(total=self._timeout) if self._timeout else None
        self._async_client = HummingbotAPIClient(
            self._base_url,
            self._username,
            self._password,
            timeout=timeout_obj,
            user_email=self._user_email,
        )
        # init() creates the aiohttp session; run it on the loop thread so the
        # session is bound to that loop.
        self._submit(self._async_client.init())

        self._wrap_routers()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the async client and stop the background loop."""
        if self._async_client is not None:
            try:
                self._submit(self._async_client.close())
            except Exception:
                pass
            self._async_client = None

        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._loop_thread is not None:
                self._loop_thread.join(timeout=5)
            self._loop.close()
            self._loop = None
            self._loop_thread = None

    def _wrap_routers(self):
        """Dynamically wrap all router methods to be synchronous."""
        router_attrs = [
            'accounts', 'archived_bots', 'backtesting', 'bot_orchestration',
            'connectors', 'controllers', 'docker', 'gateway', 'gateway_swap',
            'gateway_clmm', 'market_data', 'portfolio', 'scripts', 'trading'
        ]

        for router_name in router_attrs:
            if hasattr(self._async_client, router_name):
                async_router = getattr(self._async_client, router_name)
                sync_router = SyncRouterWrapper(async_router, self._submit)
                setattr(self, router_name, sync_router)


class SyncRouterWrapper:
    """Wrapper that converts async router methods to sync via a submit callable."""

    def __init__(self, async_router: Any, submit: Callable[[Any], Any]):
        self._async_router = async_router
        self._submit = submit

    def __getattr__(self, name: str) -> Any:
        """Dynamically wrap async methods to be synchronous."""
        attr = getattr(self._async_router, name)

        if asyncio.iscoroutinefunction(attr):
            def sync_method(*args, **kwargs):
                return self._submit(attr(*args, **kwargs))
            return sync_method

        return attr
