"""force update trip table

Revision ID: 63fa9dd00ec5
Revises: f2b328e5d6d6
Create Date: 2026-07-02 23:04:22.186280

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '63fa9dd00ec5'
down_revision: Union[str, None] = 'f2b328e5d6d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass