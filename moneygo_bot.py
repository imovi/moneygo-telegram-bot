import os
import time
import json
import requests
from datetime import datetime, timedelta
from threading import Thread

# ----- TIMEZONE (BD Time) -----
os.environ['TZ'] = 'Asia/Dhaka'
time.tzset()

# ------------ CONFIG ------------

RATES_URL = "https://api.money-go.com/api/currencies/rates"

# Render এ চালালে BOT_TOKEN, CHAT_ID env variable হিসেবে সেট করো
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# যদি PC থেকে চালাও, তাহলে উপরের দুই লাইনের বদলে নিচের মত করে লিখতে পারো:
# BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
# CHAT_ID = "852271924"   # বা তোমার চ্যাট আইডি

ADMIN_ID = 852271924   # তোমার chat id (stats command শুধু তোমাকে দেখাবে)

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

HISTORY_FILE = "rate_history.json"      # শুধু USD/BDT history
SUBSCRIBERS_FILE = "subscribers.json"   # সবাইকে এখানে রাখব


# ------------ BASIC HELPERS ------------

def tg_send(chat_id, text, parse_mode="Markdown"):
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    try:
        requests.post(url, data=payload, timeout=15)
    except Exception as e:
        print("[TG] send error:", e)


def get_pair_rate(base: str, quote: str):
    """
    base/quote pair এর rate বের করবে।
    যেমন: USD/BDT, USD/TRY ইত্যাদি।
    যদি API তে quote/base থাকে তাহলে inverse করে রিটার্ন করবে।
    """
    base = base.upper()
    quote = quote.upper()
    pair1 = f"{base}/{quote}"
    pair2 = f"{quote}/{base}"

    resp = requests.get(RATES_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # সরাসরি base/quote থাকলে
    for item in data["data"]:
        if item["name"] == pair1:
            return float(item["value"]), pair1, False

    # না থাকলে inverse pair দেখি
    for item in data["data"]:
        if item["name"] == pair2:
            v = float(item["value"])
            if v == 0:
                raise ValueError("Zero rate in API")
            return 1.0 / v, pair2, True

    raise ValueError(f"Pair {base}/{quote} not found")


def get_usd_bdt_rate():
    rate, _, _ = get_pair_rate("USD", "BDT")
    return rate


# ------------ HISTORY (last 24h for USD/BDT) ------------

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f)


def update_history(current_rate: float):
    now = datetime.now()
    history = load_history()
    history.append({"ts": now.isoformat(), "rate": current_rate})

    cutoff = now - timedelta(days=1)
    new_history = []
    for item in history:
        try:
            ts = datetime.fromisoformat(item["ts"])
        except Exception:
            continue
        if ts >= cutoff:
            new_history.append(item)

    save_history(new_history)
    return new_history


def get_stats_last_24h(history):
    if not history:
        return None, None, None, None

    high = max(history, key=lambda x: x["rate"])
    low = min(history, key=lambda x: x["rate"])

    try:
        high_ts = datetime.fromisoformat(high["ts"])
    except Exception:
        high_ts = None

    try:
        low_ts = datetime.fromisoformat(low["ts"])
    except Exception:
        low_ts = None

    return high["rate"], high_ts, low["rate"], low_ts


# ------------ SUBSCRIBERS (সবার জন্য open) ------------

def load_subscribers():
    if not os.path.exists(SUBSCRIBERS_FILE):
        return []
    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f)


def add_or_update_subscriber(chat_id, first_name, username):
    subs = load_subscribers()
    for s in subs:
        if s["chat_id"] == chat_id:
            s["first_name"] = first_name
            s["username"] = username
            save_subscribers(subs)
            return

    subs.append({
        "chat_id": chat_id,
        "first_name": first_name,
        "username": username,
        "created_at": datetime.now().isoformat()
    })
    save_subscribers(subs)


def get_all_subscribers():
    return load_subscribers()


def stats_text():
    subs = load_subscribers()
    total = len(subs)
    lines = [f"📊 *Subscribers:* {total}"]
    for s in subs[:50]:  # বেশি হলে শুধু প্রথম ৫০ জন দেখাব
        uname = f"@{s['username']}" if s.get("username") else ""
        lines.append(f"- `{s['chat_id']}` {s.get('first_name','')} {uname}")
    if total > 50:
        lines.append(f"...(+{total-50} more)")
    return "\n".join(lines)


# ------------ MESSAGE FORMAT ------------

def format_usd_message(current, last, high, high_time, low, low_time):
    now_str = datetime.now().strftime('%d %b %I:%M %p')

    stats_lines = ""
    if high is not None and low is not None:
        stats_lines += f"\n\n🏆 শেষ ২৪ ঘন্টার সর্বোচ্চ: *{high:.2f}* BDT"
        if high_time:
            stats_lines += f"\n⏱ সময়: {high_time.strftime('%d %b %I:%M %p')}"
        stats_lines += f"\n📉 শেষ ২৪ ঘন্টার সর্বনিম্ন: *{low:.2f}* BDT"
        if low_time:
            stats_lines += f"\n🕒 সময়: {low_time.strftime('%d %b %I:%M %p')}"

    if last is None:
        msg = (
            "📢 **USD/BDT রেট আপডেট!**\n\n"
            f"🟩 বর্তমান রেট: *{current:.2f}* BDT\n"
            f"📆 আপডেট: {now_str}"
            f"{stats_lines}"
        )
    else:
        diff = current - last
        msg = (
            "📢 **USD/BDT রেট পরিবর্তন হয়েছে!**\n\n"
            f"🟩 নতুন রেট: *{current:.2f}* BDT\n"
            f"📊 পুরোনো রেট: *{last:.2f}* BDT\n"
            f"📈 পরিবর্তন: *{diff:+.2f}*\n"
            f"📆 আপডেট: {now_str}"
            f"{stats_lines}"
        )
    return msg


