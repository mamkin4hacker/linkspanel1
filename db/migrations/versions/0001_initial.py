"""initial

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('username', sa.String(64), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
    )

    op.create_table(
        'domains',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('domain', sa.String(255), unique=True, nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('subdomain_count', sa.Integer(), server_default=sa.text('0')),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
    )

    op.create_table(
        'templates',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('bg_color', sa.String(7), server_default=sa.text("'#ffffff'")),
        sa.Column('text_color', sa.String(7), server_default=sa.text("'#000000'")),
        sa.Column('font_family', sa.String(100), server_default=sa.text("'Inter, sans-serif'")),
        sa.Column('title', sa.String(200), server_default=sa.text("''")),
        sa.Column('description', sa.Text(), server_default=sa.text("''")),
        sa.Column('button_text', sa.String(100), server_default=sa.text("''")),
        sa.Column('button_url', sa.Text(), server_default=sa.text("''")),
        sa.Column('favicon_url', sa.Text(), server_default=sa.text("''")),
        sa.Column('custom_css', sa.Text(), server_default=sa.text("''")),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
    )

    op.create_table(
        'links',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('template_id', UUID(as_uuid=True), sa.ForeignKey('templates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('domain_id', UUID(as_uuid=True), sa.ForeignKey('domains.id'), nullable=False),
        sa.Column('subdomain', sa.String(60), nullable=False),
        sa.Column('link_id', sa.String(20), nullable=False),
        sa.Column('full_url', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('visits', sa.Integer(), server_default=sa.text('0')),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
    )

    op.create_index('uq_links_subdomain_domain_linkid', 'links', ['subdomain', 'domain_id', 'link_id'], unique=True)
    op.create_index('ix_links_active_lookup', 'links', ['subdomain', 'link_id'],
                    postgresql_where=sa.text('is_active = true'))
    op.create_index('ix_domains_subdomain_count', 'domains', ['subdomain_count'],
                    postgresql_where=sa.text('is_active = true'))


def downgrade():
    op.drop_table('links')
    op.drop_table('templates')
    op.drop_table('domains')
    op.drop_table('users')
