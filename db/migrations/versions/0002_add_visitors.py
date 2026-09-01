"""add visitors table

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'visitors',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ip', sa.String(45), nullable=False),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('country', sa.String(100), nullable=True),
        sa.Column('device', sa.String(200), nullable=True),
        sa.Column('sys_lang', sa.String(20), nullable=True),
        sa.Column('first_seen', sa.TIMESTAMP(), server_default=sa.text('now()')),
    )
    op.create_index('ix_visitors_ip', 'visitors', ['ip'], unique=True)


def downgrade():
    op.drop_table('visitors')
