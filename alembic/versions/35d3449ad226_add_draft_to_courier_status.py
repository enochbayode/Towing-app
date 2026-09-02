"""add_draft_to_courier_status

Revision ID: 35d3449ad226
Revises: c32fd3946492
Create Date: 2026-08-26 13:19:21.010933

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '35d3449ad226'
down_revision: Union[str, None] = 'c32fd3946492'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Add DRAFT to the existing enum
        op.execute("ALTER TYPE courierstatus ADD VALUE 'DRAFT'")


def downgrade() -> None:
    pass