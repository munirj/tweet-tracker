from playwright.sync_api import sync_playwright
from config import SESSION_FILE
from db import get_tweets_to_update, update_tweet_metrics
from datetime import datetime, timezone
import time
import json
import os

# Extract a numeric metric (likes, views, etc.) from a tweet article's aria-label
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

# Extract all engagement metrics from a tweet article
def extract_metrics(article):
    return {
        "replies": extract_metric_from_label(article, "Reply"),
        "retweets": extract_metric_from_label(article, "Repost"),
        "likes": extract_metric_from_label(article, "Like"),
        "views": extract_metric_from_label(article, "View"),
    }

# Extract the tweet ID from an article's link
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

# Load recent update timestamps from disk to avoid redundant updates
def load_recent_updates(path="recent_updates.json"):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}

# Save recent update timestamps back to disk
def save_recent_updates(data, path="recent_updates.json"):
    with open(path, "w") as f:
        json.dump(data, f)

def get_tweet_time(article):
    """Extract timestamp from a tweet article"""
    try:
        time_element = article.locator('time').first
        if time_element.count() > 0:
            datetime_str = time_element.get_attribute('datetime')
            if datetime_str:
                if not datetime_str.endswith('Z') and not '+' in datetime_str:
                    datetime_str += '+00:00'
                return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
    except Exception:
        pass
    return None

def scroll_container(page, direction="down", amount=2000):
    """Scroll the main container in the specified direction with a specific amount."""
    return page.evaluate(f"""
        () => {{
            const containers = document.querySelectorAll('*');
            let maxHeight = 0;
            let maxContainer = null;
            
            for (const container of containers) {{
                const height = container.scrollHeight;
                if (height > maxHeight && height > 500) {{
                    maxHeight = height;
                    maxContainer = container;
                }}
            }}
            
            if (maxContainer) {{
                const currentScroll = maxContainer.scrollTop;
                maxContainer.scrollTop {'= 0' if direction == 'up' else f'+= {amount}'};
                return {{
                    scrolled: true,
                    previousPosition: currentScroll,
                    newPosition: maxContainer.scrollTop,
                    maxScroll: maxContainer.scrollHeight - maxContainer.clientHeight
                }};
            }}
            return {{ scrolled: false }};
        }}
    """)

