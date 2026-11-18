"""Bounded native metadata refresh for background companion decisions."""
import asyncio


async def native_context(bridge, session_id, timeout=1.5):
    try:
        async with asyncio.timeout(timeout):
            value = await bridge.voice_context(session_id)
        if (not isinstance(value, dict) or not isinstance(value.get('persona'), str)
                or type(value.get('busy')) is not bool):
            return None
        return {'persona': value['persona'][:8000], 'busy': value['busy']}
    except Exception:
        return None
