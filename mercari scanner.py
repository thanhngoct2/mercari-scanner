"""
Mercari JP Scanner
==================
Tự động quét Mercari Nhật và gửi thông báo về Telegram + Discord
khi có listing mới khớp với từ khóa của bạn.

Tác giả: Claude (Anthropic)
"""

import requests
import time
import json
import os

# ============================================================
# ⚙️  CÀI ĐẶT CỦA BẠN — Chỉnh sửa phần này trước khi chạy
# ============================================================

# --- Từ khóa tìm kiếm (tiếng Nhật hoặc tiếng Anh) ---
KEYWORDS = [
   "シャネル トップス",
    "CHANEL トップス",
    "シャネル ブラウス",
    "シャネル カットソー",
    "チャネル　デニム",
    "CHANEL ジャケット",
    "CHANEL テーラージャケット",
　　"CHANEL ニットセーター",
　　"CHANEL シャツ",
　　"CHANEL 半袖",
　　"CHANEL セットアップ",
　　"CHANEL ワンピース",
　　"DIOR トップス",
　　"DIOR ブラウス",
 　 "DIOR シャツ",
    "DIOR ニットセーター",
　　"DIOR ワンピース",

]

# --- Lọc giá (đơn vị: Yên Nhật). Đặt 0 để bỏ qua ---
MIN_PRICE = 0       # Ví dụ: 1000
MAX_PRICE = 0       # Ví dụ: 50000

# --- Tốc độ quét (giây). Tối thiểu 30 để tránh bị block ---
SCAN_INTERVAL = 5

# --- Telegram ---
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = "8502880381:AAFJ7L9Ijd40fqPzJd7P2DXZSwkXbKhuSXc"   # Xem hướng dẫn bên dưới
TELEGRAM_CHAT_ID   = "7489860569"      # Xem hướng dẫn bên dưới

# --- Discord ---
DISCORD_ENABLED = True
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1514093408094781450/wzNAcLlZFJ2f8mLNLFGxFDfEjv8XSHW3lo8_GB980k-Xcf7ePJmO0XEFovHk5idOGOYN"  # Xem hướng dẫn bên dưới

# ============================================================
# 🔧  PHẦN KỸ THUẬT — Không cần chỉnh sửa
# ============================================================

SEEN_IDS_FILE = "seen_ids.json"
MERCARI_API   = "https://api.mercari.jp/v2/entities:search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "X-Platform": "web",
    "DPoP": "dummy",
}


def load_seen_ids():
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(seen_ids):
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(list(seen_ids), f)


def search_mercari(keyword):
    payload = {
        "pageSize": 30,
        "pageToken": "",
        "searchSessionId": "scanner",
        "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
        "thumbnailTypes": [],
        "searchCondition": {
            "keyword": keyword,
            "excludeKeyword": "",
            "sort": "SORT_CREATED_TIME",
            "order": "ORDER_DESC",
            "status": ["STATUS_ON_SALE"],
            "sizeId": [],
            "categoryId": [],
            "brandId": [],
            "sellerId": [],
            "priceMin": MIN_PRICE if MIN_PRICE > 0 else 0,
            "priceMax": MAX_PRICE if MAX_PRICE > 0 else 0,
            "itemConditionId": [],
            "shippingPayerId": [],
            "shippingFromArea": [],
            "shippingMethod": [],
            "colorId": [],
            "hasCoupon": False,
            "attributes": [],
            "itemTypes": [],
            "skuIds": [],
        },
        "userId": "",
        "pageInfo": {"page": 0, "limit": 30},
    }
    try:
        r = requests.post(MERCARI_API, headers=HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("items", [])
    except Exception as e:
        print(f"  [Lỗi khi tìm '{keyword}'] {e}")
        return []


def send_telegram(item):
    if not TELEGRAM_ENABLED:
        return
    name  = item.get("name", "Không rõ tên")
    price = item.get("price", "?")
    item_id = item.get("id", "")
    url   = f"https://jp.mercari.com/item/{item_id}"
    img   = (item.get("thumbnails") or [""])[0]

    text = (
        f"🛍️ *Listing mới trên Mercari JP!*\n\n"
        f"📦 *{name}*\n"
        f"💴 ¥{price:,}\n"
        f"🔗 [Xem sản phẩm]({url})"
    )
    try:
        if img:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID, "photo": img,
                      "caption": text, "parse_mode": "Markdown"},
                timeout=10,
            )
        else:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                      "parse_mode": "Markdown"},
                timeout=10,
            )
    except Exception as e:
        print(f"  [Lỗi Telegram] {e}")


def send_discord(item):
    if not DISCORD_ENABLED:
        return
    name  = item.get("name", "Không rõ tên")
    price = item.get("price", "?")
    item_id = item.get("id", "")
    url   = f"https://jp.mercari.com/item/{item_id}"
    img   = (item.get("thumbnails") or [""])[0]

    embed = {
        "title": f"🛍️ {name}",
        "url": url,
        "color": 0xFF4F00,
        "fields": [
            {"name": "Giá", "value": f"¥{price:,}", "inline": True},
            {"name": "Link", "value": f"[Mở Mercari JP]({url})", "inline": True},
        ],
        "footer": {"text": "Mercari JP Scanner"},
    }
    if img:
        embed["thumbnail"] = {"url": img}

    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={"embeds": [embed]},
            timeout=10,
        )
    except Exception as e:
        print(f"  [Lỗi Discord] {e}")


def main():
    print("=" * 50)
    print("  🔍 Mercari JP Scanner đang chạy...")
    print(f"  Từ khóa: {', '.join(KEYWORDS)}")
    print(f"  Quét mỗi: {SCAN_INTERVAL} giây")
    if MIN_PRICE or MAX_PRICE:
        print(f"  Giá: ¥{MIN_PRICE:,} ~ ¥{MAX_PRICE:,}")
    print("  Nhấn Ctrl+C để dừng")
    print("=" * 50)

    seen_ids = load_seen_ids()
    first_run = len(seen_ids) == 0

    while True:
        for keyword in KEYWORDS:
            print(f"\n[{time.strftime('%H:%M:%S')}] Đang quét: '{keyword}'")
            items = search_mercari(keyword)
            new_count = 0

            for item in items:
                item_id = item.get("id", "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                if first_run:
                    continue  # Lần đầu chỉ lưu, không gửi thông báo
                new_count += 1
                name  = item.get("name", "?")
                price = item.get("price", "?")
                print(f"  ✅ Mới: {name} — ¥{price:,}")
                send_telegram(item)
                send_discord(item)
                time.sleep(1)

            if first_run:
                print(f"  ℹ️  Lần đầu chạy: đã lưu {len(items)} sản phẩm hiện có.")
            elif new_count == 0:
                print("  Không có listing mới.")

        save_seen_ids(seen_ids)
        first_run = False
        print(f"\n⏳ Chờ {SCAN_INTERVAL} giây...")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
