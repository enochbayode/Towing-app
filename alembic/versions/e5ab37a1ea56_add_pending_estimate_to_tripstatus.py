"""add_pending_estimate_to_tripstatus

Revision ID: e5ab37a1ea56
Revises: 12014d4b6aea
Create Date: 2026-07-27 23:26:36.768021

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e5ab37a1ea56'
down_revision: Union[str, None] = '12014d4b6aea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use autocommit_block because Postgres does not allow ALTER TYPE inside a transaction
    with op.get_context().autocommit_block():
        # Add the exact uppercase string that SQLAlchemy is attempting to insert
        op.execute("ALTER TYPE tripstatus ADD VALUE IF NOT EXISTS 'PENDING_ESTIMATE'")
        
        # Also add the lowercase version just in case you query by value later
        op.execute("ALTER TYPE tripstatus ADD VALUE IF NOT EXISTS 'pending_estimate'")

def downgrade() -> None:
    # Postgres does not support dropping a single value from an Enum easily.
    # Leave this pass.
    pass