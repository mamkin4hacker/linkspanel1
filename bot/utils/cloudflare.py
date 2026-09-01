"""
Cloudflare DNS verification utility.

Checks that a domain has both @ and * A-records pointing to the VPS IP.
Uses a single global CF_API_TOKEN from the environment.
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
    """Return Cloudflare zone ID for the given domain, or None if not found."""
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
) -> str | None:
    """Return the content (IP) of the first A record matching name, or None."""
    resp = await client.get(
        f"{_BASE}/zones/{zone_id}/dns_records",
        params={"type": "A", "name": name},
        headers=_headers(),
    )
    data = resp.json()
    if not data.get("success") or not data.get("result"):
        return None
    return data["result"][0]["content"]


async def check_dns(domain: str) -> tuple[bool, str]:
    """
    Verify that both @ and * A-records for *domain* point to VPS_IP.

    Returns (True, "") on success, or (False, human-readable error) on failure.
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
                f"Домен <code>{domain}</code> не найден в Cloudflare. "
                "Убедись, что домен добавлен в твой аккаунт и NS-серверы делегированы.",
            )

        # Check root A record (@)
        root_ip = await _get_a_record(client, zone_id, domain)
        if root_ip is None:
            return (
                False,
                f"A-запись для <code>{domain}</code> не найдена.\n"
                f"Добавь: <code>@ → A → {VPS_IP}</code>",
            )
        if root_ip != VPS_IP:
            return (
                False,
                f"A-запись <code>{domain}</code> указывает на <code>{root_ip}</code>, "
                f"а должна на <code>{VPS_IP}</code>.",
            )

        # Check wildcard A record (*)
        wildcard_ip = await _get_a_record(client, zone_id, f"*.{domain}")
        if wildcard_ip is None:
            return (
                False,
                f"Wildcard A-запись <code>*.{domain}</code> не найдена.\n"
                f"Добавь: <code>* → A → {VPS_IP}</code>",
            )
        if wildcard_ip != VPS_IP:
            return (
                False,
                f"Wildcard A-запись <code>*.{domain}</code> указывает на "
                f"<code>{wildcard_ip}</code>, а должна на <code>{VPS_IP}</code>.",
            )

    return True, ""
