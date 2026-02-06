"""HTTP execution engine for fling.

Wraps httpx.AsyncClient to send resolved HTTP requests and return
ExecutionResult objects. Handles redirects, timeouts, cookie jar
persistence, and progress event emission.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpx

from fling.core.models import ExecutionResult

if TYPE_CHECKING:
    from fling.core.models import HttpRequestDefinition

logger = logging.getLogger(__name__)

# Default timeout in seconds
DEFAULT_TIMEOUT = 30.0


class ProgressEvent(StrEnum):
    """Progress events emitted during request execution."""

    PREPARING = "preparing"
    SENDING = "sending"
    RECEIVING = "receiving"
    COMPLETE = "complete"
    ERROR = "error"


# Type for progress callbacks
ProgressCallback = Callable[[ProgressEvent, dict[str, Any]], Coroutine[Any, Any, None]]


class HttpExecutor:
    """Executes HTTP requests using httpx.AsyncClient.

    Supports configurable redirect behavior, timeouts, SSL verification,
    and cookie jar persistence. Emits progress events via an optional
    async callback.
    """

    def __init__(
        self,
        *,
        verify_ssl: bool = True,
        default_timeout: float = DEFAULT_TIMEOUT,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Initialize the executor.

        Args:
            verify_ssl: Whether to verify SSL certificates.
            default_timeout: Default request timeout in seconds.
            progress_callback: Optional async callback for progress events.
        """
        self._verify_ssl = verify_ssl
        self._default_timeout = default_timeout
        self._progress_callback = progress_callback
        self._cookie_jar = httpx.Cookies()

    async def _emit(self, event: ProgressEvent, data: dict[str, Any] | None = None) -> None:
        """Emit a progress event if a callback is registered."""
        if self._progress_callback:
            await self._progress_callback(event, data or {})

    async def execute(
        self,
        request: HttpRequestDefinition,
        resolved_url: str,
        resolved_headers: dict[str, str],
        resolved_body: str | None = None,
    ) -> ExecutionResult:
        """Execute an HTTP request and return the result.

        Args:
            request: The original request definition (for metadata).
            resolved_url: URL with variables resolved.
            resolved_headers: Headers with variables resolved.
            resolved_body: Body with variables resolved.

        Returns:
            ExecutionResult with response data or error.
        """
        # Determine request-specific settings from metadata
        meta = request.metadata
        follow_redirects = not meta.no_redirect
        timeout = self._resolve_timeout(meta.timeout_ms)

        await self._emit(
            ProgressEvent.PREPARING,
            {
                "method": request.method.value,
                "url": resolved_url,
            },
        )

        try:
            # Build client config
            client_kwargs: dict[str, Any] = {
                "verify": self._verify_ssl,
                "timeout": timeout,
                "follow_redirects": follow_redirects,
            }

            # Attach cookies unless @no-cookie-jar
            if not meta.no_cookie_jar:
                client_kwargs["cookies"] = self._cookie_jar

            async with httpx.AsyncClient(**client_kwargs) as client:
                await self._emit(
                    ProgressEvent.SENDING,
                    {
                        "method": request.method.value,
                        "url": resolved_url,
                    },
                )

                start_time = time.monotonic()

                response = await client.request(
                    method=request.method.value,
                    url=resolved_url,
                    headers=resolved_headers,
                    content=resolved_body.encode("utf-8") if resolved_body else None,
                )

                elapsed_ms = (time.monotonic() - start_time) * 1000

                await self._emit(
                    ProgressEvent.RECEIVING,
                    {
                        "status_code": response.status_code,
                        "elapsed_ms": elapsed_ms,
                    },
                )

                # Update cookie jar from response (unless @no-cookie-jar)
                if not meta.no_cookie_jar:
                    self._cookie_jar.update(response.cookies)

                # Build response headers dict
                response_headers = self._extract_response_headers(response)

                # Read response body
                response_body = response.text

                result = ExecutionResult(
                    request=request,
                    resolved_url=resolved_url,
                    resolved_headers=resolved_headers,
                    resolved_body=resolved_body,
                    status_code=response.status_code,
                    response_headers=response_headers,
                    response_body=response_body,
                    elapsed_ms=elapsed_ms,
                )

                await self._emit(
                    ProgressEvent.COMPLETE,
                    {
                        "status_code": response.status_code,
                        "elapsed_ms": elapsed_ms,
                        "body_length": len(response_body),
                    },
                )

                return result

        except httpx.TimeoutException as exc:
            return await self._error_result(
                request,
                resolved_url,
                resolved_headers,
                resolved_body,
                f"Request timed out: {exc}",
            )
        except httpx.ConnectError as exc:
            return await self._error_result(
                request,
                resolved_url,
                resolved_headers,
                resolved_body,
                f"Connection error: {exc}",
            )
        except httpx.HTTPError as exc:
            return await self._error_result(
                request,
                resolved_url,
                resolved_headers,
                resolved_body,
                f"HTTP error: {exc}",
            )
        except Exception as exc:
            return await self._error_result(
                request,
                resolved_url,
                resolved_headers,
                resolved_body,
                f"Unexpected error: {exc}",
            )

    def _resolve_timeout(self, timeout_ms: int | None) -> float:
        """Resolve the timeout for a request.

        Args:
            timeout_ms: Per-request timeout in milliseconds, or None.

        Returns:
            Timeout in seconds.
        """
        if timeout_ms is not None:
            return timeout_ms / 1000.0
        return self._default_timeout

    @staticmethod
    def _extract_response_headers(response: httpx.Response) -> dict[str, list[str]]:
        """Extract response headers as a dict of lists.

        Args:
            response: The httpx response.

        Returns:
            Dictionary mapping header names to lists of values.
        """
        headers: dict[str, list[str]] = {}
        for name, value in response.headers.multi_items():
            headers.setdefault(name, []).append(value)
        return headers

    async def _error_result(
        self,
        request: HttpRequestDefinition,
        resolved_url: str,
        resolved_headers: dict[str, str],
        resolved_body: str | None,
        error_msg: str,
    ) -> ExecutionResult:
        """Create an error ExecutionResult.

        Args:
            request: The original request definition.
            resolved_url: The resolved URL.
            resolved_headers: The resolved headers.
            resolved_body: The resolved body.
            error_msg: Human-readable error message.

        Returns:
            ExecutionResult with error set.
        """
        await self._emit(ProgressEvent.ERROR, {"error": error_msg})
        return ExecutionResult(
            request=request,
            resolved_url=resolved_url,
            resolved_headers=resolved_headers,
            resolved_body=resolved_body,
            error=error_msg,
        )

    def clear_cookies(self) -> None:
        """Clear the cookie jar."""
        self._cookie_jar.clear()
