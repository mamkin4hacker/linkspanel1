"""
Certbot SSL certificate issuance utility.

Runs certbot on the host via subprocess (certbot must be installed on the host).
Uses Cloudflare DNS plugin for wildcard certificate validation.
"""
import asyncio
import os

CERTBOT_EMAIL = os.getenv("CERTBOT_EMAIL", "")
CF_CREDENTIALS = os.getenv("CF_CREDENTIALS", "/root/.cloudflare/credentials.ini")
CERT_TIMEOUT = int(os.getenv("CERTBOT_TIMEOUT", "240"))


async def issue_cert(domain: str) -> tuple[bool, str]:
    """
    Issue a wildcard SSL certificate for *domain* via certbot + Cloudflare DNS.

    Returns (True, "") on success, or (False, error_message) on failure.
    Certificate ends up at /etc/letsencrypt/live/{domain}/
    """
    if not CERTBOT_EMAIL:
        return False, "CERTBOT_EMAIL не задан в .env"

    cmd = [
        "certbot", "certonly",
        "--dns-cloudflare",
        f"--dns-cloudflare-credentials={CF_CREDENTIALS}",
        "--dns-cloudflare-propagation-seconds=60",
        "--non-interactive",
        "--agree-tos",
        f"--email={CERTBOT_EMAIL}",
        f"-d={domain}",
        f"-d=*.{domain}",
        "--expand",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=CERT_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return False, f"certbot завис (таймаут {CERT_TIMEOUT}с). Попробуй ещё раз."

        output = stdout.decode(errors="replace") if stdout else ""

        if proc.returncode == 0:
            return True, ""

        # Extract the most useful line from certbot output
        lines = [l.strip() for l in output.splitlines() if l.strip()]
        error_lines = [l for l in lines if "error" in l.lower() or "Error" in l]
        summary = error_lines[-1] if error_lines else (lines[-1] if lines else "неизвестная ошибка")
        return False, f"certbot завершился с кодом {proc.returncode}:\n<code>{summary}</code>"

    except FileNotFoundError:
        return False, "certbot не найден. Установи: <code>apt install certbot python3-certbot-dns-cloudflare</code>"
    except Exception as e:
        return False, f"Ошибка запуска certbot: <code>{e}</code>"
