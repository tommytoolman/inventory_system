"""add_product_metadata_fields

Revision ID: 8c573c6cff44
Revises: 001_initial_schema
Create Date: 2025-11-04 15:19:16.186362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8c573c6cff44'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    handedness_enum = postgresql.ENUM(
        'RIGHT', 'LEFT', 'AMBIDEXTROUS', 'UNSPECIFIED',
        name='handedness'
    )
    manufacturing_enum = postgresql.ENUM(
        'GB', 'US', 'CA', 'JP', 'DE', 'FR', 'IT', 'ES', 'SE', 'NO', 'DK', 'MX',
        'ID', 'CN', 'KR', 'AU', 'NZ', 'BR', 'OTHER',
        name='manufacturingcountry'
    )
    inventory_enum = postgresql.ENUM(
        'warehouse', 'showroom', 'vault', 'consignment', 'offsite', 'in_transit', 'unspecified',
        name='inventorylocation'
    )
    storefront_enum = postgresql.ENUM(
        'primary', 'shopify', 'reverb', 'ebay', 'vr', 'direct', 'wholesale', 'unspecified',
        name='storefront'
    )
    case_status_enum = postgresql.ENUM(
        'none', 'original', 'period_correct', 'aftermarket', 'gig_bag', 'flight_case', 'unspecified',
        name='casestatus'
    )

    for enum_type in (
        handedness_enum,
        manufacturing_enum,
        inventory_enum,
        storefront_enum,
        case_status_enum,
    ):
        enum_type.create(bind, checkfirst=True)

    op.add_column('products', sa.Column('serial_number', sa.String(), nullable=True))
    op.add_column(
        'products',
        sa.Column(
            'handedness',
            handedness_enum,
            server_default=sa.text("'RIGHT'"),
            nullable=False,
        ),
    )
    op.add_column(
        'products',
        sa.Column(
            'artist_owned',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )
    op.add_column(
        'products',
        sa.Column(
            'artist_names',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'products',
        sa.Column(
            'manufacturing_country',
            manufacturing_enum,
            nullable=True,
        ),
    )
    op.add_column(
        'products',
        sa.Column(
            'inventory_location',
            inventory_enum,
            server_default=sa.text("'unspecified'"),
            nullable=False,
        ),
    )
    op.add_column(
        'products',
        sa.Column(
            'storefront',
            storefront_enum,
            server_default=sa.text("'unspecified'"),
            nullable=False,
        ),
    )
    op.add_column(
        'products',
        sa.Column(
            'case_status',
            case_status_enum,
            server_default=sa.text("'unspecified'"),
            nullable=False,
        ),
    )
    op.add_column('products', sa.Column('case_details', sa.Text(), nullable=True))
    op.add_column(
        'products',
        sa.Column(
            'extra_attributes',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    op.execute(
        """
        CREATE OR REPLACE VIEW products_admin_view AS
        SELECT
            id,
            created_at,
            updated_at,
            sku,
            title,
            brand,
            model,
            year,
            decade,
            serial_number,
            handedness,
            artist_owned,
            artist_names,
            manufacturing_country,
            category,
            finish,
            condition,
            base_price,
            cost_price,
            price,
            price_notax,
            collective_discount,
            offer_discount,
            status,
            is_sold,
            is_stocked_item,
            quantity,
            inventory_location,
            storefront,
            in_collective,
            in_inventory,
            in_reseller,
            free_shipping,
            buy_now,
            show_vat,
            local_pickup,
            available_for_shipment,
            processing_time,
            shipping_profile_id,
            package_type,
            package_weight,
            package_dimensions,
            case_status,
            case_details,
            primary_image,
            additional_images,
            video_url,
            external_link,
            description,
            extra_attributes
        FROM products;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS products_admin_view")

    op.drop_column('products', 'extra_attributes')
    op.drop_column('products', 'case_details')
    op.drop_column('products', 'case_status')
    op.drop_column('products', 'storefront')
    op.drop_column('products', 'inventory_location')
    op.drop_column('products', 'manufacturing_country')
    op.drop_column('products', 'artist_names')
    op.drop_column('products', 'artist_owned')
    op.drop_column('products', 'handedness')
    op.drop_column('products', 'serial_number')

    for enum_name in (
        'casestatus',
        'storefront',
        'inventorylocation',
        'manufacturingcountry',
        'handedness',
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
