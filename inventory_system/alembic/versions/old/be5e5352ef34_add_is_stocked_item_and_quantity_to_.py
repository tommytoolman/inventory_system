"""Add is_stocked_item and quantity to products

Revision ID: be5e5352ef34
Revises: 09c0a0f2ddbc
Create Date: 2025-08-28 14:17:24.694353

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be5e5352ef34'
down_revision: Union[str, None] = '09c0a0f2ddbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The corrected upgrade function."""
    
    # Add the new 'is_stocked_item' column, telling the database to use FALSE as the default for existing rows.
    op.add_column(
        'products', 
        sa.Column('is_stocked_item', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )
    
    # Add the quantity column (this one is nullable, so it's fine as is).
    op.add_column('products', sa.Column('quantity', sa.Integer(), nullable=True))
    
    # Create the index for the new column.
    op.create_index(op.f('ix_products_is_stocked_item'), 'products', ['is_stocked_item'], unique=False)

    # Note: Because server_default handles populating existing rows, the explicit op.execute() is not strictly needed,
    # but keeping the column definition clean like this is the standard Alembic way.

def downgrade() -> None:
    # It's still fine to leave this empty for now.
    op.drop_index(op.f('ix_products_is_stocked_item'), table_name='products')
    op.drop_column('products', 'quantity')
    op.drop_column('products', 'is_stocked_item')
