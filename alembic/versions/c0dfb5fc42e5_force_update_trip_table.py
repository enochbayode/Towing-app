"""force update trip table

Revision ID: c0dfb5fc42e5
Revises: fda60b9d7461
Create Date: 2026-07-02 20:57:52.555683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c0dfb5fc42e5'
down_revision: Union[str, None] = 'fda60b9d7461'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass