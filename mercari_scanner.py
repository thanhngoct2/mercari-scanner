import os
import json
import time
import logging
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

KEYWORDS = [
    "シャネル トップス",
    "CHANEL トップス",
    "シャネル ブラウス",
    "シャネル カットソー",
    "チャネル デニム",
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

SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", "180"))
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SEEN_ITEMS_FILE = os.environ.get("SEEN_ITEMS_FILE", "seen_items.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mercari_scanner")

_debug_done = False


def load_seen_items():
    if os.path.exists(SEEN_ITEMS_FILE):
        try:
            with open(SEEN_ITEMS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_seen_items(seen_ids):
    ids_list = list(seen_ids)[-5000:]
    with open(SEEN_ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(ids_list, f)


def find_items_recursive(node, found=None):
    if found is None:
        found = []
    if isinstance(node, dict):
        if {"id", "name", "price"}.issubset(node.keys()):
            found.append(node)
        else:
            for value in node.values():
                find_items_recursive(value, found)
    elif isinstance(node, list):
        for value in node:
            find_items_recursive(value, found)
    return found


def scan_keyword_with_browser(page, keyword: str) -> list:
    global _debug_done
    captured_json = []

    def handle_response(response):
        try:
            ctype = response.headers.get("content-type", "")
            if "application/json" in ctype and response.status == 200:
                body = response.json()
                captured_json.append(body)
        except Exception:
            pass

    page.on("response", handle_response)

    url = f"https://jp.mercari.com/search?keyword={requests.utils.quote(keyword)}&status=on_sale"
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as e:
        log.error("Loi khi mo trang cho tu khoa '%s': %s", keyword, e)
        page.remove_listener("response", handle_response)
        return []

    page.remove_listener("response", handle_response)

    if not _debug_done:
        _debug_done = True
        log.info("[DEBUG] So goi JSON bat duoc: %d", len(captured_json))

    all_items = []
    for blob in captured_json:
        all_items.extend(find_items_recursive(blob))

    unique = {}
    for item in all_items:
        unique[item["id"]] = item
    return list(unique.values())


def send_telegram_message(text: str):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            api_url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            log.error("Gui Telegram that bai: %s", resp.text)
    except requests.RequestException as e:
        log.error("Loi ket noi Telegram: %s", e)


def format_item_message(item: dict, keyword: str) -> str:
    item_id = item.get("id", "")
    name = item.get("name", "(khong co ten)")
    price = item.get("price", "?")
    item_url = f"https://jp.mercari.com/item/{item_id}"
    return f"Hang moi: {keyword}\n{name}\nGia: {price} yen\n{item_url}"


def main():
    log.info("Bat dau mercari_scanner (che do trinh duyet ao) - tu khoa: %s", KEYWORDS)
    seen_ids = load_seen_items()
    log.info("Da co %d item trong lich su.", len(seen_ids))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = context.new_page()

        while True:
            for keyword in KEYWORDS:
                keyword = keyword.strip()
                if not keyword:
                    continue
                try:
                    items = scan_keyword_with_browser(page, keyword)
                except Exception as e:
                    log.error("Loi khong xac dinh voi tu khoa '%s': %s", keyword, e)
                    items = []

                log.info("Tu khoa '%s': tim thay %d item.", keyword, len(items))

                new_items = [i for i in items if str(i.get("id")) not in seen_ids]
                for item in new_items:
                    item_id = str(item.get("id"))
                    seen_ids.add(item_id)
                    send_telegram_message(format_item_message(item, keyword))
                    log.info("Da bao hang moi: %s (%s)", item.get("name"), item_id)
                if new_items:
                    save_seen_items(seen_ids)

                time.sleep(3)

            log.info(
                "Hoan tat 1 vong quet luc %s - cho %ds.",
                datetime.now().strftime("%H:%M:%S"),
                SCAN_INTERVAL_SECONDS,
            )
            time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
