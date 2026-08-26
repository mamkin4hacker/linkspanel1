# База данных

## Схема таблиц

### `users`
```sql
CREATE TABLE users (
    id          BIGINT PRIMARY KEY,   -- telegram user id
    username    VARCHAR(64),
    created_at  TIMESTAMP DEFAULT now()
);
```

### `domains`
```sql
CREATE TABLE domains (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain           VARCHAR(255) UNIQUE NOT NULL,  -- "domain1.com"
    is_active        BOOLEAN DEFAULT true,
    subdomain_count  INT DEFAULT 0,                 -- для балансировки
    created_at       TIMESTAMP DEFAULT now()
);
```

### `templates`
```sql
CREATE TABLE templates (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      BIGINT REFERENCES users(id) ON DELETE CASCADE,
    name         VARCHAR(100),           -- произвольное название для пользователя

    -- визуальные настройки
    bg_color     VARCHAR(7) DEFAULT '#ffffff',
    text_color   VARCHAR(7) DEFAULT '#000000',
    font_family  VARCHAR(100) DEFAULT 'Inter, sans-serif',
    title        VARCHAR(200) DEFAULT '',
    description  TEXT DEFAULT '',
    button_text  VARCHAR(100) DEFAULT '',
    button_url   TEXT DEFAULT '',
    favicon_url  TEXT DEFAULT '',        -- путь к файлу в /static/favicons/
    custom_css   TEXT DEFAULT '',        -- санитизированный CSS

    created_at   TIMESTAMP DEFAULT now(),
    updated_at   TIMESTAMP DEFAULT now()
);
```

### `links`
```sql
CREATE TABLE links (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      BIGINT REFERENCES users(id) ON DELETE CASCADE,
    template_id  UUID REFERENCES templates(id) ON DELETE CASCADE,
    domain_id    UUID REFERENCES domains(id),

    subdomain    VARCHAR(60) NOT NULL,   -- "mypage" в mypage.domain.com
    link_id      VARCHAR(20) NOT NULL,   -- "abc123" в /abc123
    full_url     TEXT NOT NULL,          -- итоговый URL (денормализация для скорости)

    is_active    BOOLEAN DEFAULT true,
    visits       INT DEFAULT 0,

    created_at   TIMESTAMP DEFAULT now()
);
```

---

## Индексы

```sql
-- уникальность: один поддомен+путь на одном домене
CREATE UNIQUE INDEX ON links(subdomain, domain_id, link_id);

-- быстрый поиск при рендеринге страницы
CREATE INDEX ON links(subdomain, link_id) WHERE is_active = true;

-- балансировка: сортировка по счётчику
CREATE INDEX ON domains(subdomain_count) WHERE is_active = true;
```

---

## SQLAlchemy модели (db/models.py)

```python
import uuid
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Text, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class Domain(Base):
    __tablename__ = "domains"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    domain: Mapped[str] = mapped_column(String(255), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subdomain_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class Template(Base):
    __tablename__ = "templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    name: Mapped[str | None] = mapped_column(String(100))
    bg_color: Mapped[str] = mapped_column(String(7), default="#ffffff")
    text_color: Mapped[str] = mapped_column(String(7), default="#000000")
    font_family: Mapped[str] = mapped_column(String(100), default="Inter, sans-serif")
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    button_text: Mapped[str] = mapped_column(String(100), default="")
    button_url: Mapped[str] = mapped_column(Text, default="")
    favicon_url: Mapped[str] = mapped_column(Text, default="")
    custom_css: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

class Link(Base):
    __tablename__ = "links"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    template_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("templates.id"))
    domain_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("domains.id"))
    subdomain: Mapped[str] = mapped_column(String(60))
    link_id: Mapped[str] = mapped_column(String(20))
    full_url: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    visits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    template: Mapped[Template] = relationship("Template", lazy="joined")
    domain: Mapped[Domain] = relationship("Domain", lazy="joined")
```

---

## CRUD: выбор домена (db/crud/domains.py)

```python
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Domain

async def get_least_loaded_domain(session: AsyncSession) -> Domain | None:
    result = await session.execute(
        select(Domain)
        .where(Domain.is_active == True)
        .order_by(Domain.subdomain_count.asc())
        .limit(1)
        .with_for_update(skip_locked=True)  # защита от race condition
    )
    return result.scalar_one_or_none()

async def increment_subdomain_count(session: AsyncSession, domain_id) -> None:
    await session.execute(
        update(Domain)
        .where(Domain.id == domain_id)
        .values(subdomain_count=Domain.subdomain_count + 1)
    )
```

---

## Redis — ключи и TTL

| Ключ | Значение | TTL |
|---|---|---|
| `page:{subdomain}:{link_id}` | HTML строка | 5 мин |
| `preview:{user_id}` | JSON конфига шаблона | 10 мин |
| `preview_token:{token}` | user_id | 10 мин |
