"""add accent_color to templates

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'templates',
        sa.Column('accent_color', sa.String(7), nullable=False, server_default='#29abe2'),
    )


def downgrade():
    op.drop_column('templates', 'accent_color')
