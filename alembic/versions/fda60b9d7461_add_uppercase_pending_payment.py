"""add_uppercase_pending_payment

Revision ID: fda60b9d7461
Revises: d2b50d9fc734
Create Date: 2026-07-02 15:38:00.950926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'fda60b9d7461'
down_revision: Union[str, None] = 'd2b50d9fc734'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE tripstatus ADD VALUE 'PENDING_PAYMENT'")
    pass


def downgrade() -> None:
    pass