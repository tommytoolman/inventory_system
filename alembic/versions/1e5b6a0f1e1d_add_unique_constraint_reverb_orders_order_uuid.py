"""Add unique constraint on reverb_orders.order_uuid

Revision ID: 1e5b6a0f1e1d
Revises: 8c573c6cff44
Create Date: 2025-11-23 13:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "1e5b6a0f1e1d"
down_revision: Union[str, None] = "8c573c6cff44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_exists(bind, is_sqlite: bool) -> bool:
    """Check if the unique constraint already exists."""
    if is_sqlite:
        result = bind.execute(
            text("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='uq_reverb_orders_order_uuid'")
        )
        return result.scalar() > 0
    else:
        result = bind.execute(
            text(
                """
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON c.conrelid = t.oid
                WHERE c.conname = 'uq_reverb_orders_order_uuid'
                  AND t.relname = 'reverb_orders'
                """
            )
        )
        return result.scalar() is not None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'

    if not _constraint_exists(bind, is_sqlite):
        if is_sqlite:
            # SQLite doesn't support ALTER TABLE ADD CONSTRAINT; use batch mode
            with op.batch_alter_table("reverb_orders") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_reverb_orders_order_uuid",
                    ["order_uuid"],
                )
        else:
            op.create_unique_constraint(
                "uq_reverb_orders_order_uuid",
                "reverb_orders",
                ["order_uuid"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'

    if _constraint_exists(bind, is_sqlite):
        if is_sqlite:
            with op.batch_alter_table("reverb_orders") as batch_op:
                batch_op.drop_constraint(
                    "uq_reverb_orders_order_uuid",
                    type_="unique",
                )
        else:
            op.drop_constraint(
                "uq_reverb_orders_order_uuid",
                "reverb_orders",
                type_="unique",
            )