# Main loop that tracks tweet engagement metrics over time
def updater_engagement_tracker():
    recent_updates = load_recent_updates()

    # Configurable timing parameters
    max_cycle_seconds = 55                # Max total time for each scroll/update cycle
    min_update_spacing_seconds = 50       # Minimum spacing between updates for each tweet

    last_summary = None
    skipped_same_summaries = 0

    with sync_playwright() as p:
        # Start browser with optimized settings
        browser = p.chromium.launch(
            headless=True,
            slow_mo=0,
            args=[
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-extensions',
                '--window-size=1920,1080'
            ]
        )
        context = browser.new_context(
            storage_state=SESSION_FILE,
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        page.goto("https://pro.x.com/i/decks/1915696383484371263", timeout=60000)
        
        # Wait for main content to load
        print("[UPDATER] Waiting for main content to load...")
        try:
            page.wait_for_selector('[data-testid="cellInnerDiv"]', timeout=30000)
            print("[UPDATER] Main container found")
            page.wait_for_selector('article', timeout=30000)
            print("[UPDATER] First article found")
            time.sleep(5)
        except Exception as e:
            print(f"[UPDATER] Error during initial content load: {e}")
            return

        print("[UPDATER] Engagement tracker started.")

        while True:
            cycle_start = datetime.now(timezone.utc)

            # Get tweets from the last 24h that are ready to be updated
            known_updates = {t["tweet_id"]: t for t in get_tweets_to_update(hours_back=24)}
            tweets_to_update = set(known_updates.keys())
            updated = 0
            scroll_scans = 0
            processed_tweet_ids = set()

            # Track scroll positions we've tried
            scroll_positions = set()
            max_scroll_retries = 3
            scroll_retry_count = 0
            scroll_amounts = [2000, 1000, 500]  # Try different scroll amounts
            
            while True:
                now = datetime.now(timezone.utc)
                elapsed = (now - cycle_start).total_seconds()

                if elapsed >= max_cycle_seconds:
                    print(f"[UPDATER] Max cycle time {max_cycle_seconds}s reached. Restarting top scan.")
                    scroll_container(page, "up")
                    time.sleep(2)
                    break

                scroll_scans += 1

                # Locate all tweet articles on the page
                articles = page.locator("article")
                article_count = articles.count()
                print(f"[UPDATER] Found {article_count} articles on current page")

                # Track earliest and latest tweets we can see
                earliest_time = None
                latest_time = None

                for i in range(article_count):
                    try:
                        article = articles.nth(i)
                        tweet_id = extract_tweet_id(article)
                        tweet_time = get_tweet_time(article)

                        if tweet_time:
                            if earliest_time is None or tweet_time < earliest_time:
                                earliest_time = tweet_time
                            if latest_time is None or tweet_time > latest_time:
                                latest_time = tweet_time

                        if tweet_id:
                            processed_tweet_ids.add(tweet_id)

                            # Skip if tweet not in the list of known update targets
                            if tweet_id not in known_updates:
                                continue

                            # Get last time this tweet was updated
                            last_updated = datetime.fromisoformat(recent_updates.get(tweet_id, "1970-01-01T00:00:00"))
                            if last_updated.tzinfo is None:
                                last_updated = last_updated.replace(tzinfo=timezone.utc)

                            # Skip if too soon to re-update
                            if (now - last_updated).total_seconds() < min_update_spacing_seconds:
                                continue

                            # Extract and save new metrics
                            metrics = extract_metrics(article)
                            if any(metrics.values()):
                                update_tweet_metrics(tweet_id, metrics)
                                recent_updates[tweet_id] = now.isoformat()
                                updated += 1
                                tweets_to_update.discard(tweet_id)
                                print(f"[UPDATER] Successfully updated tweet {tweet_id}")

                    except Exception as e:
                        print(f"[UPDATER ERROR] Failed updating #{i}: {e}")

                # Check which tweets we're still missing
                missing_tweets = tweets_to_update - processed_tweet_ids
                if missing_tweets:
                    print(f"[UPDATER] Still missing tweets: {missing_tweets}")
                    if earliest_time and latest_time:
                        print(f"[UPDATER] Current visible range: {earliest_time} to {latest_time}")

                    # Try different scroll amounts when we're stuck
                    scroll_result = scroll_container(page, "down", scroll_amounts[scroll_retry_count % len(scroll_amounts)])
                    if isinstance(scroll_result, dict) and scroll_result.get('scrolled'):
                        current_pos = scroll_result.get('newPosition', 0)
                        if current_pos in scroll_positions:
                            scroll_retry_count += 1
                            if scroll_retry_count >= max_scroll_retries * len(scroll_amounts):
                                print(f"[UPDATER] Unable to find missing tweets after {max_scroll_retries} retries with different scroll amounts")
                                break
                        scroll_positions.add(current_pos)
                    time.sleep(2)
                else:
                    break

            # Build and conditionally print the summary
            current_summary = f"[SUMMARY] Cycle finished: {updated} tweets updated, {len(tweets_to_update)} still pending, after {scroll_scans} scroll scans."

            if current_summary == last_summary:
                skipped_same_summaries += 1
            else:
                if skipped_same_summaries > 0:
                    print(f"[SKIPPED] {skipped_same_summaries} identical summary prints skipped.")
                    skipped_same_summaries = 0
                print(current_summary)
                last_summary = current_summary

            # Persist updated timestamps
            save_recent_updates(recent_updates)

if __name__ == "__main__":
    updater_engagement_tracker()
