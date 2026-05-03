


import time
import random
import re
import logging
from datetime import datetime

from bs4 import BeautifulSoup
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# MongoDB — flipkart_products collection

client = MongoClient("mongodb://localhost:27017/")
db = client["buygenix"]
collection = db["flipkart_products"]  # for different collection from amazon



# Selenium Driver

def get_driver():
    import undetected_chromedriver as uc
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Passing version_main=147 to match the current browser version
    driver = uc.Chrome(options=options, version_main=147)
    driver.set_page_load_timeout(30)
    return driver

# Parse single card — verified selectors

def _parse_card(card):
    product_id = card.get("data-id", "")

    url = None
    link_el = card.select_one("a.k7wcnx")
    if link_el:
        href = link_el.get("href", "")
        url = f"https://www.flipkart.com{href}" if href.startswith("/") else href

    title = None
    img_el = card.select_one("img.UCc1lI")
    if img_el:
        title = img_el.get("alt", "").strip()
        if title.endswith("..."):
            title = title[:-3].strip()
    if not title or len(title) < 5:
        return None

    image_url = img_el.get("src", "") if img_el else None

    price = None
    price_el = card.select_one("div.hZ3P6w.DeU9vF")
    if price_el:
        cleaned = re.sub(r"[₹,\s]", "", price_el.get_text(strip=True))
        try:
            price = float(cleaned)
        except ValueError:
            pass

    if not price:
        for sel in ["div.oFEPlD", "div.QiMO5r"]:
            el = card.select_one(sel)
            if el:
                match = re.search(r"₹([\d,]+)", el.get_text(strip=True))
                if match:
                    try:
                        price = float(match.group(1).replace(",", ""))
                        break
                    except ValueError:
                        continue

    rating = None
    for el in card.find_all("div"):
        text = el.get_text(strip=True)
        if re.fullmatch(r"[1-5]\.[0-9]", text):
            try:
                rating = float(text)
                break
            except ValueError:
                continue

    reviews = None
    for el in card.find_all(["span", "div"]):
        text = el.get_text(strip=True)
        match = re.search(r"([\d,]+)\s*(Ratings?|Reviews?)", text, re.IGNORECASE)
        if match:
            try:
                reviews = int(match.group(1).replace(",", ""))
                break
            except ValueError:
                continue

    return {
        "title": title,
        "price": price,
        "rating": rating,
        "reviews": reviews,
        "url": url,
        "image": image_url,
        "product_id": product_id,
        "platform": "flipkart",
    }



# Search

def search_flipkart(query, max_results=10):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    logger.info(f"[Flipkart] Starting browser for: '{query}'")
    driver = get_driver()

    try:
        driver.get("https://www.flipkart.com")
        time.sleep(random.uniform(2, 3))

        try:
            close_btn = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'✕')]"))
            )
            close_btn.click()
            time.sleep(1)
        except Exception:
            pass

        search_url = f"https://www.flipkart.com/search?q={query.replace(' ', '+')}&marketplace=FLIPKART"
        driver.get(search_url)
        time.sleep(random.uniform(3, 4))

        driver.execute_script("window.scrollTo(0, 600)")
        time.sleep(1.5)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-id]"))
        )

        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.select("div[data-id]")
        logger.info(f"[Flipkart] Found {len(cards)} cards")

        products = []
        for card in cards:
            if len(products) >= max_results:
                break
            try:
                product = _parse_card(card)
                if product and product.get("price"):
                    products.append(product)
            except Exception as e:
                logger.debug(f"Card parse error: {e}")
                continue

        logger.info(f"[Flipkart] Parsed {len(products)} products")
        return products

    except Exception as e:
        logger.error(f"[Flipkart] Scrape failed: {e}")
        return []

    finally:
        try:
            driver.quit()
        except Exception:
            pass



# MongoDB Save — flipkart_products collection

def save_to_mongodb(products, query):
    saved_count = 0
    timestamp = datetime.utcnow()

    for product in products:
        if not product.get("price"):
            continue

        product_id = product.get("product_id")
        filter_query = (
            {"product_id": product_id}
            if product_id
            else {"title": product["title"]}
        )

        collection.update_one(
            filter_query,
            {
                "$set": {
                    "title": product["title"],
                    "current_price": product["price"],
                    "rating": product.get("rating"),
                    "reviews": product.get("reviews"),
                    "url": product.get("url"),
                    "image": product.get("image"),
                    "product_id": product_id,
                    "platform": "flipkart",
                    "search_query": query,
                    "last_updated": timestamp,
                },
                "$push": {
                    "price_history": {
                        "price": product["price"],
                        "timestamp": timestamp,
                    }
                },
                "$setOnInsert": {"created_at": timestamp},
            },
            upsert=True,
        )
        saved_count += 1

    logger.info(f"[MongoDB] flipkart_products — saved {saved_count} for '{query}'")
    return saved_count



# Main

def scrape_flipkart(query, max_results=10):
    logger.info(f"[Flipkart Scraper] Starting: '{query}'")
    products = search_flipkart(query, max_results)

    if not products:
        logger.warning(f"[Flipkart] No products found for: '{query}'")
        return 0

    count = save_to_mongodb(products, query)
    logger.info(f"[Flipkart Scraper] Done — {count} saved to flipkart_products.")
    return count


if __name__ == "__main__":
    scrape_flipkart("laptop", max_results=10)