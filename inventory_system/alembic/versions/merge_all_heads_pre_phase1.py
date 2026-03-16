"""Merge all existing heads before Phase 1 multi-tenancy.

Unifies three independent branches:
- add_platform_preferences (main feature chain)
- add_sync_errors_001 (sync errors branch)
- wc_multitenant_001 (WooCommerce stores branch)

Revision ID: merge_pre_phase1
Revises: add_platform_preferences, add_sync_errors_001, wc_multitenant_001
"""

from typing import Sequence, Union

revision: str = "merge_pre_phase1"
down_revision: Union[str, Sequence[str], None] = (
    "add_platform_preferences",
    "add_sync_errors_001",
    "wc_multitenant_001",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
