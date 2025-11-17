from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PlatformName, ProductCondition
from app.models.condition_mapping import PlatformConditionMapping

DEFAULT_SCOPE = "default"


class ConditionMappingService:
    """
    Provides read helpers for platform condition mappings stored in the database.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_mapping(
        self,
        platform: PlatformName | str,
        condition: ProductCondition | str,
        *,
        scope: str = DEFAULT_SCOPE,
        fallbacks: Sequence[str] = (DEFAULT_SCOPE,),
    ) -> Optional[PlatformConditionMapping]:
        """
        Fetch a mapping row for a platform/condition pair. When no record exists
        for the requested scope we try the provided fallbacks (defaulting to the
        global "default" scope).
        """

        platform_value = platform.value if isinstance(platform, PlatformName) else str(platform).upper()
        condition_value = condition.value if isinstance(condition, ProductCondition) else str(condition).upper()

        scopes_to_try = [scope]
        for fallback_scope in fallbacks:
            if fallback_scope not in scopes_to_try:
                scopes_to_try.append(fallback_scope)

        for scope_name in scopes_to_try:
            stmt = (
                select(PlatformConditionMapping)
                .where(
                    PlatformConditionMapping.platform_name == platform_value,
                    PlatformConditionMapping.condition == condition_value,
                    PlatformConditionMapping.category_scope == scope_name,
                )
                .limit(1)
            )
            result = await self.db.execute(stmt)
            row = result.scalars().first()
            if row:
                return row
        return None

    async def get_condition_id(
        self,
        platform: PlatformName | str,
        condition: ProductCondition | str,
        *,
        scope: str = DEFAULT_SCOPE,
        fallbacks: Sequence[str] = (DEFAULT_SCOPE,),
    ) -> Optional[str]:
        """
        Convenience helper returning just the platform_condition_id string.
        """

        mapping = await self.get_mapping(
            platform,
            condition,
            scope=scope,
            fallbacks=fallbacks,
        )
        return mapping.platform_condition_id if mapping else None
