import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import SQLAlchemyError
from app.core.auth import authenticate_request
from app.models.auth import AuthenticatedUser
from app.services.cache import get_revenue_summary
from app.services.reservations import list_properties

router = APIRouter()
logger = logging.getLogger(__name__)


def require_tenant(user: AuthenticatedUser) -> str:
    if not user.tenant_id:
        raise HTTPException(status_code=403, detail='Tenant context required')
    return user.tenant_id


@router.get('/dashboard/properties')
async def get_dashboard_properties(response: Response,
                                   user: AuthenticatedUser = Depends(authenticate_request)):
    response.headers['Cache-Control'] = 'no-store'
    tenant_id = require_tenant(user)
    try:
        return await list_properties(tenant_id)
    except (SQLAlchemyError, OSError):
        logger.exception('Property database unavailable')
        raise HTTPException(status_code=503, detail='Revenue database unavailable')


@router.get('/dashboard/summary')
async def get_dashboard_summary(
    response: Response,
    property_id: str = Query(min_length=1),
    month: int | None = Query(default=None, ge=1, le=12),
    year: int | None = Query(default=None, ge=1, le=9998),
    current_user: AuthenticatedUser = Depends(authenticate_request),
) -> dict:
    response.headers['Cache-Control'] = 'no-store'
    tenant_id = require_tenant(current_user)
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail='A month requires a year')
    try:
        data = await get_revenue_summary(property_id, tenant_id, month, year)
    except (SQLAlchemyError, OSError):
        logger.exception('Revenue database unavailable')
        raise HTTPException(status_code=503, detail='Revenue database unavailable')
    return {
        'property_id': data['property_id'], 'timezone': data['timezone'],
        'month': data['month'], 'year': data['year'],
        'total_revenue': data['total'], 'currency': data['currency'],
        'reservations_count': data['count'],
        'totals': [{'currency': item['currency'], 'total_revenue': item['total'],
                    'reservations_count': item['count']} for item in data['totals']],
    }
