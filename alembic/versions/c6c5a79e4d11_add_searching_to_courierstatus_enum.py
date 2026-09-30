"""add searching to courierstatus enum

Revision ID: c6c5a79e4d11
Revises: 8d87d53881e4
Create Date: 2026-09-30 20:29:28.434943

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c6c5a79e4d11'
down_revision: Union[str, None] = '8d87d53881e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE courierstatus ADD VALUE IF NOT EXISTS 'searching'")
    op.execute("ALTER TYPE courierstatus ADD VALUE IF NOT EXISTS 'SEARCHING'")


def downgrade() -> None:
    pass