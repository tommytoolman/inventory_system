# tests/unit/services/reverb/conftest.py
"""
Local conftest for reverb unit tests.

Provides a db_session that tracks add() calls per class.
Tests verify DB state via db_session._store[ClassName] lists,
NOT via execute() queries (which would recurse with mocker.patch.object).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.platform_common import PlatformCommon
from app.models.product import Product
from app.models.reverb import ReverbListing
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def db_session():
    """
    Smart mock AsyncSession.
    - _store[Product], _store[PlatformCommon], _store[ReverbListing] track added objects
    - execute() returns objects from _store for the queried class
    - count queries return len(_store[class])
    """
    session = MagicMock(spec=AsyncSession)

    _store: dict = {
        Product: [],
        PlatformCommon: [],
        ReverbListing: [],
    }

    def _add(obj):
        cls = type(obj)
        if cls in _store:
            _store[cls].append(obj)

    session.add = MagicMock(side_effect=_add)
    session.delete = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session._store = _store

    async def _execute(statement, params=None):
        stmt_str = ""
        try:
            stmt_str = str(statement).lower() if not isinstance(statement, str) else statement.lower()
        except Exception:
            pass

        is_count = "count" in stmt_str

        # Detect queried model (most specific first)
        queried_cls = None
        if "reverb_listings" in stmt_str:
            queried_cls = ReverbListing
        elif "platform_common" in stmt_str:
            queried_cls = PlatformCommon
        elif "products" in stmt_str:
            queried_cls = Product

        objects = _store.get(queried_cls, []) if queried_cls else []

        mock_result = MagicMock()

        if is_count:
            count_val = len(objects)
            mock_result.scalar.return_value = count_val
            mock_result.scalar_one.return_value = count_val
            mock_result.scalar_one_or_none.return_value = count_val
            mock_result.scalars.return_value = MagicMock(
                all=MagicMock(return_value=objects[:]),
                first=MagicMock(return_value=objects[0] if objects else None),
            )
        else:
            first_obj = objects[0] if objects else None
            mock_result.scalar.return_value = 0
            mock_result.scalar_one_or_none.return_value = first_obj
            mock_result.scalar_one.return_value = first_obj
            mock_result.scalars.return_value = MagicMock(
                all=MagicMock(return_value=objects[:]),
                first=MagicMock(return_value=first_obj),
            )
            mock_result.all.return_value = objects[:]
            mock_result.fetchall.return_value = objects[:]
            mock_result.first.return_value = first_obj

        return mock_result

    session.execute = AsyncMock(side_effect=_execute)

    yield session
