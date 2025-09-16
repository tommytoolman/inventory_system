"""drop_redundant_product_columns

Revision ID: a31e5bb8a24a
Revises: 0880cf909e4c
Create Date: 2025-02-20 12:14:33.029417

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a31e5bb8a24a'
down_revision: Union[str, None] = '0880cf909e4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.drop_column('products', 'brand_name')
    op.drop_column('products', 'product_model')
    op.drop_column('products', 'category_name')

def downgrade():
    op.add_column('products', sa.Column('brand_name', sa.VARCHAR(), nullable=True))
    op.add_column('products', sa.Column('product_model', sa.VARCHAR(), nullable=True))
    op.add_column('products', sa.Column('category_name', sa.VARCHAR(), nullable=True))