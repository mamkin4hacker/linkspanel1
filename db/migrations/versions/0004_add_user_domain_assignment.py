"""add user_id FK to domains for per-user domain isolation

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'domains',
        sa.Column('user_id', sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        'fk_domains_user_id',
        'domains', 'users',
        ['user_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_domains_user_id', 'domains', ['user_id'])
    op.create_unique_constraint('uq_domains_user_id', 'domains', ['user_id'])


def downgrade():
    op.drop_constraint('uq_domains_user_id', 'domains', type_='unique')
    op.drop_index('ix_domains_user_id', table_name='domains')
    op.drop_constraint('fk_domains_user_id', 'domains', type_='foreignkey')
    op.drop_column('domains', 'user_id')
