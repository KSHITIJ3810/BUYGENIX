

import time
import random
import re
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# MongoDB — amazon_products collection

client = MongoClient("mongodb://localhost:27017/")
db = client["buygenix"]
collection = db["amazon_products"]  # different - from flipkart collection


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



# Parse single card

def _parse_amazon_card(card):
    # Title
    title = None
    title_el = card.select_one("h2 span")
    if title_el:
        title = title_el.get_text(strip=True)
    if not title or len(title) < 5:
        return None

    # ASIN + URL
    asin = card.get("data-asin", "")
    url = None
    link_el = card.select_one("a.a-link-normal[href*='/dp/']")
    if link_el:
        href = link_el.get("href", "")
        url = f"https://www.amazon.in{href}" if href.startswith("/") else href

    # Price — skip MRP, take first valid price
    price = None
    for span in card.select("span.a-offscreen"):
        text = span.get_text(strip=True)
        if "M.R.P" in text or "mrp" in text.lower():
            continue
        cleaned = re.sub(r"[₹,\s]", "", text)
        try:
            price = float(cleaned)
            break
        except ValueError:
            continue

    # Rating
    rating = None
    rating_el = card.select_one("span.a-icon-alt")
    if rating_el:
        match = re.search(r"(\d+\.?\d*)", rating_el.get_text(strip=True))
        if match:
            rating = float(match.group(1))

    # Reviews
    reviews = None
    reviews_el = card.select_one("span.a-size-base.s-underline-text")
    if reviews_el:
        text = re.sub(r"[,\s]", "", reviews_el.get_text(strip=True))
        try:
            reviews = int(text)
        except ValueError:
            pass

    # Image
    image_url = None
    img_el = card.select_one("img.s-image")
    if img_el:
        image_url = img_el.get("src", "")

    return {
        "title": title,
        "price": price,
        "rating": rating,
        "reviews": reviews,
        "url": url,
        "image": image_url,
        "asin": asin,
        "platform": "amazon",
    }



# Search

def search_amazon(query, max_results=10):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    search_url = f"https://www.amazon.in/s?k={query.replace(' ', '+')}&i=electronics"
    logger.info(f"[Amazon] Starting browser for: '{query}'")
    
    driver = get_driver()
    products = []
    
    try:
        driver.get(search_url)
        time.sleep(random.uniform(3, 5))
        
        # Scroll to load images/content
        driver.execute_script("window.scrollTo(0, 1000)")
        time.sleep(2)
        
        # Parse page
        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.select("div[data-component-type='s-search-result']")
        logger.info(f"[Amazon] Found {len(cards)} cards")

        for card in cards:
            if len(products) >= max_results:
                break
            try:
                product = _parse_amazon_card(card)
                if product:
                    products.append(product)
            except Exception as e:
                logger.debug(f"Card parse error: {e}")
                continue
                
    except Exception as e:
        logger.error(f"[Amazon] Scrape failed: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    logger.info(f"[Amazon] Parsed {len(products)} products")
    return products



# MongoDB Save — amazon_products collection

def save_to_mongodb(products, query):
    saved_count = 0
    timestamp = datetime.now(datetime.UTC) if hasattr(datetime, 'UTC') else datetime.utcnow()

    for product in products:
        if not product.get("price"):
            continue

        asin = product.get("asin")
        filter_query = (
            {"asin": asin}
            if asin
            else {"title": product["title"]}
        )

        collection.update_one(        # amazon_products collection
            filter_query,
            {
                "$set": {
                    "title": product["title"],
                    "current_price": product["price"],
                    "rating": product.get("rating"),
                    "reviews": product.get("reviews"),
                    "url": product.get("url"),
                    "image": product.get("image"),
                    "asin": asin,
                    "platform": "amazon",
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

    logger.info(f"[MongoDB] amazon_products — saved {saved_count} for '{query}'")
    return saved_count



# Main

def scrape_amazon(query, max_results=10):
    logger.info(f"[Amazon Scraper] Starting: '{query}'")
    products = search_amazon(query, max_results)

    if not products:
        logger.warning(f"[Amazon] No products found for: '{query}'")
        return 0

    count = save_to_mongodb(products, query)
    logger.info(f"[Amazon Scraper] Done — {count} saved to amazon_products.")
    return count


if __name__ == "__main__":
    scrape_amazon("laptop", max_results=10)