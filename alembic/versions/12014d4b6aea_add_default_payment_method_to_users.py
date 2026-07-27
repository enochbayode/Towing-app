"""add default_payment_method to users

Revision ID: 12014d4b6aea
Revises: 63fa9dd00ec5
Create Date: 2026-07-27 13:20:11.876935

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '12014d4b6aea'
down_revision: Union[str, None] = '63fa9dd00ec5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    # 1. Create the custom Enum types in PostgreSQL explicitly FIRST
    payment_method_enum = postgresql.ENUM('CASH', 'CARD', name='paymentmethod', create_type=False)
    payment_status_enum = postgresql.ENUM('UNPAID', 'PAID', 'DEBT_LOGGED', name='paymentstatus', create_type=False)
    ledger_entry_enum = postgresql.ENUM('COMMISSION_DEBT', 'MANUAL_SETTLEMENT', 'CARD_PAYOUT', name='ledgerentrytype', create_type=False)

    payment_method_enum.create(op.get_bind(), checkfirst=True)
    payment_status_enum.create(op.get_bind(), checkfirst=True)
    ledger_entry_enum.create(op.get_bind(), checkfirst=True)

    # 2. Create the Company Ledgers table
    op.create_table('company_ledgers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('driver_id', sa.Uuid(), nullable=True),
        sa.Column('trip_id', sa.Uuid(), nullable=True),
        sa.Column('entry_type', ledger_entry_enum, nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['company.id'], ),
        sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index(op.f('ix_company_ledgers_company_id'), 'company_ledgers', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_ledgers_driver_id'), 'company_ledgers', ['driver_id'], unique=False)
    op.create_index(op.f('ix_company_ledgers_entry_type'), 'company_ledgers', ['entry_type'], unique=False)
    op.create_index(op.f('ix_company_ledgers_id'), 'company_ledgers', ['id'], unique=False)
    op.create_index(op.f('ix_company_ledgers_trip_id'), 'company_ledgers', ['trip_id'], unique=False)
    
    # 3. Add simple nullable string columns
    op.add_column('drivers', sa.Column('fcm_token', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('payment_accounts', sa.Column('paystack_subaccount_code', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_payment_accounts_paystack_subaccount_code'), 'payment_accounts', ['paystack_subaccount_code'], unique=False)
    
    # 4. Add Enum columns to existing tables using server_default to prevent null constraint crashes
    op.add_column('trips', sa.Column('payment_method', payment_method_enum, server_default='CASH', nullable=False))
    op.add_column('trips', sa.Column('payment_status', payment_status_enum, server_default='UNPAID', nullable=False))
    op.create_index(op.f('ix_trips_payment_method'), 'trips', ['payment_method'], unique=False)
    op.create_index(op.f('ix_trips_payment_status'), 'trips', ['payment_status'], unique=False)
    
    op.add_column('users', sa.Column('default_payment_method', payment_method_enum, server_default='CASH', nullable=False))


def downgrade() -> None:
    # Drop columns and tables
    op.drop_column('users', 'default_payment_method')
    op.drop_index(op.f('ix_trips_payment_status'), table_name='trips')
    op.drop_index(op.f('ix_trips_payment_method'), table_name='trips')
    op.drop_column('trips', 'payment_status')
    op.drop_column('trips', 'payment_method')
    op.drop_index(op.f('ix_payment_accounts_paystack_subaccount_code'), table_name='payment_accounts')
    op.drop_column('payment_accounts', 'paystack_subaccount_code')
    op.drop_column('drivers', 'fcm_token')
    
    op.drop_index(op.f('ix_company_ledgers_trip_id'), table_name='company_ledgers')
    op.drop_index(op.f('ix_company_ledgers_id'), table_name='company_ledgers')
    op.drop_index(op.f('ix_company_ledgers_entry_type'), table_name='company_ledgers')
    op.drop_index(op.f('ix_company_ledgers_driver_id'), table_name='company_ledgers')
    op.drop_index(op.f('ix_company_ledgers_company_id'), table_name='company_ledgers')
    op.drop_table('company_ledgers')

    # Drop the custom Postgres types
    payment_method_enum = postgresql.ENUM('CASH', 'CARD', name='paymentmethod', create_type=False)
    payment_status_enum = postgresql.ENUM('UNPAID', 'PAID', 'DEBT_LOGGED', name='paymentstatus', create_type=False)
    ledger_entry_enum = postgresql.ENUM('COMMISSION_DEBT', 'MANUAL_SETTLEMENT', 'CARD_PAYOUT', name='ledgerentrytype', create_type=False)
    
    payment_method_enum.drop(op.get_bind(), checkfirst=True)
    payment_status_enum.drop(op.get_bind(), checkfirst=True)
    ledger_entry_enum.drop(op.get_bind(), checkfirst=True)