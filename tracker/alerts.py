"""Phone alerts through Telegram and/or ntfy.

Telegram: set the TELEGRAM_TOKEN secret; the chat is found automatically after you send /start to your bot.
ntfy:     set the NTFY_TOPIC secret to a long random topic name and subscribe to it in the ntfy app.
"""
from __future__ import annotations

import html
import os
import time
from pathlib import Path

import requests

from .store import load_json, save_json

STATE = Path("data/alerted.json")
CHAT = Path(".state/telegram.json")  # kept in the private Actions cache, never committed (the repo is public)
API = "https://api.telegram.org/bot{token}/{method}"


def _chat_id(token: str) -> str | None:
    if os.environ.get("TELEGRAM_CHAT_ID"):
        return os.environ["TELEGRAM_CHAT_ID"]
    saved = load_json(CHAT, {})
    if saved.get("chat_id"):
        return str(saved["chat_id"])
    me = _tg(token, "getMe")
    if str(me.get("description", "")).startswith("network error"):
        print(f"Telegram: {me['description']}")
        t0 = time.time()
        try:
            root = requests.get("https://api.telegram.org/", timeout=20)
            print(f"Telegram: server itself answers HTTP {root.status_code} in {time.time() - t0:.1f}s "
                  f"(so the problem is specific to this token's request)")
        except requests.RequestException as e:
            print(f"Telegram: server unreachable from the runner ({type(e).__name__} after {time.time() - t0:.1f}s)")
        print(f"Telegram: saved token shape: {token_shape(os.environ.get('TELEGRAM_TOKEN', ''))}")
        bad = [hex(ord(c)) for c in os.environ.get("TELEGRAM_TOKEN", "") if ord(c) > 127 or not (c.isalnum() or c in ":_-")]
        print(f"Telegram: unusual characters in token: {len(bad)} {bad[:5]}")
        return None
    r = _tg(token, "getUpdates")
    if not me.get("ok"):
        print(f"Telegram: token rejected ({me.get('error_code')} {me.get('description')}). Re-copy the full token into TELEGRAM_TOKEN.")
        print(f"Telegram: saved token shape: {token_shape(os.environ.get('TELEGRAM_TOKEN', ''))}. A valid one is 8-10 digits, a colon, then 35 characters.")
        return None
    print(f"Telegram: token belongs to @{me['result'].get('username')}")
    if not r.get("ok"):
        print(f"Telegram: getUpdates failed ({r.get('error_code')} {r.get('description')})")
        return None
    print(f"Telegram: {len(r.get('result', []))} recent messages to the bot")
    for upd in reversed(r.get("result", [])):
        chat = (upd.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private":
            save_json(CHAT, {"chat_id": chat["id"]})
            return str(chat["id"])
    return None


def _tg(token: str, method: str, data: dict | None = None) -> dict:
    """Call the Telegram API with retries; returns the JSON reply or {'ok': False, 'description': ...}."""
    last = ""
    for attempt in range(4):
        try:
            url = API.format(token=token, method=method)
            r = requests.post(url, data=data, timeout=35) if data else requests.get(url, timeout=35)
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
            time.sleep(3 * (attempt + 1))
    return {"ok": False, "description": f"network error {last} after 4 tries"}


def token_shape(raw: str) -> str:
    """Describe a token's format without revealing it (for the run log)."""
    t = raw.strip()
    head, colon, tail = t.partition(":")
    return (f"length {len(raw)} (trimmed {len(t)}), colon: {'yes' if colon else 'NO'}, "
            f"part before colon: {len(head)} chars{' all digits' if head.isdigit() else ' NOT all digits'}, "
            f"part after: {len(tail)} chars, spaces/newlines inside: {'yes' if any(c.isspace() for c in t) else 'no'}")


def send(text: str) -> bool:
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    if not token:
        return False
    chat = _chat_id(token)
    if not chat:
        print("Telegram: no chat yet. Send /start to your bot.")
        return False
    r = _tg(token, "sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})
    if not r.get("ok"):
        print(f"Telegram: sendMessage failed ({r.get('error_code')} {r.get('description')})")
    return bool(r.get("ok"))


def pick_alerts(products: list[dict], items: dict, shops: dict) -> list[tuple[str, dict]]:
    """Decide what is worth a ping. Returns [(reason, product)], reason in deal / target / deal+target."""
    state = load_json(STATE, {})
    picks = []
    for p in products:
        if shops.get(p["s"], {}).get("alerts") is False:
            continue
        item = items.get(p["i"], {})
        target = item.get("max_price")
        last = state.get(p["k"])
        if last is not None and p["p"] >= last:
            continue
        deal = bool(p.get("low30") and p.get("drop_pct", 0) >= 10)
        under = bool(target and p["p"] <= target)
        if deal or under:
            picks.append(("deal+target" if deal and under else "deal" if deal else "target", p))
    picks.sort(key=lambda x: ("deal" not in x[0], x[1]["p"]))
    return picks


def mark_sent(picks):
    """Remember what was sent, only after a message actually reached the phone."""
    state = load_json(STATE, {})
    for _, p in picks:
        state[p["k"]] = p["p"]
    save_json(STATE, state)


def format_message(picks, items, shops, app_url: str, first_run: bool, total: int) -> str | None:
    if not picks and not first_run:
        return None
    lines = []
    if first_run:
        lines.append(f"🟢 <b>Deal tracker is live</b>: watching {total} products.")
    for reason, p in picks[:10]:
        item = items.get(p["i"], {})
        shop = shops.get(p["s"], {}).get("name", p["s"])
        tgt = f"under your {int(item.get('max_price') or 0)} KM target"
        head = {"deal": f"🔻 Real drop −{p.get('drop_pct', 0):.0f}%", "target": "🎯 " + tgt[0].upper() + tgt[1:],
                "deal+target": f"🔻 Real drop −{p.get('drop_pct', 0):.0f}%, {tgt}"}[reason]
        was = f" (was {p['prev']:.0f})" if p.get("prev") and p["prev"] > p["p"] else ""
        lines.append(f"{head} · {html.escape(item.get('name', p['i']))}\n<a href=\"{html.escape(p['u'])}\">{html.escape(p['t'][:80])}</a>\n"
                     f"<b>{p['p']:.0f} KM</b> at {html.escape(shop)}{was}")
    if len(picks) > 10:
        lines.append(f"…and {len(picks) - 10} more in the app.")
    if app_url:
        lines.append(f'<a href="{app_url}">Open the app</a>')
    return "\n\n".join(lines)


def send_ntfy(picks, items, shops, app_url: str, first_run: bool, total: int) -> int:
    """One push notification per deal (tapping it opens the shop page). Returns how many were sent."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return 0
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    sent = 0

    def push(title, body, click=None, tags="shopping_cart", priority="default"):
        nonlocal sent
        headers = {"Title": title.encode("utf-8"), "Tags": tags, "Priority": priority}
        if click:
            headers["Click"] = click
        try:
            r = requests.post(f"{server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=20)
            sent += int(r.ok)
        except requests.RequestException:
            pass

    if first_run:
        push("Deal tracker is live", f"Watching {total} products. You'll get a ping when something drops.", app_url or None, "white_check_mark")
    for reason, p in picks[:6]:
        item = items.get(p["i"], {})
        shop = shops.get(p["s"], {}).get("name", p["s"])
        if "deal" in reason:
            title = f"{item.get('name', p['i'])}: real drop -{p.get('drop_pct', 0):.0f}%"
        else:
            title = f"{item.get('name', p['i'])} under {int(item.get('max_price') or 0)} KM"
        was = f" (was {p['prev']:.0f})" if p.get("prev") and p["prev"] > p["p"] else ""
        push(title, f"{p['p']:.0f} KM at {shop}{was}\n{p['t'][:120]}", p["u"], "chart_with_downwards_trend" if "deal" in reason else "dart",
             "high" if reason == "deal+target" else "default")
    if len(picks) > 6:
        push("More deals", f"{len(picks) - 6} more in the app.", app_url or None, "shopping_cart")
    return sent
