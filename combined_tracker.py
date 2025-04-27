from playwright.sync_api import sync_playwright
from config import SESSION_FILE
from db import insert_new_tweets, get_tweets_to_update, update_tweet_metrics
from datetime import datetime, timedelta, timezone
import time
import json
import os

def extract_metric_from_label(article, label_text):
    try:
        span = article.locator(f"[aria-label*='{label_text}']")
        if span.count() > 0:
            label = span.first.get_attribute("aria-label")
            number = label.split(" ")[0].replace(",", "")
            if "K" in number:
                return int(float(number.replace("K", "")) * 1000)
            elif "M" in number:
                return int(float(number.replace("M", "")) * 1_000_000)
            return int(number)
    except:
        pass
    return 0

def extract_metrics(article):
    return {
        "replies": extract_metric_from_label(article, "Reply"),
        "retweets": extract_metric_from_label(article, "Repost"),
        "likes": extract_metric_from_label(article, "Like"),
        "views": extract_metric_from_label(article, "View"),
    }

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

def load_recent_updates(path="recent_updates.json"):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}

def save_recent_updates(data, path="recent_updates.json"):
    with open(path, "w") as f:
        json.dump(data, f)

def combined_tracker():
    seen_ids = set()
    recent_updates = load_recent_updates()
    update_attempts = {}

    # Configurable settings
    # below is every 63 seconds or so
    max_scroll_seconds = 50
    max_cycle_seconds = 65
    min_update_spacing_seconds = 50
    scroll_pause_seconds = 0.3
    scroll_offset_pixels = 1000


    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=0)
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()
        page.goto("https://pro.x.com/i/decks/1915696383484371263", timeout=60000)
        time.sleep(5)

        print("[INFO] Combined tracker started.")

        while True:
            cycle_start = datetime.now(timezone.utc)

            print("[PASS] Top scan: looking for new tweets")
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
                    print(f"[WARN] Top pass error at #{i}: {e}")

            if new_tweets:
                print(f"[INFO] Logging {len(new_tweets)} new tweets")
                insert_new_tweets(new_tweets)

            print("[PASS] Scrolling and updating engagement...")
            known_updates = {t["tweet_id"]: t for t in get_tweets_to_update(limit=500)}
            updated = 0

            scroll_start = datetime.now(timezone.utc)

            while (datetime.now(timezone.utc) - scroll_start).total_seconds() < max_scroll_seconds:
                page.mouse.wheel(0, scroll_offset_pixels)
                time.sleep(scroll_pause_seconds)

                articles = page.locator("article")
                for i in range(articles.count()):
                    try:
                        article = articles.nth(i)
                        tweet_id = extract_tweet_id(article)
                        if not tweet_id or tweet_id not in known_updates:
                            continue

                        now = datetime.now(timezone.utc)
                        last_updated = datetime.fromisoformat(recent_updates.get(tweet_id, "1970-01-01T00:00:00"))
                        if last_updated.tzinfo is None:
                            last_updated = last_updated.replace(tzinfo=timezone.utc)

                        if (now - last_updated).total_seconds() < min_update_spacing_seconds:
                            continue

                        metrics = extract_metrics(article)
                        update_tweet_metrics(tweet_id, metrics)
                        recent_updates[tweet_id] = now.isoformat()
                        updated += 1

                    except Exception as e:
                        print(f"[ERROR] Failed updating tweet #{i}: {e}")

                if updated >= len(known_updates):
                    print("[INFO] All known tweets updated early.")
                    break

            print(f"[SUMMARY] Cycle done: {updated} updated.")
            save_recent_updates(recent_updates)

            cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            if cycle_duration < max_cycle_seconds:
                sleep_time = max_cycle_seconds - cycle_duration - 1
                print(f"[WAIT] Sleeping {sleep_time:.1f}s to align cycles...")
                time.sleep(sleep_time)

if __name__ == "__main__":
    combined_tracker()
