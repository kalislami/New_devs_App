"""Reproduce the original HEAD defects in an isolated process, without changing running code.
Run before committing the fix: python backend/tests/reproduce_original_bugs.py
Redis and calculation are controlled doubles, isolating the cache-key behavior.
"""
import asyncio
import json
import subprocess
import sys
from types import ModuleType, SimpleNamespace


def original(path):
    return subprocess.check_output(['git', 'show', 'HEAD:' + path], text=True)


async def run():
    values = {}
    async def get(key):
        return values.get(key)
    async def setex(key, ttl, value):
        values[key] = value
    client = SimpleNamespace(get=get, setex=setex)
    redis = ModuleType('redis')
    redis_async = ModuleType('redis.asyncio')
    redis_async.Redis = SimpleNamespace(from_url=lambda *args: client)
    redis.asyncio = redis_async
    sys.modules['redis'] = redis
    sys.modules['redis.asyncio'] = redis_async
    for name in ['app', 'app.services', 'app.services.reservations']:
        sys.modules[name] = ModuleType(name)
    async def calculate(property_id, tenant_id):
        return {'property_id': property_id, 'tenant_id': tenant_id,
                'total': '2250.00' if tenant_id == 'tenant-a' else '0.00', 'currency': 'USD', 'count': 4 if tenant_id == 'tenant-a' else 0}
    sys.modules['app.services.reservations'].calculate_total_revenue = calculate
    namespace = {}
    exec(compile(original('backend/app/services/cache.py'), 'original/cache.py', 'exec'), namespace)
    first = await namespace['get_revenue_summary']('prop-001', 'tenant-a')
    second = await namespace['get_revenue_summary']('prop-001', 'tenant-b')
    assert second['tenant_id'] == 'tenant-a', 'Original bug did not reproduce; HEAD may already include fixes.'
    print(json.dumps({'original_cache_bug': 'reproduced', 'request_a': first,
                      'request_b_incorrectly_received': second}, indent=2))
    namespace = {}
    exec(compile(original('backend/app/services/reservations.py'), 'original/reservations.py', 'exec'), namespace)
    total = await namespace['calculate_monthly_revenue']('prop-001', 3, 2024)
    assert total == 0
    print('Original monthly function returns placeholder zero:', str(total))


if __name__ == '__main__':
    asyncio.run(run())
