import uuid
import pytest
import pytest_asyncio

from db.crud.domains import (
    create_domain,
    get_least_loaded_domain,
    increment_subdomain_count,
    decrement_subdomain_count,
    get_all_active_domains,
)
from db.crud.users import get_or_create_user
from db.crud.templates import create_template, update_template, get_template_by_id
from db.crud.links import (
    create_link,
    get_link_by_subdomain_and_id,
    get_links_by_user,
    count_links_by_user,
    get_link_by_id,
    soft_delete_link,
    increment_visits,
)

pytestmark = pytest.mark.asyncio


# ── helpers ────────────────────────────────────────────────────────────────────

async def _make_user(session, uid=None):
    uid = uid or (abs(hash(str(uuid.uuid4()))) % 10**9)
    return await get_or_create_user(session, uid, f"user_{uid}")


async def _make_domain(session, name=None):
    name = name or f"{uuid.uuid4().hex[:8]}.test"
    return await create_domain(session, name)


async def _make_template(session, user_id):
    return await create_template(session, user_id=user_id, title="Test", autocommit=False)


async def _make_link(session, user_id, domain, subdomain=None, link_id=None):
    subdomain = subdomain or uuid.uuid4().hex[:8]
    link_id = link_id or uuid.uuid4().hex[:8]
    full_url = f"https://{subdomain}.{domain.domain}/{link_id}"
    tpl = await _make_template(session, user_id)
    return await create_link(
        session,
        autocommit=False,
        user_id=user_id,
        template_id=tpl.id,
        domain_id=domain.id,
        subdomain=subdomain,
        link_id=link_id,
        full_url=full_url,
    )


# ── users ──────────────────────────────────────────────────────────────────────

class TestUsers:
    async def test_create_user(self, db_session):
        user = await _make_user(db_session, uid=111111)
        assert user.id == 111111

    async def test_get_existing_user(self, db_session):
        await get_or_create_user(db_session, 222222, "alice")
        user2 = await get_or_create_user(db_session, 222222, "alice")
        assert user2.id == 222222

    async def test_username_updated(self, db_session):
        await get_or_create_user(db_session, 333333, "old_name")
        user = await get_or_create_user(db_session, 333333, "new_name")
        assert user.username == "new_name"


# ── domains ────────────────────────────────────────────────────────────────────

class TestDomains:
    async def test_create_domain(self, db_session):
        domain = await _make_domain(db_session)
        assert domain.id is not None
        assert domain.subdomain_count == 0
        assert domain.is_active is True

    async def test_get_least_loaded(self, db_session):
        d1 = await _make_domain(db_session)
        d2 = await _make_domain(db_session)
        await increment_subdomain_count(db_session, d1.id)
        await db_session.flush()

        least = await get_least_loaded_domain(db_session)
        assert least is not None
        # d2 has count 0, d1 has count 1 — d2 should be returned
        assert least.id == d2.id

    async def test_increment(self, db_session):
        domain = await _make_domain(db_session)
        await increment_subdomain_count(db_session, domain.id)
        await db_session.flush()
        await db_session.refresh(domain)
        assert domain.subdomain_count == 1

    async def test_decrement(self, db_session):
        domain = await _make_domain(db_session)
        await increment_subdomain_count(db_session, domain.id)
        await increment_subdomain_count(db_session, domain.id)
        await db_session.flush()
        await decrement_subdomain_count(db_session, domain.id)
        await db_session.flush()
        await db_session.refresh(domain)
        assert domain.subdomain_count == 1

    async def test_decrement_no_negative(self, db_session):
        domain = await _make_domain(db_session)
        # count is 0, decrement should be no-op (WHERE subdomain_count > 0)
        await decrement_subdomain_count(db_session, domain.id)
        await db_session.flush()
        await db_session.refresh(domain)
        assert domain.subdomain_count == 0

    async def test_get_all_active(self, db_session):
        d = await _make_domain(db_session)
        domains = await get_all_active_domains(db_session)
        ids = [x.id for x in domains]
        assert d.id in ids


# ── templates ──────────────────────────────────────────────────────────────────

