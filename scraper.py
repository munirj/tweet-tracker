from playwright.sync_api import sync_playwright
from config import SESSION_FILE
from db import insert_new_tweets
from datetime import datetime, timezone
import time

def extract_tweet_id(article):
    try:
        links = article.locator("a")
        hrefs = [links.nth(j).get_attribute("href") for j in range(links.count())]
        status_links = [href for href in hrefs if href and "/status/" in href]
        if status_links:
            tweet_url = status_links[0]
            return tweet_url.split("/")[-1]
    except:
        pass
    return None

def extract_tweet_text(article):
    try:
        text_blocks = article.locator("div[lang]").all_inner_texts()
        return " ".join(text_blocks).strip()
    except:
        return ""

def extract_user_handle(article):
    try:
        handle_elem = article.locator("a[role='link'] span").first
        return handle_elem.inner_text() if handle_elem else "unknown"
    except:
        return "unknown"

def scraper_live_capture():
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=0)
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()
        page.goto("https://pro.x.com/i/decks/1915696383484371263", timeout=60000)
        time.sleep(5)

        print("[SCRAPER] Live tweet capture started.")

        while True:
            articles = page.locator("article")
            count = articles.count()
            new_tweets = []

            for i in range(count):
                try:
                    article = articles.nth(i)
                    tweet_id = extract_tweet_id(article)
                    if not tweet_id or tweet_id in seen_ids:
                        continue

                    seen_ids.add(tweet_id)

                    tweet_text = extract_tweet_text(article)
                    user_handle = extract_user_handle(article)

                    tweet = {
                        "id": tweet_id,
                        "user": user_handle,
                        "text": tweet_text,
                    }
                    new_tweets.append(tweet)

                except Exception as e:
                    print(f"[SCRAPER WARN] Error at #{i}: {e}")

            if new_tweets:
                print(f"[SCRAPER] Logging {len(new_tweets)} new tweets")
                insert_new_tweets(new_tweets)

            time.sleep(1)  # Small wait before checking again

if __name__ == "__main__":
    scraper_live_capture()
