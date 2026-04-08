"""
Amplitude analytics — fire-and-forget wrapper.

All tracking is non-blocking: errors are logged but never
propagate to the user. If AMPLITUDE_API_KEY is empty, all
calls are silently skipped.
"""
import asyncio
import logging

from amplitude import Amplitude, BaseEvent

from config import AMPLITUDE_API_KEY

logger = logging.getLogger(__name__)

_client: Amplitude | None = None


def _get_client() -> Amplitude | None:
    global _client
    if not AMPLITUDE_API_KEY:
        return None
    if _client is None:
        _client = Amplitude(AMPLITUDE_API_KEY)
        _client.configuration.server_zone = 'EU'
    return _client


def _send(user_id: int, event_type: str, properties: dict) -> None:
    """Synchronous Amplitude call — run inside executor."""
    client = _get_client()
    if client is None:
        return
    client.track(
        BaseEvent(
            event_type=event_type,
            user_id=str(user_id),
            event_properties=properties,
        )
    )


async def track(user_id: int, event_type: str, **properties) -> None:
    """
    Track an event asynchronously. Never raises.

    Usage:
        await analytics.track(user_id, "card_day")
        await analytics.track(user_id, "payment_success", package_id="pack_10", stars=50)
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send, user_id, event_type, properties)
    except Exception:
        logger.warning("Analytics track failed: %s", event_type, exc_info=True)
