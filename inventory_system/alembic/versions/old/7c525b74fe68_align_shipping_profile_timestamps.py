"""Align shipping profile timestamps

Revision ID: 7c525b74fe68
Revises: eb774d2b4f5c
Create Date: 2025-04-30 09:24:50.030567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7c525b74fe68'
down_revision: Union[str, None] = 'eb774d2b4f5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Manually adjusted: Only handle shipping_profiles timestamps ###
    print("Applying corrected server defaults for shipping_profiles timestamps...")
    utc_now = sa.text("now() at time zone 'utc'")

    op.alter_column('shipping_profiles', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               server_default=utc_now,
               existing_nullable=True)
               
    op.alter_column('shipping_profiles', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               server_default=utc_now, # Apply to updated_at as well
               existing_nullable=True)
    print("Finished applying corrected server defaults for shipping_profiles.")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### Manually adjusted: Only handle shipping_profiles timestamps ###
    print("Reverting server defaults for shipping_profiles timestamps...")
    # Revert to simple now() as that was likely the state from func.now()
    # Or set to None if we want to strictly reverse the upgrade's explicit set. Let's use None.
    op.alter_column('shipping_profiles', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               server_default=None, 
               existing_nullable=True)
               
    op.alter_column('shipping_profiles', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               server_default=None, 
               existing_nullable=True)
    print("Finished reverting server defaults for shipping_profiles.")
    # ### end Alembic commands ###