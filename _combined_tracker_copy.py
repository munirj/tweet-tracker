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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=0)
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()
        page.goto("https://pro.x.com/i/decks/1915696383484371263", timeout=60000)
        time.sleep(5)

        print("[INFO] Combined tracker started. Scanning for new tweets...")

        capture_min_spacing = 60
        scroll_time = 10

        while True: 
            loop_start = datetime.now(timezone.utc)

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

            print("[PASS] Scrolling to update engagement metrics...")
            known_updates = {t["tweet_id"]: t for t in get_tweets_to_update(limit=500)}
            updated = 0
            skipped = 0
            forced = 0
            not_seen = set(known_updates)

            scroll_start = datetime.now(timezone.utc)
            # specify number of scroll passes to do on repeat
            for scroll_pass in range(100):
                articles = page.locator("article")
                for i in range(articles.count()):
                    if (datetime.now(timezone.utc) - scroll_start).total_seconds() >= (capture_min_spacing + scroll_time):
                        break
                    try:
                        article = articles.nth(i)
                        tweet_id = extract_tweet_id(article)
                        if not tweet_id or tweet_id not in known_updates:
                            continue

                        now = datetime.now(timezone.utc)
                        last_updated = datetime.fromisoformat(recent_updates.get(tweet_id, "1970-01-01T00:00:00"))
                        if last_updated.tzinfo is None:
                            last_updated = last_updated.replace(tzinfo=timezone.utc)
                        time_since = (now - last_updated).total_seconds()

                        # skip if last update was less than min spacing seconds ago
                        if time_since < capture_min_spacing:
                            update_attempts[tweet_id] = update_attempts.get(tweet_id, 0) + 1
                            if update_attempts[tweet_id] < 2:
                                skipped += 1
                                continue
                            elif time_since >= capture_min_spacing:
                                print(f"[FORCE] Updating {tweet_id} after multiple skips")
                                forced += 1
                                update_attempts[tweet_id] = 0
                            else:
                                skipped += 1
                                continue
                        else:
                            update_attempts[tweet_id] = 0

                        metrics = extract_metrics(article)
                        update_tweet_metrics(tweet_id, metrics)
                        recent_updates[tweet_id] = now.isoformat()
                        updated += 1
                        not_seen.discard(tweet_id)
                    except Exception as e:
                        print(f"[ERROR] Failed to update tweet #{i}: {e}")

                # if get over specified seconds, restart the loop to enable new tweets to be added to db
                if (datetime.now(timezone.utc) - scroll_start).total_seconds() >= (capture_min_spacing + scroll_time):
                    break

                try:
                    scroll_offset = 1000 
                    page.mouse.wheel(0, scroll_offset)
                except:
                    pass
                time.sleep(0.3)

            print(f"[SUMMARY] Cycle complete: {len(new_tweets)} new, {updated} updated, {skipped} skipped, {forced} forced, {len(not_seen)} not seen.")
            save_recent_updates(recent_updates)

            # print("[WAIT] Pausing before next cycle...")
            # time.sleep(max(0, 60 - (datetime.now(timezone.utc) - loop_start).total_seconds()))

if __name__ == "__main__":
    combined_tracker()