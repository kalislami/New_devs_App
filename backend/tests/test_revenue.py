"""Integration regression tests. Run against the seeded assignment PostgreSQL/Redis."""
import json
import logging
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import httpx
import redis.asyncio as redis
from jose import jwt
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.main import app
from app.config import settings
from app.core.auth import authenticate_request, clear_auth_cache
from app.core.database_pool import db_pool
from app.models.auth import AuthenticatedUser
from app.services import cache
from app.services.reservations import money, period_bounds

logging.disable(logging.CRITICAL)


class RevenueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        clear_auth_cache()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')
        cache.redis_client = redis.Redis.from_url(settings.redis_url)
        self.tokens = {}
        for tenant, email, password in [('a', 'sunset@propertyflow.com', 'client_a_2024'),
                                         ('b', 'ocean@propertyflow.com', 'client_b_2024')]:
            response = await self.client.post('/api/v1/auth/login', json={'email': email, 'password': password})
            self.assertEqual(response.status_code, 200, response.text)
            self.tokens[tenant] = response.json()['access_token']
        self.prop = 'test-revenue-' + uuid4().hex
        await db_pool.initialize()
        async with db_pool.get_session() as session:
            for tenant, zone in [('a', 'Europe/Paris'), ('b', 'America/New_York')]:
                await session.execute(text("INSERT INTO properties (id, tenant_id, name, timezone) VALUES (:id, :tenant, 'Regression fixture', :zone)"),
                                      {'id': self.prop, 'tenant': 'tenant-' + tenant, 'zone': zone})
            rows = [
                ('a', '2024-02-29T22:59:59+00:00', '80', 'USD'),
                ('a', '2024-02-29T23:00:00+00:00', '10', 'USD'),
                ('a', '2024-02-29T23:30:00+00:00', '20', 'USD'),
                ('a', '2024-03-15T10:00:00+00:00', '333.333', 'USD'),
                ('a', '2024-03-16T10:00:00+00:00', '333.333', 'USD'),
                ('a', '2024-03-17T10:00:00+00:00', '333.334', 'USD'),
                ('a', '2024-03-31T21:59:59+00:00', '30', 'USD'),
                ('a', '2024-03-31T22:00:00+00:00', '90', 'USD'),
                ('b', '2024-03-01T04:59:59+00:00', '100', 'USD'),
                ('b', '2024-03-01T05:00:00+00:00', '40', 'USD'),
                ('b', '2024-04-01T03:59:59+00:00', '60', 'USD'),
                ('b', '2024-04-01T04:00:00+00:00', '200', 'USD'),
            ]
            for tenant, date, amount, currency in rows:
                await self.insert(session, tenant, date, amount, currency)
            await session.commit()

    async def insert(self, session, tenant, date, amount, currency):
        await session.execute(text("""INSERT INTO reservations
            (id, property_id, tenant_id, check_in_date, check_out_date, total_amount, currency)
            VALUES (:id, :prop, :tenant, :date, :out, :amount, :currency)"""),
            {'id': uuid4().hex, 'prop': self.prop, 'tenant': 'tenant-' + tenant,
             'date': datetime.fromisoformat(date), 'out': datetime.fromisoformat(date) + timedelta(days=2),
             'amount': Decimal(amount), 'currency': currency})

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        async with db_pool.get_session() as session:
            await session.execute(text('DELETE FROM reservations WHERE property_id = :id'), {'id': self.prop})
            await session.execute(text('DELETE FROM properties WHERE id = :id'), {'id': self.prop})
            await session.commit()
        # Delete only keys for this test fixture, never flush shared Redis data.
        async for key in cache.redis_client.scan_iter('revenue:v2:*' + self.prop + '*'):
            await cache.redis_client.delete(key)
        await self.client.aclose()
        await cache.redis_client.aclose()
        await db_pool.close()

    def headers(self, tenant='a'):
        return {'Authorization': 'Bearer ' + self.tokens[tenant]}

    async def summary(self, tenant='a', **params):
        query = {'property_id': self.prop, 'month': 3, 'year': 2024, **params}
        return await self.client.get('/api/v1/dashboard/summary', params=query, headers=self.headers(tenant))

    async def test_seeded_clients_and_cache_isolation(self):
        for tenant, expected, count in [('a', '2250.00', 4), ('b', None, 0), ('a', '2250.00', 4)]:
            response = await self.summary(tenant, property_id='prop-001')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['total_revenue'], expected)
            self.assertEqual(response.json()['reservations_count'], count)
            self.assertEqual(response.headers['cache-control'], 'no-store')

    async def test_paris_month_boundaries_and_dst(self):
        march = await self.summary()
        self.assertEqual(march.json()['total_revenue'], '1060.00')
        self.assertEqual(march.json()['reservations_count'], 6)
        self.assertEqual((await self.summary(month=2)).json()['total_revenue'], '80.00')
        self.assertEqual((await self.summary(month=4)).json()['total_revenue'], '90.00')

    async def test_new_york_boundaries_and_tenant_cache(self):
        self.assertEqual((await self.summary()).json()['total_revenue'], '1060.00')
        for _ in range(2):
            self.assertEqual((await self.summary('b')).json()['total_revenue'], '100.00')
        self.assertEqual((await self.summary()).json()['total_revenue'], '1060.00')

    async def test_annual_and_all_time(self):
        response = await self.client.get('/api/v1/dashboard/summary', params={'property_id': self.prop, 'year': 2024}, headers=self.headers())
        self.assertEqual(response.json()['total_revenue'], '1230.00')
        response = await self.client.get('/api/v1/dashboard/summary', params={'property_id': self.prop}, headers=self.headers())
        self.assertEqual(response.json()['total_revenue'], '1230.00')

    async def test_currency_separation_and_round_after_sum(self):
        async with db_pool.get_session() as session:
            for amount in ['1.005', '2.000']:
                await self.insert(session, 'a', '2024-03-20T10:00:00+00:00', amount, 'EUR')
            await session.commit()
        data = (await self.summary()).json()
        self.assertIsNone(data['total_revenue'])
        self.assertIsNone(data['currency'])
        self.assertEqual({x['currency']: x['total_revenue'] for x in data['totals']}, {'EUR': '3.01', 'USD': '1060.00'})
        self.assertEqual(money(Decimal('0.005')), '0.01')
        self.assertEqual(money(Decimal('-0.005')), '-0.01')
        self.assertEqual(money(Decimal('333.333') * 2 + Decimal('333.334')), '1000.00')

    async def test_property_access_and_spoofed_tenant(self):
        response = await self.summary('b', property_id='prop-002')
        self.assertEqual(response.status_code, 404)
        response = await self.client.get('/api/v1/dashboard/summary', params={'property_id': self.prop, 'month': 3, 'year': 2024},
            headers={**self.headers('b'), 'X-Simulated-Tenant': 'tenant-a'})
        self.assertEqual(response.json()['total_revenue'], '100.00')
        for tenant, owned in [('a', 'prop-002'), ('b', 'prop-004')]:
            response = await self.client.get('/api/v1/dashboard/properties', headers=self.headers(tenant))
            ids = {item['id'] for item in response.json()}
            self.assertIn(owned, ids)
            self.assertNotIn('prop-004' if tenant == 'a' else 'prop-002', ids)

    async def test_invalid_periods(self):
        for params in [{'month': 0}, {'month': 13}, {'year': 0}, {'year': 9999}]:
            self.assertEqual((await self.summary(**params)).status_code, 422)
        response = await self.client.get('/api/v1/dashboard/summary', params={'property_id': self.prop, 'month': 3}, headers=self.headers())
        self.assertEqual(response.status_code, 422)

    async def test_authentication_fails_closed(self):
        path = '/api/v1/dashboard/summary?property_id=' + self.prop
        self.assertEqual((await self.client.get(path)).status_code, 401)
        for token in ['mock-token-123', 'invalid', jwt.encode({'id': 'u', 'email': 'candidate@propertyflow.com',
             'aud': 'authenticated', 'exp': datetime.now(timezone.utc) - timedelta(seconds=1)}, settings.secret_key, algorithm='HS256')]:
            response = await self.client.get(path, headers={'Authorization': 'Bearer ' + token})
            self.assertEqual(response.status_code, 401)
        payload = {'id': 'unassigned', 'email': 'unassigned@example.com', 'aud': 'authenticated',
                   'user_metadata': {'tenant_id': 'tenant-a'}, 'exp': datetime.now(timezone.utc) + timedelta(hours=1)}
        token = jwt.encode(payload, settings.secret_key, algorithm='HS256')
        response = await self.client.get(path, headers={'Authorization': 'Bearer ' + token})
        self.assertEqual(response.status_code, 403)
        for email in ['sunset@propertyflow.com', 'ocean@propertyflow.com', 'candidate@propertyflow.com']:
            response = await self.client.post('/api/v1/auth/login', json={'email': email, 'password': 'wrong'})
            self.assertEqual(response.status_code, 401)

    async def test_redis_failure_uses_real_database(self):
        from redis.exceptions import ConnectionError
        with patch.object(cache.redis_client, 'get', new=AsyncMock(side_effect=ConnectionError)), patch.object(cache.redis_client, 'setex', new=AsyncMock(side_effect=ConnectionError)):
            self.assertEqual((await self.summary()).json()['total_revenue'], '1060.00')

    async def test_mismatched_cache_recomputed(self):
        with patch.object(cache.redis_client, 'get', new=AsyncMock(return_value=json.dumps({'tenant_id': 'tenant-b', 'total': '999999.00'}))):
            self.assertEqual((await self.summary()).json()['total_revenue'], '1060.00')

    async def test_database_failure_returns_503_not_mock_money(self):
        with patch('app.services.cache.get_property', new=AsyncMock(side_effect=OperationalError('query', {}, Exception('offline')))):
            response = await self.summary()
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('total_revenue', response.json())

    def test_year_rollover_and_dst_bounds(self):
        start, end = period_bounds(2024, 3, 'Europe/Paris')
        self.assertEqual(start.isoformat(), '2024-02-29T23:00:00+00:00')
        self.assertEqual(end.isoformat(), '2024-03-31T22:00:00+00:00')
        start, end = period_bounds(2024, 12, 'America/New_York')
        self.assertEqual(end.year, 2025)
        start, end = period_bounds(2024, None, 'Europe/Paris')
        self.assertEqual(start.isoformat(), '2023-12-31T23:00:00+00:00')
        self.assertEqual(end.isoformat(), '2024-12-31T23:00:00+00:00')


if __name__ == '__main__':
    unittest.main()
