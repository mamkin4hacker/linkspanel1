"""
Cloudflare DNS utility.

Ensures both @ and * A-records for a domain point to VPS_IP.
Creates or updates records automatically — no manual DNS setup needed.
"""
import os

import httpx

CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
VPS_IP = os.getenv("VPS_IP", "")

_BASE = "https://api.cloudflare.com/client/v4"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }


async def _get_zone_id(client: httpx.AsyncClient, domain: str) -> str | None:
    resp = await client.get(
        f"{_BASE}/zones",
        params={"name": domain},
        headers=_headers(),
    )
    data = resp.json()
    if not data.get("success") or not data.get("result"):
        return None
    return data["result"][0]["id"]


async def _get_a_record(
    client: httpx.AsyncClient, zone_id: str, name: str
) -> tuple[str | None, str | None]:
    """Return (record_id, ip) of the first matching A record, or (None, None)."""
    resp = await client.get(
        f"{_BASE}/zones/{zone_id}/dns_records",
        params={"type": "A", "name": name},
        headers=_headers(),
    )
    data = resp.json()
    if not data.get("success") or not data.get("result"):
        return None, None
    rec = data["result"][0]
    return rec["id"], rec["content"]


async def _create_a_record(
    client: httpx.AsyncClient, zone_id: str, name: str, ip: str
) -> bool:
    resp = await client.post(
        f"{_BASE}/zones/{zone_id}/dns_records",
        headers=_headers(),
        json={"type": "A", "name": name, "content": ip, "ttl": 1, "proxied": False},
    )
    return resp.json().get("success", False)


async def _update_a_record(
    client: httpx.AsyncClient, zone_id: str, record_id: str, name: str, ip: str
) -> bool:
    resp = await client.put(
        f"{_BASE}/zones/{zone_id}/dns_records/{record_id}",
        headers=_headers(),
        json={"type": "A", "name": name, "content": ip, "ttl": 1, "proxied": False},
    )
    return resp.json().get("success", False)


async def _ensure_a_record(
    client: httpx.AsyncClient, zone_id: str, name: str, ip: str
) -> tuple[bool, str]:
    """
    Make sure an A record for *name* points to *ip*.
    Creates it if missing, updates if wrong. Returns (ok, action_description).
    """
    record_id, current_ip = await _get_a_record(client, zone_id, name)

    if record_id is None:
        ok = await _create_a_record(client, zone_id, name, ip)
        if not ok:
            return False, f"не удалось создать A-запись для <code>{name}</code>"
        return True, f"создана <code>{name} → {ip}</code>"

    if current_ip == ip:
        return True, f"<code>{name}</code> уже указывает на <code>{ip}</code>"

    ok = await _update_a_record(client, zone_id, record_id, name, ip)
    if not ok:
        return False, f"не удалось обновить A-запись <code>{name}</code> (было {current_ip})"
    return True, f"обновлена <code>{name} → {ip}</code> (было {current_ip})"


async def setup_dns(domain: str) -> tuple[bool, str]:
    """
    Ensure @ and * A-records for *domain* point to VPS_IP.
    Creates or updates records automatically.

    Returns (True, summary) on success, (False, error) on failure.
    """
    if not CF_API_TOKEN:
        return False, "CF_API_TOKEN не задан в .env"
    if not VPS_IP:
        return False, "VPS_IP не задан в .env"

    async with httpx.AsyncClient(timeout=15) as client:
        zone_id = await _get_zone_id(client, domain)
        if zone_id is None:
            return (
                False,
                f"Домен <code>{domain}</code> не найден в Cloudflare.\n"
                "Убедись, что домен добавлен в аккаунт и NS-серверы делегированы на Cloudflare.",
            )

        ok_root, msg_root = await _ensure_a_record(client, zone_id, domain, VPS_IP)
        if not ok_root:
            return False, msg_root

        ok_wild, msg_wild = await _ensure_a_record(client, zone_id, f"*.{domain}", VPS_IP)
        if not ok_wild:
            return False, msg_wild

    summary = f"• {msg_root}\n• {msg_wild}"
    return True, summary
