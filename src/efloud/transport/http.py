from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, TypeVar, cast

import httpx
from hishel import AsyncSqliteStorage, CacheOptions, SpecificationPolicy
from hishel.httpx import AsyncCacheTransport
from smartratelimit import RateLimiter
from smartratelimit.async_client import AsyncRateLimiter
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from types import TracebackType

logger = logging.getLogger(__name__)

F = TypeVar("F")


@dataclass(frozen=True)
class HttpCacheConfig:
    """
    Async HTTP client with retries + rate limiting + RFC9111 caching via hishel.

    Keying: absolute URL only. Callers pass full URLs; we do not rely on base_url for identity.
    """

    name: str

    headers: dict[str, str] | None = None
    timeout: float = 60.0

    enable_cache: bool = True
    ttl_seconds: int | None = 300
    cache_db_path: str | None = None
    force_cache: bool = False  # ignore RFC 9111 headers (useful for APIs without cache headers)

    rate_limit_storage: str = "memory"
    rate_limit_scope: str | None = None
    raise_on_rate_limit: bool = False

    retries: int = 5
    retry_wait_multiplier: float = 1.0
    retry_wait_min: float = 1.0
    retry_wait_max: float = 30.0


def _retry_decorator(cfg: HttpCacheConfig) -> Callable[[F], F]:
    return retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        wait=wait_exponential(
            multiplier=cfg.retry_wait_multiplier,
            min=cfg.retry_wait_min,
            max=cfg.retry_wait_max,
        ),
        stop=stop_after_attempt(cfg.retries),
        reraise=True,
    )


class HttpCache:
    """
    Thin wrapper around httpx.AsyncClient.

    - tenacity retries for HTTP errors
    - smartratelimit gating per scope
    - hishel RFC9111 caching (persistent sqlite storage)
    """

    def __init__(self, cfg: HttpCacheConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self._cfg = cfg

        if client is None:
            # Build transport: either plain httpx, or hishel-wrapped httpx transport
            transport: httpx.AsyncBaseTransport | None = None

            use_hishel = cfg.enable_cache and AsyncCacheTransport is not None and AsyncSqliteStorage is not None

            if use_hishel:
                # Choose DB path. If not provided, keep it deterministic per cache name.
                # Reviewer note: "Consider grouping under <root>/cache/http/" if you have a known cache root."
                db_path = cfg.cache_db_path or f"{cfg.name}.hishel_cache.db"

                storage = AsyncSqliteStorage(
                    database_path=db_path,
                    default_ttl=float(cfg.ttl_seconds) if cfg.ttl_seconds is not None else None,
                )

                next_transport = httpx.AsyncHTTPTransport()
                # Optionally force caching even without cache headers
                policy = None
                if cfg.force_cache and SpecificationPolicy is not None and CacheOptions is not None:
                    # hishel's CacheOptions API varies by version. Older versions exposed an
                    # `always_cache` knob; newer ones do not. If unsupported, ignore force_cache
                    # rather than crashing at runtime.
                    try:
                        cache_options = CacheOptions(always_cache=True)  # ty: ignore[unknown-argument]
                        policy = SpecificationPolicy(cache_options=cache_options)
                    except TypeError:
                        logger.warning(
                            "HttpCache %s: force_cache unsupported by installed hishel; ignoring",
                            cfg.name,
                        )
                        policy = None

                transport = AsyncCacheTransport(
                    next_transport=next_transport,
                    storage=cast("Any", storage),
                    policy=cast("Any", policy),
                )

                client = httpx.AsyncClient(
                    headers=cfg.headers or {},
                    timeout=cfg.timeout,
                    transport=transport,
                )
                logger.info("HttpCache %s using hishel cache %s", cfg.name, db_path)
            else:
                # Fallback: no response caching
                client = httpx.AsyncClient(
                    headers=cfg.headers or {},
                    timeout=cfg.timeout,
                )
                logger.info("HttpCache %s using raw httpx client", cfg.name)

        self._client = client

        self._async_limiter: AsyncRateLimiter | None
        if AsyncRateLimiter is None:
            self._async_limiter = None
            scope = cfg.rate_limit_scope or f"http:{cfg.name}"
            limiter = RateLimiter(
                storage=cfg.rate_limit_storage,
                raise_on_limit=cfg.raise_on_rate_limit,
            )
            limiter.wrap_client(self._client, scope=scope)
        else:
            self._async_limiter = AsyncRateLimiter(
                storage=cfg.rate_limit_storage,
                raise_on_limit=cfg.raise_on_rate_limit,
            )

        self._send = _retry_decorator(cfg)(self._send_request)

    @property
    def name(self) -> str:
        return self._cfg.name

    async def __aenter__(self) -> Self:
        """Return the cache instance for async context-manager use."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the underlying HTTP client when leaving a context."""
        await self.aclose()

    async def _send_request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._async_limiter is not None:
            return await self._async_limiter.arequest_httpx(self._client, method, url, **kwargs)
        return await self._client.request(method, url, **kwargs)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """
        Request by absolute URL.

        If hishel is enabled, responses may be served from or stored in the cache
        according to RFC 9111.
        """
        method_u = method.upper()

        extensions = dict(kwargs.pop("extensions", {}) or {})
        extensions.setdefault("hishel_refresh_ttl_on_access", True)

        return await self._send(
            method_u,
            url,
            extensions=extensions,
            **kwargs,
        )

    async def get(self, url: str, *, refresh: bool = False, **kwargs: Any) -> httpx.Response:
        headers = (kwargs.pop("headers", {}) or {}).copy()
        if refresh:
            # RFC9111-style revalidation: prefer new response rather than cached.
            headers["Cache-Control"] = "no-cache"
        return await self.request("GET", url, headers=headers, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    @staticmethod
    async def invalidate(_urls: Iterable[str]) -> None:
        """
        Keep no-op until you need it.

        Reviewer note: Hishel supports cache invalidation via storage APIs, but
        there is no stable cross-version public invalidate(urls) in the httpx
        integration.
        """
        return

    @staticmethod
    async def clear() -> None:
        """
        Keep no-op until required.

        Reviewer note: can be implemented by deleting the sqlite DB file if you
        control `db_path`.
        """
        return

    async def aclose(self) -> None:
        await self._client.aclose()
