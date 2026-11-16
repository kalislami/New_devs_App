"""Revenue belongs to the check-in period in the property's local time."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import text
from app.core.database_pool import db_pool


def period_bounds(year: int, month: int | None, property_timezone: str):
    """Convert local boundaries independently, including DST changes."""
    zone = ZoneInfo(property_timezone)
    start = datetime(year, month or 1, 1, tzinfo=zone)
    end = (datetime(year + 1, 1, 1, tzinfo=zone) if month is None or month == 12
           else datetime(year, month + 1, 1, tzinfo=zone))
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def money(value: Decimal) -> str:
    # Round once per currency AFTER summing all sub-cent amounts.
    return format(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')


async def get_property(property_id: str, tenant_id: str) -> dict:
    await db_pool.initialize()
    async with db_pool.get_session() as session:
        result = await session.execute(text("""
            SELECT id, name, timezone FROM properties
            WHERE id = :property_id AND tenant_id = :tenant_id
        """), {"property_id": property_id, "tenant_id": tenant_id})
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail='Property not found')
    return dict(row)


async def list_properties(tenant_id: str) -> list[dict]:
    await db_pool.initialize()
    async with db_pool.get_session() as session:
        result = await session.execute(text("""
            SELECT id, name, timezone FROM properties
            WHERE tenant_id = :tenant_id ORDER BY id
        """), {"tenant_id": tenant_id})
        return [dict(row) for row in result.mappings()]


async def calculate_total_revenue(property_id: str, tenant_id: str,
                                  month: int | None = None, year: int | None = None,
                                  property_timezone: str | None = None) -> dict:
    if month is not None and year is None:
        raise ValueError('A month requires a year')
    if property_timezone is None:
        property_timezone = (await get_property(property_id, tenant_id))['timezone']
    await db_pool.initialize()
    params = {"property_id": property_id, "tenant_id": tenant_id}
    period_filter = ''
    if year is not None:
        params['start'], params['end'] = period_bounds(year, month, property_timezone)
        period_filter = 'AND check_in_date >= :start AND check_in_date < :end'
    async with db_pool.get_session() as session:
        result = await session.execute(text(f"""
            SELECT currency, SUM(total_amount) AS total, COUNT(*) AS count
            FROM reservations
            WHERE property_id = :property_id AND tenant_id = :tenant_id
            {period_filter}
            GROUP BY currency ORDER BY currency
        """), params)
        totals = [{"currency": row.currency, "total": money(row.total), "count": row.count}
                  for row in result]
    return {
        "property_id": property_id, "tenant_id": tenant_id,
        "timezone": property_timezone, "month": month, "year": year,
        "total": totals[0]['total'] if len(totals) == 1 else None,
        "currency": totals[0]['currency'] if len(totals) == 1 else None,
        "count": sum(item['count'] for item in totals), "totals": totals,
    }


async def calculate_monthly_revenue(property_id: str, month: int, year: int,
                                    tenant_id: str) -> dict:
    return await calculate_total_revenue(property_id, tenant_id, month, year)
