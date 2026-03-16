"""Phase 1.5: Replace single-column unique constraints with tenant-scoped composites.

Drops old unique constraints that assumed single-tenant data, and replaces
them with (tenant_id, column) composites so the same value can exist
across different tenants.

Also adds composite indexes on frequently queried (tenant_id, ...) pairs
for efficient tenant-scoped queries.

Revision ID: phase1_005
Revises: phase1_004
"""

from typing import Sequence, Union

from alembic import op

revision: str = "phase1_005"
down_revision: Union[str, Sequence[str], None] = "phase1_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Drop old single-column unique constraints, add composite replacements ---

    # products.sku: drop unique index, add (tenant_id, sku) composite
    op.drop_constraint("products_sku_key", "products", type_="unique")
    op.create_unique_constraint("uq_product_sku_per_tenant", "products", ["tenant_id", "sku"])

    # ebay_listings.ebay_item_id: drop unique, add composite
    op.drop_constraint("ebay_listings_ebay_item_id_key", "ebay_listings", type_="unique")
    op.create_unique_constraint("uq_ebay_item_per_tenant", "ebay_listings", ["tenant_id", "ebay_item_id"])

    # woocommerce_orders.wc_order_id: drop unique, add composite
    op.drop_constraint("woocommerce_orders_wc_order_id_key", "woocommerce_orders", type_="unique")
    op.create_unique_constraint("uq_wc_order_per_tenant", "woocommerce_orders", ["tenant_id", "wc_order_id"])

    # shopify_orders.shopify_order_id: drop unique, add composite
    op.drop_constraint("shopify_orders_shopify_order_id_key", "shopify_orders", type_="unique")
    op.create_unique_constraint("uq_shopify_order_per_tenant", "shopify_orders", ["tenant_id", "shopify_order_id"])

    # reverb_historical_listings.reverb_listing_id: drop unique, add composite
    op.drop_constraint("reverb_historical_listings_reverb_listing_id_key", "reverb_historical_listings", type_="unique")
    op.create_unique_constraint(
        "uq_reverb_historical_listing_per_tenant", "reverb_historical_listings", ["tenant_id", "reverb_listing_id"]
    )

    # platform_preferences.username: drop unique, add composite
    op.drop_constraint("platform_preferences_username_key", "platform_preferences", type_="unique")
    op.create_unique_constraint("uq_preference_username_per_tenant", "platform_preferences", ["tenant_id", "username"])

    # --- Add composite indexes for query performance ---
    op.create_index("ix_products_tenant_product_id", "products", ["tenant_id", "id"])
    op.create_index("ix_platform_common_tenant_product", "platform_common", ["tenant_id", "product_id"])
    op.create_index("ix_sales_tenant_product", "sales", ["tenant_id", "product_id"])
    op.create_index("ix_sync_events_tenant_platform", "sync_events", ["tenant_id", "platform_name"])
    op.create_index("ix_activity_log_tenant_created", "activity_log", ["tenant_id", "created_at"])
    op.create_index("ix_sync_errors_tenant_created", "sync_errors", ["tenant_id", "created_at"])
    op.create_index("ix_orders_tenant_id_pk", "orders", ["tenant_id", "id"])


def downgrade() -> None:
    # Drop composite indexes
    op.drop_index("ix_orders_tenant_id_pk", table_name="orders")
    op.drop_index("ix_sync_errors_tenant_created", table_name="sync_errors")
    op.drop_index("ix_activity_log_tenant_created", table_name="activity_log")
    op.drop_index("ix_sync_events_tenant_platform", table_name="sync_events")
    op.drop_index("ix_sales_tenant_product", table_name="sales")
    op.drop_index("ix_platform_common_tenant_product", table_name="platform_common")
    op.drop_index("ix_products_tenant_product_id", table_name="products")

    # Restore original unique constraints
    op.drop_constraint("uq_preference_username_per_tenant", "platform_preferences", type_="unique")
    op.create_unique_constraint("platform_preferences_username_key", "platform_preferences", ["username"])

    op.drop_constraint("uq_reverb_historical_listing_per_tenant", "reverb_historical_listings", type_="unique")
    op.create_unique_constraint(
        "reverb_historical_listings_reverb_listing_id_key", "reverb_historical_listings", ["reverb_listing_id"]
    )

    op.drop_constraint("uq_shopify_order_per_tenant", "shopify_orders", type_="unique")
    op.create_unique_constraint("shopify_orders_shopify_order_id_key", "shopify_orders", ["shopify_order_id"])

    op.drop_constraint("uq_wc_order_per_tenant", "woocommerce_orders", type_="unique")
    op.create_unique_constraint("woocommerce_orders_wc_order_id_key", "woocommerce_orders", ["wc_order_id"])

    op.drop_constraint("uq_ebay_item_per_tenant", "ebay_listings", type_="unique")
    op.create_unique_constraint("ebay_listings_ebay_item_id_key", "ebay_listings", ["ebay_item_id"])

    op.drop_constraint("uq_product_sku_per_tenant", "products", type_="unique")
    op.create_unique_constraint("products_sku_key", "products", ["sku"])
