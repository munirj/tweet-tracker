from playwright.sync_api import sync_playwright
from config import SESSION_FILE
from db import get_tweets_to_update, update_tweet_metrics
from datetime import datetime, timezone
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

def load_recent_updates(path="recent_updates.json"):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}

def save_recent_updates(data, path="recent_updates.json"):
    with open(path, "w") as f:
        json.dump(data, f)

def updater_engagement_tracker():
    recent_updates = load_recent_updates()

    # Config
    max_cycle_seconds = 65
    min_update_spacing_seconds = 50
    scroll_pause_seconds = 0.3
    scroll_offset_pixels = 1000

    last_summary = None
    skipped_same_summaries = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=0)
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()
        page.goto("https://pro.x.com/i/decks/1915696383484371263", timeout=60000)
        time.sleep(5)

        print("[UPDATER] Engagement tracker started.")

        while True:
            cycle_start = datetime.now(timezone.utc)

            known_updates = {t["tweet_id"]: t for t in get_tweets_to_update(limit=500)}
            tweets_to_update = set(known_updates.keys())
            updated = 0
            scroll_scans = 0

            while True:
                now = datetime.now(timezone.utc)
                elapsed = (now - cycle_start).total_seconds()

                if elapsed >= max_cycle_seconds:
                    print(f"[UPDATER] Max cycle time {max_cycle_seconds}s reached. Restarting top scan.")
                    break

                scroll_scans += 1

                page.mouse.wheel(0, scroll_offset_pixels)
                time.sleep(scroll_pause_seconds)

                articles = page.locator("article")
                for i in range(articles.count()):
                    try:
                        article = articles.nth(i)
                        tweet_id = extract_tweet_id(article)
                        if not tweet_id or tweet_id not in known_updates:
                            continue

                        last_updated = datetime.fromisoformat(recent_updates.get(tweet_id, "1970-01-01T00:00:00"))
                        if last_updated.tzinfo is None:
                            last_updated = last_updated.replace(tzinfo=timezone.utc)

                        if (now - last_updated).total_seconds() < min_update_spacing_seconds:
                            continue

                        metrics = extract_metrics(article)
                        update_tweet_metrics(tweet_id, metrics)
                        recent_updates[tweet_id] = now.isoformat()
                        updated += 1
                        tweets_to_update.discard(tweet_id)

                    except Exception as e:
                        print(f"[UPDATER ERROR] Failed updating #{i}: {e}")

                if not tweets_to_update:
                    break  # No need to print spam here anymore

            # Build summary including scroll_scans
            current_summary = f"[SUMMARY] Cycle finished: {updated} tweets updated, {len(tweets_to_update)} still pending, after {scroll_scans} scroll scans."

            if current_summary == last_summary:
                skipped_same_summaries += 1
            else:
                if skipped_same_summaries > 0:
                    print(f"[SKIPPED] {skipped_same_summaries} identical summary prints skipped.")
                    skipped_same_summaries = 0
                print(current_summary)
                last_summary = current_summary

            save_recent_updates(recent_updates)

if __name__ == "__main__":
    updater_engagement_tracker()
