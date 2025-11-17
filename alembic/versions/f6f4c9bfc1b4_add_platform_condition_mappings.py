"""Add platform condition mappings table

Revision ID: f6f4c9bfc1b4
Revises: 50a15e4ef9f2
Create Date: 2025-11-15 16:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6f4c9bfc1b4'
down_revision: Union[str, None] = '50a15e4ef9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


product_condition_enum = postgresql.ENUM(
    'NEW', 'EXCELLENT', 'VERYGOOD', 'GOOD', 'FAIR', 'POOR',
    name='productcondition',
    create_type=False
)


def upgrade() -> None:
    op.create_table(
        'platform_condition_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform_name', sa.String(length=32), nullable=False),
        sa.Column('condition', product_condition_enum, nullable=False),
        sa.Column('platform_condition_id', sa.String(length=128), nullable=False),
        sa.Column('display_name', sa.String(length=128), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category_scope', sa.String(length=64), nullable=False, server_default='default'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('platform_name', 'condition', 'category_scope', name='uq_platform_condition_scope')
    )
    op.create_index(
        op.f('ix_platform_condition_mappings_condition'),
        'platform_condition_mappings',
        ['condition'],
        unique=False
    )
    op.create_index(
        op.f('ix_platform_condition_mappings_platform_name'),
        'platform_condition_mappings',
        ['platform_name'],
        unique=False
    )

    platform_condition_table = sa.table(
        'platform_condition_mappings',
        sa.column('platform_name', sa.String),
        sa.column('condition', product_condition_enum),
        sa.column('platform_condition_id', sa.String),
        sa.column('display_name', sa.String),
        sa.column('description', sa.Text),
        sa.column('category_scope', sa.String),
    )

    reverb_rows = [
        ("REVERB", "NEW", "7c3f45de-2ae0-4c81-8400-fdb6b1d74890", "Brand New",
         "Brand New items are sold by an authorized dealer or original builder and include all original packaging."),
        ("REVERB", "EXCELLENT", "df268ad1-c462-4ba6-b6db-e007e23922ea", "Excellent",
         "Excellent items are almost entirely free from blemishes and other visual defects and have been played or used with the utmost care."),
        ("REVERB", "VERYGOOD", "ae4d9114-1bd7-4ec5-a4ba-6653af5ac84d", "Very Good",
         "Very Good items may show a few slight marks or scratches but are fully functional and in overall great shape."),
        ("REVERB", "GOOD", "f7a3f48c-972a-44c6-b01a-0cd27488d3f6", "Good",
         "Good condition items function properly but may exhibit some wear and tear."),
        ("REVERB", "FAIR", "98777886-76d0-44c8-865e-bb40e669e934", "Fair",
         "Fair condition gear should function but will show noticeable cosmetic damage or other issues."),
        ("REVERB", "POOR", "6a9dfcad-600b-46c8-9e08-ce6e5057921e", "Poor",
         "Poor condition gear may not work properly but can still perform most functions."),
    ]

    ebay_musical_rows = [
        ("EBAY", "NEW", "1000", "New", "Condition code for new items", "musical_instruments"),
        ("EBAY", "EXCELLENT", "3000", "Used - Excellent", "Best match for excellent vintage items", "musical_instruments"),
        ("EBAY", "VERYGOOD", "3000", "Used - Very Good", "Used condition for very good items", "musical_instruments"),
        ("EBAY", "GOOD", "3000", "Used - Good", "Used condition for good items", "musical_instruments"),
        ("EBAY", "FAIR", "3000", "Used - Fair", "Used condition for fair items", "musical_instruments"),
        ("EBAY", "POOR", "7000", "For parts or not working", "Items sold for parts or not working", "musical_instruments"),
    ]

    ebay_default_rows = [
        ("EBAY", "NEW", "1000", "New", "Default condition code for new items", "default"),
        ("EBAY", "EXCELLENT", "2000", "Manufacturer Refurbished", "Default excellent condition code", "default"),
        ("EBAY", "VERYGOOD", "3000", "Used", "Default used condition code", "default"),
        ("EBAY", "GOOD", "4000", "Good", "Default good condition code", "default"),
        ("EBAY", "FAIR", "5000", "Acceptable", "Default acceptable condition code", "default"),
        ("EBAY", "POOR", "7000", "For parts or not working", "Default code for items sold as parts", "default"),
    ]

    op.bulk_insert(
        platform_condition_table,
        [
            {
                "platform_name": platform,
                "condition": condition,
                "platform_condition_id": platform_condition_id,
                "display_name": display_name,
                "description": description,
                "category_scope": "default",
            }
            for platform, condition, platform_condition_id, display_name, description in reverb_rows
        ]
    )

    op.bulk_insert(
        platform_condition_table,
        [
            {
                "platform_name": platform,
                "condition": condition,
                "platform_condition_id": platform_condition_id,
                "display_name": display_name,
                "description": description,
                "category_scope": scope,
            }
            for platform, condition, platform_condition_id, display_name, description, scope in (
                ebay_musical_rows + ebay_default_rows
            )
        ]
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_platform_condition_mappings_platform_name'), table_name='platform_condition_mappings')
    op.drop_index(op.f('ix_platform_condition_mappings_condition'), table_name='platform_condition_mappings')
    op.drop_table('platform_condition_mappings')
