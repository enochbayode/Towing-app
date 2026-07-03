"""force update trip table

Revision ID: f2b328e5d6d6
Revises: c0dfb5fc42e5
Create Date: 2026-07-02 22:52:29.435662

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f2b328e5d6d6'
down_revision: Union[str, None] = 'c0dfb5fc42e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass