"""reset_courierstatus_enum

Revision ID: ae0d7585b7cd
Revises: c6c5a79e4d11
Create Date: 2026-09-30 20:38:41.505517

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'ae0d7585b7cd'
down_revision: Union[str, None] = 'c6c5a79e4d11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Convert column to text temporarily
    op.execute("ALTER TABLE courier_trips ALTER COLUMN status TYPE VARCHAR")

    # 2. Migrate any existing 'pending' rows to 'searching'
    op.execute("UPDATE courier_trips SET status = 'searching' WHERE status = 'pending' OR status = 'PENDING'")
    op.execute("UPDATE courier_trips SET status = LOWER(status) WHERE status IS NOT NULL")

    # 3. Rename old enum
    op.execute("ALTER TYPE courierstatus RENAME TO courierstatus_old")

    # 4. Create new enum without 'pending'
    op.execute("""
        CREATE TYPE courierstatus AS ENUM (
            'draft', 'searching', 'accepted', 
            'en_route_to_pickup', 'arrived', 'loading', 
            'in_transit', 'unloading', 'completed', 
            'cancelled', 'disputed'
        )
    """)

    # 5. Recast column to new enum type
    op.execute("ALTER TABLE courier_trips ALTER COLUMN status TYPE courierstatus USING status::courierstatus")

    # 6. Drop old enum
    op.execute("DROP TYPE courierstatus_old")

def downgrade() -> None:
    pass