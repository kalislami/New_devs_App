"""Resolve tenant identity only from verified, server-managed claims."""
from typing import Optional
from jose import jwt, JWTError
from app.config import settings


class TenantResolver:
    @staticmethod
    def resolve_tenant_from_token(token_payload: dict) -> Optional[str]:
        return (token_payload.get('app_metadata') or {}).get('tenant_id') or token_payload.get('tenant_id')

    @staticmethod
    def resolve_tenant_from_user(user_data: dict) -> Optional[str]:
        return TenantResolver.resolve_tenant_from_token(user_data)

    @staticmethod
    async def resolve_tenant_id(user_id: str, user_email: str,
                               token: Optional[str] = None) -> Optional[str]:
        if not token:
            return None
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=['HS256'],
                                 audience='authenticated')
        except JWTError:
            # Supabase tokens have already been verified by authenticate_request.
            # That caller can use the verified user's app_metadata instead.
            return None
        if (payload.get('id') or payload.get('sub')) != user_id:
            return None
        return TenantResolver.resolve_tenant_from_token(payload)

    @staticmethod
    async def update_user_tenant_metadata(user_id: str, tenant_id: str) -> None:
        pass
