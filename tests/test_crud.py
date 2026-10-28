import uuid
import pytest
import pytest_asyncio

from db.crud.domains import (
    create_domain,
    get_least_loaded_domain,
    increment_subdomain_count,
    decrement_subdomain_count,
    get_all_active_domains,
    list_domains,
    get_domain_by_id,
    reassign_domain,
    delete_domain,
    unassign_domain_from_user,
    assign_domain_to_user,
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
    subdomain_is_taken,
)

pytestmark = pytest.mark.asyncio


# ── helpers ────────────────────────────────────────────────────────────────────

async def _make_user(session, uid=None):
    uid = uid or (abs(hash(str(uuid.uuid4()))) % 10**9)
    return await get_or_create_user(session, uid, f"user_{uid}", autocommit=False)


async def _make_domain(session, name=None):
    name = name or f"{uuid.uuid4().hex[:8]}.test"
    return await create_domain(session, name, autocommit=False)


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
        await get_or_create_user(db_session, 333333, "old_name", autocommit=False)
        user = await get_or_create_user(db_session, 333333, "new_name", autocommit=False)
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

    async def test_list_domains_includes_assigned(self, db_session):
        user = await _make_user(db_session)
        d = await _make_domain(db_session)
        await assign_domain_to_user(db_session, d.id, user.id, autocommit=False)
        await db_session.flush()
        listed = await list_domains(db_session)
        assert any(x.id == d.id and x.user_id == user.id for x in listed)

    async def test_reassign_moves_from_previous_owner(self, db_session):
        u1 = await _make_user(db_session)
        u2 = await _make_user(db_session)
        d = await _make_domain(db_session)
        await assign_domain_to_user(db_session, d.id, u1.id, autocommit=False)
        await db_session.flush()
        moved = await reassign_domain(db_session, d.id, u2.id, autocommit=False)
        await db_session.flush()
        await db_session.refresh(d)
        assert moved is not None
        assert d.user_id == u2.id

    async def test_reassign_releases_users_old_domain(self, db_session):
        u = await _make_user(db_session)
        old = await _make_domain(db_session)
        new = await _make_domain(db_session)
        await assign_domain_to_user(db_session, old.id, u.id, autocommit=False)
        await db_session.flush()
        await reassign_domain(db_session, new.id, u.id, autocommit=False)
        await db_session.flush()
        await db_session.refresh(old)
        await db_session.refresh(new)
        assert old.user_id is None
        assert new.user_id == u.id

    async def test_delete_domain_refuses_when_links_exist(self, db_session):
        user = await _make_user(db_session)
        d = await _make_domain(db_session)
        await _make_link(db_session, user.id, d)
        await db_session.flush()
        ok, reason = await delete_domain(db_session, d.id, autocommit=False)
        assert ok is False
        assert "ссыл" in reason.lower()

    async def test_delete_domain_ok_when_empty(self, db_session):
        d = await _make_domain(db_session)
        await db_session.flush()
        did = d.id
        ok, reason = await delete_domain(db_session, did, autocommit=False)
        await db_session.flush()
        assert ok is True
        assert await get_domain_by_id(db_session, did) is None


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
        updated = await update_template(db_session, tpl.id, title="New", bg_color="#000000", autocommit=False)
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

    async def test_same_subdomain_ok_on_different_domains(self, db_session):
        user_a = await _make_user(db_session)
        user_b = await _make_user(db_session)
        domain_a = await _make_domain(db_session, "a.test")
        domain_b = await _make_domain(db_session, "b.test")
        link_a = await _make_link(
            db_session, user_a.id, domain_a, subdomain="shop", link_id="aaaa1111"
        )
        link_b = await _make_link(
            db_session, user_b.id, domain_b, subdomain="shop", link_id="bbbb2222"
        )
        await db_session.flush()

        assert await subdomain_is_taken(db_session, "shop", domain_a.id) is True
        assert await subdomain_is_taken(db_session, "shop", domain_b.id) is True

        fetched_a = await get_link_by_subdomain_and_id(
            db_session, "shop", "aaaa1111", domain="a.test"
        )
        fetched_b = await get_link_by_subdomain_and_id(
            db_session, "shop", "bbbb2222", domain="b.test"
        )
        assert fetched_a.id == link_a.id
        assert fetched_b.id == link_b.id
        wrong = await get_link_by_subdomain_and_id(
            db_session, "shop", "aaaa1111", domain="b.test"
        )
        assert wrong is None

    async def test_subdomain_free_on_other_domain(self, db_session):
        user = await _make_user(db_session)
        domain_a = await _make_domain(db_session, "one.test")
        domain_b = await _make_domain(db_session, "two.test")
        await _make_link(db_session, user.id, domain_a, subdomain="pay")
        await db_session.flush()

        assert await subdomain_is_taken(db_session, "pay", domain_a.id) is True
        assert await subdomain_is_taken(db_session, "pay", domain_b.id) is False

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
