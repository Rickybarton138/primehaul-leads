"""add_referral_and_error_tracking

Revision ID: a1b2c3d4e5f6
Revises: 133ca12100fb
Create Date: 2026-03-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '133ca12100fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Referral reward columns on leads (idempotent)
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='leads' AND column_name='referral_count'"
    ))
    if result.fetchone() is None:
        op.add_column('leads', sa.Column('referral_count', sa.Integer(), nullable=True, server_default='0'))
        op.add_column('leads', sa.Column('referral_discount_pct', sa.Integer(), nullable=True, server_default='0'))

    # Error logs table (idempotent)
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='error_logs')"
    ))
    if not result.scalar():
        op.create_table('error_logs',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('level', sa.String(length=20), nullable=False),
            sa.Column('source', sa.String(length=255), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('traceback', sa.Text(), nullable=True),
            sa.Column('request_url', sa.String(length=500), nullable=True),
            sa.Column('request_method', sa.String(length=10), nullable=True),
            sa.Column('user_agent', sa.String(length=500), nullable=True),
            sa.Column('ip_address', sa.String(length=45), nullable=True),
            sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )


def downgrade() -> None:
    op.drop_table('error_logs')
    op.drop_column('leads', 'referral_discount_pct')
    op.drop_column('leads', 'referral_count')