class TestTemplates:
    async def test_create_template(self, db_session):
        user = await _make_user(db_session)
        tpl = await create_template(db_session, user_id=user.id, title="Hello", autocommit=False)
        assert tpl.id is not None
        assert tpl.title == "Hello"
        assert tpl.bg_color == "#ffffff"

    async def test_get_by_id(self, db_session):
        user = await _make_user(db_session)
        tpl = await create_template(db_session, user_id=user.id, autocommit=False)
        await db_session.flush()
        fetched = await get_template_by_id(db_session, tpl.id)
        assert fetched.id == tpl.id

    async def test_get_by_id_not_found(self, db_session):
        result = await get_template_by_id(db_session, uuid.uuid4())
        assert result is None

    async def test_update_template(self, db_session):
        user = await _make_user(db_session)
        tpl = await create_template(db_session, user_id=user.id, title="Old", autocommit=False)
        await db_session.flush()
        updated = await update_template(db_session, tpl.id, title="New", bg_color="#000000")
        assert updated.title == "New"
        assert updated.bg_color == "#000000"

    async def test_update_nonexistent(self, db_session):
        result = await update_template(db_session, uuid.uuid4(), title="X")
        assert result is None


# ── links ──────────────────────────────────────────────────────────────────────

class TestLinks:
    async def test_create_link(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        link = await _make_link(db_session, user.id, domain)
        assert link.id is not None
        assert link.is_active is True
        assert link.visits == 0

    async def test_get_by_subdomain_and_id(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        link = await _make_link(db_session, user.id, domain, subdomain="mysub", link_id="mylink1")
        await db_session.flush()

        fetched = await get_link_by_subdomain_and_id(db_session, "mysub", "mylink1")
        assert fetched is not None
        assert fetched.id == link.id

    async def test_get_by_subdomain_not_found(self, db_session):
        result = await get_link_by_subdomain_and_id(db_session, "nosub", "noid")
        assert result is None

    async def test_get_links_by_user(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        await _make_link(db_session, user.id, domain)
        await _make_link(db_session, user.id, domain)
        await db_session.flush()

        links = await get_links_by_user(db_session, user.id)
        assert len(links) == 2

    async def test_count_links_by_user(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        await _make_link(db_session, user.id, domain)
        await _make_link(db_session, user.id, domain)
        await db_session.flush()

        count = await count_links_by_user(db_session, user.id)
        assert count == 2

    async def test_soft_delete(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        link = await _make_link(db_session, user.id, domain, subdomain="delsub", link_id="delid1")
        await db_session.flush()

        await soft_delete_link(db_session, link.id, autocommit=False)
        await db_session.flush()

        fetched = await get_link_by_subdomain_and_id(db_session, "delsub", "delid1")
        assert fetched is None

    async def test_soft_delete_not_in_list(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        link = await _make_link(db_session, user.id, domain)
        await db_session.flush()

        await soft_delete_link(db_session, link.id, autocommit=False)
        await db_session.flush()

        links = await get_links_by_user(db_session, user.id)
        assert all(l.id != link.id for l in links)

    async def test_increment_visits(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        link = await _make_link(db_session, user.id, domain)
        await db_session.flush()

        await increment_visits(db_session, link.id)
        await db_session.flush()
        await db_session.refresh(link)
        assert link.visits == 1

    async def test_get_link_by_id(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        link = await _make_link(db_session, user.id, domain)
        await db_session.flush()

        fetched = await get_link_by_id(db_session, link.id)
        assert fetched.id == link.id

    async def test_pagination(self, db_session):
        user = await _make_user(db_session)
        domain = await _make_domain(db_session)
        for _ in range(5):
            await _make_link(db_session, user.id, domain)
        await db_session.flush()

        page1 = await get_links_by_user(db_session, user.id, offset=0, limit=3)
        page2 = await get_links_by_user(db_session, user.id, offset=3, limit=3)
        assert len(page1) == 3
        assert len(page2) == 2
        ids1 = {l.id for l in page1}
        ids2 = {l.id for l in page2}
        assert ids1.isdisjoint(ids2)