def format_pair_message(base, quote, rate, api_pair, inverted):
    """
    /rate usd/try টাইপ কমান্ডের জন্য generic message
    """
    now_str = datetime.now().strftime('%d %b %I:%M %p')
    base = base.upper()
    quote = quote.upper()
    line = (
        "💱 *Exchange Rate*\n\n"
        f"Pair: *{base}/{quote}*\n"
        f"Price: *1 {base} = {rate:.4f} {quote}*\n"
        f"📆 সময়: {now_str}\n"
        f"Source pair: `{api_pair}`"
    )
    if inverted:
        line += "\n(🔁 API থেকে inverse করে গণনা করা হয়েছে)"
    return line


# ------------ TIMING (slot) ------------

def sleep_until_next_slot():
    now = datetime.now()
    slots = [1, 16, 31, 46]

    target = None
    for m in slots:
        if now.minute < m or (now.minute == m and now.second < 1):
            target = now.replace(minute=m, second=0, microsecond=0)
            break

    if target is None:
        target = (now + timedelta(hours=1)).replace(minute=1, second=0, microsecond=0)

    delta = (target - now).total_seconds()
    print(f"[AUTO] Sleeping {int(delta)} seconds until {target}")
    if delta > 0:
        time.sleep(delta)


# ------------ TELEGRAM UPDATES / COMMANDS ------------

def get_updates(offset=None):
    params = {}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(f"{TELEGRAM_API_BASE}/getUpdates", params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data.get("result", [])


def parse_rate_command(text: str):
    """
    /rate         -> ('USD','BDT')
    /rate usd/bdt -> ('USD','BDT')
    /rate usd bdt -> ('USD','BDT')
    """
    parts = text.split()
    if len(parts) == 1:
        return "USD", "BDT"

    arg = parts[1].strip().lower()
    if "/" in arg:
        b, q = arg.split("/", 1)
        return b.strip().upper(), q.strip().upper()

    if len(parts) >= 3:
        return parts[1].upper(), parts[2].upper()

    # fallback
    return "USD", "BDT"


def command_loop():
    print("[CMD] Command loop started")
    last_update_id = None

    while True:
        try:
            offset = last_update_id + 1 if last_update_id is not None else None
            updates = get_updates(offset)

            for upd in updates:
                last_update_id = upd["update_id"]
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue

                chat = msg["chat"]
                chat_id = chat["id"]
                text = msg.get("text", "").strip()

                first_name = chat.get("first_name", "")
                username = chat.get("username")

                # সাবস্ক্রাইবার লিস্ট আপডেট (সবার জন্য open)
                add_or_update_subscriber(chat_id, first_name, username)

                # Admin stats
                if chat_id == ADMIN_ID and text.startswith("/stats"):
                    tg_send(chat_id, stats_text())
                    continue

                # Rate commands
                lower = text.lower()
                if lower.startswith("/rate") or lower in ("rate", "/usd", "usd"):
                    base, quote = parse_rate_command(text)
                    try:
                        rate, api_pair, inverted = get_pair_rate(base, quote)
                        # যদি USD/BDT হয়, extra stats
                        if base.upper() == "USD" and quote.upper() == "BDT":
                            history = update_history(rate)
                            high, high_time, low, low_time = get_stats_last_24h(history)
                            reply = format_usd_message(rate, None, high, high_time, low, low_time)
                        else:
                            reply = format_pair_message(base, quote, rate, api_pair, inverted)
                        tg_send(chat_id, reply)
                    except Exception as e:
                        print("[CMD] rate error:", e)
                        tg_send(
                            chat_id,
                            "❌ এই pair টা পাওয়া যায়নি। যেমন: `/rate usd/bdt`",
                            parse_mode="Markdown",
                        )
                    continue

                # /start message
                if text.startswith("/start"):
                    tg_send(
                        chat_id,
                        "👋 স্বাগতম!\n\n"
                        "➤ `/rate` → USD/BDT রেট\n"
                        "➤ `/rate usd/try` → অন্য currency pair\n"
                        "➤ যেকোনো প্রশ্নে শুধু `/rate` লিখে পাঠাতে পারো।",
                    )
                elif text.startswith("/"):
                    tg_send(
                        chat_id,
                        "Commands:\n"
                        "`/rate` – USD/BDT রেট\n"
                        "`/rate usd/try` – যেকোনো pair\n",
                        parse_mode="Markdown",
                    )

        except Exception as e:
            print("[CMD] Error:", e)

        time.sleep(5)


# ------------ AUTO SLOT LOOP (USD/BDT alert) ------------

def auto_loop():
    last_rate = None
    print("[AUTO] Auto loop started")

    while True:
        sleep_until_next_slot()

        try:
            rate = get_usd_bdt_rate()
            print("[AUTO] Current USD/BDT:", rate)

            history = update_history(rate)
            high, high_time, low, low_time = get_stats_last_24h(history)
            text = format_usd_message(rate, last_rate, high, high_time, low, low_time)

            subs = get_all_subscribers()
            if last_rate is None or rate != last_rate:
                for s in subs:
                    tg_send(s["chat_id"], text)

            last_rate = rate

        except Exception as e:
            print("[AUTO] Error:", e)


# ------------ MAIN ------------

if __name__ == "__main__":
    t = Thread(target=auto_loop, daemon=True)
    t.start()
    command_loop()
