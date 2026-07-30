import os
import json
import time
import threading
import logging
from datetime import datetime

import requests
from flask import Flask
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

# --- Toc do quet: chinh o day neu can ---
# Thoi gian nghi giua 2 vong quet day du (tat ca tu khoa)
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", "300"))  # 5 phut
# Thoi gian nghi giua tung tu khoa trong 1 vong quet
DELAY_BETWEEN_KEYWORDS_SECONDS = int(os.environ.get("DELAY_BETWEEN_KEYWORDS_SECONDS", "8"))

SEEN_IDS_FILE = os.environ.get("SEEN_IDS_FILE", "seen_ids.json")
ITEMS_FILE = os.environ.get("ITEMS_FILE", "found_items.json")
MAX_ITEMS_KEPT = 300

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mercari_dashboard")

app = Flask(__name__)

_lock = threading.Lock()
_seen_ids = set()          # tat ca ID da tung thay (de khong bao lai)
_items_by_id = {}          # chi chua hang MOI THAT SU (hien thi len web)


def load_state():
    global _seen_ids, _items_by_id
    if os.path.exists(SEEN_IDS_FILE):
        try:
            with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
                _seen_ids = set(json.load(f))
        except Exception:
            _seen_ids = set()
    if os.path.exists(ITEMS_FILE):
        try:
            with open(ITEMS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _items_by_id = {i["id"]: i for i in data}
        except Exception:
            _items_by_id = {}


def save_seen_ids():
    with _lock:
        ids_list = list(_seen_ids)[-10000:]
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(ids_list, f)


def save_items():
    with _lock:
        items = sorted(_items_by_id.values(), key=lambda x: x["found_at"], reverse=True)
        items = items[:MAX_ITEMS_KEPT]
    with open(ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)


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
    captured_json = []

    def handle_response(response):
        try:
            ctype = response.headers.get("content-type", "")
            if "application/json" in ctype and response.status == 200:
                captured_json.append(response.json())
        except Exception:
            pass

    page.on("response", handle_response)
    # sort=created_time&order=desc -> sap xep theo "moi nhat" (Mercari that su),
    # thay vi mac dinh "de xuat" (co the tron hang cu duoc day len do quang cao PR)
    url = (
        f"https://jp.mercari.com/search?keyword={requests.utils.quote(keyword)}"
        f"&status=on_sale&sort=created_time&order=desc"
    )
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as e:
        log.error("Loi khi mo trang cho tu khoa '%s': %s", keyword, e)
        page.remove_listener("response", handle_response)
        return []
    page.remove_listener("response", handle_response)

    all_items = []
    for blob in captured_json:
        all_items.extend(find_items_recursive(blob))

    unique = {}
    for item in all_items:
        unique[item["id"]] = item
    return list(unique.values())


def background_scanner():
    global _seen_ids, _items_by_id
    load_state()

    is_first_run = len(_seen_ids) == 0
    if is_first_run:
        log.info("Lan chay dau tien - se chi ghi nho hang hien co, KHONG hien len trang web.")
    else:
        log.info("Da co %d ID trong lich su, %d item dang hien thi.", len(_seen_ids), len(_items_by_id))

    log.info(
        "Bat dau quet nen - %d tu khoa, nghi %ds/tu khoa, %ds/vong.",
        len(KEYWORDS), DELAY_BETWEEN_KEYWORDS_SECONDS, SCAN_INTERVAL_SECONDS,
    )

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

        first_pass = is_first_run

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

                now = datetime.now().isoformat()
                truly_new_count = 0
                with _lock:
                    for item in items:
                        item_id = str(item.get("id"))
                        if item_id in _seen_ids:
                            continue
                        _seen_ids.add(item_id)
                        if not first_pass:
                            _items_by_id[item_id] = {
                                "id": item_id,
                                "name": item.get("name", "(khong co ten)"),
                                "price": item.get("price", "?"),
                                "keyword": keyword,
                                "found_at": now,
                                "url": f"https://jp.mercari.com/item/{item_id}",
                            }
                            truly_new_count += 1

                save_seen_ids()
                if truly_new_count > 0:
                    save_items()
                    log.info("-> %d hang MOI THAT SU vua duoc them vao trang web.", truly_new_count)

                time.sleep(DELAY_BETWEEN_KEYWORDS_SECONDS)

            if first_pass:
                log.info("Da hoan tat vong ghi nho dau tien. Tu vong sau se hien hang moi that su len web.")
                first_pass = False

            log.info(
                "Hoan tat 1 vong quet luc %s - cho %ds truoc vong sau.",
                datetime.now().strftime("%H:%M:%S"),
                SCAN_INTERVAL_SECONDS,
            )
            time.sleep(SCAN_INTERVAL_SECONDS)


PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>Mercari - Hang moi</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #111; color: #eee; margin: 0; padding: 16px; }}
  h1 {{ font-size: 18px; }}
  .empty {{ color: #888; margin-top: 20px; }}
  .item {{ display: flex; justify-content: space-between; align-items: center;
          background: #1c1c1c; border-radius: 10px; padding: 12px 16px; margin-bottom: 8px; }}
  .item a {{ color: #7ab8ff; text-decoration: none; font-weight: 600; }}
  .meta {{ font-size: 12px; color: #999; margin-top: 4px; }}
  .price {{ font-weight: 700; color: #ffd166; white-space: nowrap; margin-left: 12px; }}
</style>
</head>
<body>
<h1>Hang moi tren Mercari ({count} san pham)</h1>
{rows}
</body>
</html>
"""

ROW_TEMPLATE = """
<div class="item">
  <div>
    <a href="{url}" target="_blank">{name}</a>
    <div class="meta">{keyword} &middot; phat hien luc {found_at}</div>
  </div>
  <div class="price">{price} yen</div>
</div>
"""


@app.route("/")
def index():
    with _lock:
        items = sorted(_items_by_id.values(), key=lambda x: x["found_at"], reverse=True)
    if not items:
        rows = '<div class="empty">Chua co hang moi nao duoc phat hien. Trang se tu lam moi moi 30 giay.</div>'
    else:
        rows = "".join(
            ROW_TEMPLATE.format(
                url=i["url"],
                name=i["name"],
                keyword=i["keyword"],
                found_at=i["found_at"][:19].replace("T", " "),
                price=i["price"],
            )
            for i in items[:200]
        )
    return PAGE_TEMPLATE.format(count=len(items), rows=rows)


if __name__ == "__main__":
    t = threading.Thread(target=background_scanner, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
