import json
import logging
import redis.asyncio as redis
from redis.exceptions import RedisError
from app.config import settings
from app.services.reservations import calculate_total_revenue, get_property

logger = logging.getLogger(__name__)
redis_client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1,
                                    socket_timeout=1)


async def get_revenue_summary(property_id: str, tenant_id: str,
                              month: int | None = None, year: int | None = None) -> dict:
    # Authorize on cache hits too; never trust a tenant supplied by the browser.
    property_data = await get_property(property_id, tenant_id)
    # A new namespace avoids unsafe legacy entries. Encode parts unambiguously.
    cache_key = 'revenue:v2:' + json.dumps(
        [tenant_id, property_id, year, month, property_data['timezone']], separators=(',', ':'))
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            if (result.get('tenant_id') == tenant_id and result.get('property_id') == property_id
                    and result.get('month') == month and result.get('year') == year
                    and result.get('timezone') == property_data['timezone']):
                return result
    except (RedisError, ValueError, TypeError, AttributeError):
        logger.warning('Revenue cache unavailable or invalid; querying database')
    result = await calculate_total_revenue(property_id, tenant_id, month, year,
                                           property_data['timezone'])
    try:
        await redis_client.setex(cache_key, 300, json.dumps(result))
    except RedisError:
        logger.warning('Revenue cache write failed')
    return result
