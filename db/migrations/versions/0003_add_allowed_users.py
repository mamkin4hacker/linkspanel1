"""add allowed_users table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'allowed_users',
        sa.Column('user_id',    sa.BigInteger(), primary_key=True),
        sa.Column('note',       sa.String(200),  nullable=True),
        sa.Column('granted_by', sa.BigInteger(), nullable=False),
        sa.Column('granted_at', sa.TIMESTAMP(),  server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('allowed_users')
