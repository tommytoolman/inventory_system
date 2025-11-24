"""Add unique constraint on reverb_orders.order_uuid

Revision ID: 1e5b6a0f1e1d
Revises: 8c573c6cff44
Create Date: 2025-11-23 13:45:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1e5b6a0f1e1d"
down_revision: Union[str, None] = "8c573c6cff44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_reverb_orders_order_uuid",
        "reverb_orders",
        ["order_uuid"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_reverb_orders_order_uuid",
        "reverb_orders",
        type_="unique",
    )
