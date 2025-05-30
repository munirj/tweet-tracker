from playwright.sync_api import sync_playwright
from datetime import datetime, timezone, timedelta
import sqlite3
import time
import json
from config import SESSION_FILE
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # current script dir
DB_PATH = os.path.join(BASE_DIR, "..", "dbs", "tweets_infinite.db")
DB_PATH = os.path.abspath(DB_PATH)  # normalize the final path

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS tweets (
            tweet_id TEXT PRIMARY KEY,
            user_handle TEXT,
            text TEXT,
            created_at TEXT,
            likes INTEGER DEFAULT 0,
            reposts INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            collected_at TEXT
        );
    """)
    conn.commit()
    return conn, c

def extract_tweet_id(article):
    """Extract tweet ID from article"""
    try:
        # More efficient selector that only gets status links
        link = article.locator('a[href*="/status/"]').first
        if link:
            href = link.get_attribute('href', timeout=5000)
            if href:
                return href.split('/')[-1]
    except Exception:
        pass
    return None

def extract_tweet_time(article):
    """Extract timestamp from a tweet article"""
    try:
        # Get tweet ID for better debugging
        tweet_id = None
        try:
            link = article.locator('a[href*="/status/"]').first
            if link:
                href = link.get_attribute('href')
                if href:
                    tweet_id = href.split('/')[-1]
        except:
            pass
            
        print(f"\n[TIME DEBUG] Extracting time for tweet {tweet_id}:")
        
        # Try all possible time selectors
        time_selectors = [
            'time[datetime]',  # Standard time element
            'time',            # Any time element
            '[datetime]'       # Any element with datetime
        ]
        
        for selector in time_selectors:
            elements = article.locator(selector).all()
            print(f"[TIME DEBUG] Found {len(elements)} elements matching '{selector}'")
            
            for idx, element in enumerate(elements):
                try:
                    datetime_str = element.get_attribute('datetime', timeout=5000)
                    visible_text = element.inner_text(timeout=5000)
                    print(f"[TIME DEBUG] Element {idx}: datetime='{datetime_str}' text='{visible_text}'")
                    
                    if datetime_str:
                        # Handle Twitter's timestamp format
                        if not datetime_str.endswith('Z') and not '+' in datetime_str:
                            datetime_str += '+00:00'
                        try:
                            tweet_time = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
                            print(f"[TIME DEBUG] Successfully parsed: {tweet_time} (UTC)")
                            return tweet_time
                        except Exception as e:
                            print(f"[TIME DEBUG] Failed to parse '{datetime_str}': {e}")
                except Exception as e:
                    print(f"[TIME DEBUG] Error getting element {idx} attributes: {e}")
        
        # If we get here, we found no valid timestamps
        print("[TIME DEBUG] No valid timestamps found, dumping HTML:")
        html = article.inner_html()
        print(f"[TIME DEBUG] {html[:500]}...")
        
    except Exception as e:
        print(f"[TIME DEBUG] Fatal error: {e}")
    return None

def extract_tweet_text(article):
    """Extract tweet text content"""
    try:
        # Only get first text block with timeout
        text = article.locator("div[lang]").first.inner_text(timeout=5000)
        return text.strip()
    except Exception:
        return ""

def extract_user_handle(article):
    """Extract user handle from article"""
    try:
        handle_elem = article.locator("a[role='link'] span").first
        return handle_elem.inner_text(timeout=5000) if handle_elem else "unknown"
    except Exception:
        return "unknown"

def extract_metric_from_label(article, label_text):
    """Extract a specific metric (likes, reposts, etc.) from article"""
    try:
        # First try with shorter timeout
        metrics = article.locator(f'[aria-label*="{label_text}"]').first
        if metrics:
            value = metrics.get_attribute("aria-label", timeout=5000)
            if value:
                # Extract first number from string
                import re
                numbers = re.findall(r'\d+', value)
                if numbers:
                    return int(numbers[0])
    except Exception:
        pass
    return 0

def extract_metrics(article):
    """Extract all engagement metrics from article"""
    return {
        "likes": extract_metric_from_label(article, "Like"),
        "retweets": extract_metric_from_label(article, "Repost"),
        "replies": extract_metric_from_label(article, "Repl"),
        "views": extract_metric_from_label(article, "View")
    }

def careful_scroll(page):
    """Scroll carefully and wait for content to load"""
    try:
        # Find a tweet to scroll to
        articles = page.locator("article").all()
        if not articles:
            print("[DEBUG] No articles found to scroll to")
            return False
            
        # Get the last visible article
        last_article = articles[-1]
        
        # Scroll to it using mouse wheel
        last_article.scroll_into_view_if_needed()
        page.mouse.wheel(0, 1000)
        
        # Wait for load
        time.sleep(3)
        
        # Check if we moved
        new_articles = page.locator("article").all()
        if len(new_articles) > len(articles):
            print(f"[DEBUG] Scrolled: {len(articles)} -> {len(new_articles)} articles")
            return True
            
        print("[DEBUG] No new articles loaded after scroll")
        return False
            
    except Exception as e:
        print(f"[ERROR] Failed to scroll: {e}")
        return False

def archive_tweets():
    """Main function to continuously archive tweets until stopped"""
    conn, c = init_db()
    seen_ids = set()
    start_time = datetime.now(timezone.utc)
    print(f"[ARCHIVER] Starting archival at: {start_time}")
    
    with sync_playwright() as p:
        # Launch browser with optimized settings
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gpu',
                '--window-size=1920,1080'
            ]
        )
        context = browser.new_context(
            storage_state=SESSION_FILE,
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        
        # Enable request logging
        def log_request(request):
            if 'graphql' in request.url or 'api' in request.url:
                print(f"[DEBUG] Request: {request.method} {request.url}")
        page = context.new_page()
        page.on('request', log_request)
        
        print("[ARCHIVER] Loading timeline...")
        page.set_default_timeout(60000)  # 60 seconds for all operations
        
        try:
            # First try loading with shorter timeout
            print("[DEBUG] Attempting to load page...")
            try:
                response = page.goto("https://pro.x.com/i/decks/1915696383484371263", timeout=20000)
                print(f"[DEBUG] Initial page load complete with status: {response.status}")
            except Exception as e:
                print(f"[DEBUG] Initial page load timed out: {e}")
                print("[DEBUG] Checking if page loaded partially...")
            
            # Check if we got any content
            try:
                title = page.title()
                print(f"[DEBUG] Page title: {title}")
            except:
                print("[DEBUG] Could not get page title")
                
            # Wait for network to settle with a shorter timeout
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
                print("[DEBUG] Network is idle")
            except Exception as e:
                print(f"[DEBUG] Network not idle: {e}")
            
            # Wait a moment for any post-load JavaScript
            page.wait_for_timeout(5000)
            
            # Try to detect what state we're in
            print("[DEBUG] Checking page state...")
            html = page.content()
            print(f"[DEBUG] Page title: {page.title()}")
            
            # Check for various timeline selectors
            timeline_selectors = [
                '[data-testid="cellInnerDiv"]',  # Standard timeline
                'article',                        # Tweet articles
                '[data-testid="tweet"]',         # Alternative tweet marker
                'div[role="main"]',              # Main content area
                '.timeline-item'                  # Another possible timeline class
            ]
            
            # Check for authentication elements
            auth_selectors = [
                'input[autocomplete="username"]',  # Login form
                'input[name="text"]',             # Another login field
                '[data-testid="login-button"]'    # Login button
            ]
            
            print("[DEBUG] Checking for timeline elements...")
            for selector in timeline_selectors:
                count = page.locator(selector).count()
                print(f"[DEBUG] Found {count} elements matching '{selector}'")
                
            print("[DEBUG] Checking for auth elements...")
            for selector in auth_selectors:
                count = page.locator(selector).count()
                print(f"[DEBUG] Found {count} elements matching '{selector}'")
            
            # Check if we're logged in
            for selector in auth_selectors:
                if page.locator(selector).count() > 0:
                    print("[ERROR] Not authenticated - login form detected")
                    print("[ERROR] Please ensure your session file is valid")
                    browser.close()
                    conn.close()
                    return
            
            # Try to find timeline content
            found_timeline = False
            for selector in timeline_selectors:
                try:
                    element = page.wait_for_selector(selector, timeout=10000)
                    if element:
                        print(f"[DEBUG] Successfully found timeline using selector: {selector}")
                        found_timeline = True
                        break
                except:
                    continue
                    
            if not found_timeline:
                print("[ERROR] Could not find timeline content with any known selector")
                print("[DEBUG] Current page HTML:")
                print(html[:1000] + "...")
                browser.close()
                conn.close()
                return
            
        except Exception as e:
            print(f"[ERROR] Failed while checking authentication: {e}")
            browser.close()
            conn.close()
            return
        
        # Force scroll to top to ensure we start fresh
        page.evaluate("""
            () => {
                window.scrollTo(0, 0);
                const containers = [
                    document.querySelector('[data-testid="primaryColumn"]'),
                    document.querySelector('div[aria-label*="Timeline"]'),
                    document.querySelector('div[role="main"]'),
                    document.querySelector('main')
                ];
                for (const container of containers) {
                    if (container) container.scrollTop = 0;
                }
            }
        """)
        time.sleep(3)
        
        print("[ARCHIVER] Starting tweet collection...")
        oldest_seen_time = datetime.now(timezone.utc)
        oldest_archived_time = datetime.now(timezone.utc)
        no_new_tweets_count = 0
        scroll_attempts = 0
        
        last_progress_time = datetime.now(timezone.utc)
        stalled_scrolls = 0
        
        # Track progress
        while True:  # Run until manually stopped
            articles = page.locator("article")
            article_count = articles.count()
            found_new_tweet = False
            scroll_attempts += 1
            
            print(f"\n[ARCHIVER] Scroll attempt {scroll_attempts}")
            print(f"[ARCHIVER] Articles loaded: {article_count}")
            
            # Process articles in batches for better performance
            batch_size = 10
            for i in range(0, article_count, batch_size):
                batch_end = min(i + batch_size, article_count)
                current_time = datetime.now(timezone.utc)
                print(f"\n[ARCHIVER] Processing articles {i+1}-{batch_end} of {article_count}...")
                print(f"[ARCHIVER] Current oldest seen: {oldest_seen_time} ({(current_time - oldest_seen_time).total_seconds() / 3600:.1f} hours ago)")
                
                for j in range(i, batch_end):
                    try:
                        article = articles.nth(j)
                        tweet_id = extract_tweet_id(article)
                        if not tweet_id or tweet_id in seen_ids:
                            continue
                        
                        tweet_time = extract_tweet_time(article)
                        if not tweet_time:
                            print("[ARCHIVER] Skipping tweet with no timestamp")
                            continue
                        
                        # Get tweet ID for debugging
                        tweet_id = extract_tweet_id(article)
                        current_time = datetime.now(timezone.utc)
                        age_hours = (current_time - tweet_time).total_seconds() / 3600
                        print(f"[ARCHIVER] Tweet {tweet_id}: time={tweet_time}, age={age_hours:.1f}h")
                        
                        # Always track the oldest tweet we've seen
                        oldest_seen_time = min(oldest_seen_time, tweet_time)
                        
                        # Track this tweet as archived
                        oldest_archived_time = min(oldest_archived_time, tweet_time)
                        seen_ids.add(tweet_id)
                        found_new_tweet = True
                        
                        # Extract all tweet data
                        metrics = extract_metrics(article)
                        user_handle = extract_user_handle(article)
                        tweet_text = extract_tweet_text(article)
                        collected_at = datetime.now(timezone.utc)
                        
                        # Store in database
                        try:
                            c.execute("""
                                INSERT OR REPLACE INTO tweets (
                                    tweet_id, user_handle, text, created_at,
                                    likes, reposts, replies, views, collected_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                tweet_id, user_handle, tweet_text, tweet_time.strftime('%Y-%m-%d %H:%M:%S'),
                                metrics["likes"], metrics["retweets"], 
                                metrics["replies"], metrics["views"],
                                collected_at.strftime('%Y-%m-%d %H:%M:%S')
                            ))
                            conn.commit()
                            print(f"[ARCHIVER] Archived tweet {tweet_id} from {tweet_time}")
                        except Exception as e:
                            print(f"[ERROR] Failed to store tweet {tweet_id}: {e}")
                    
                    except Exception as e:
                        print(f"[ERROR] Failed to process article: {e}")
            
            # Check if we're making progress
            if found_new_tweet:
                if oldest_seen_time < last_progress_time:
                    hours_back = (start_time - oldest_seen_time).total_seconds() / 3600
                    print(f"[ARCHIVER] Progress: archived back to {oldest_seen_time} ({hours_back:.1f}h ago)")
                    last_progress_time = oldest_seen_time
                    stalled_scrolls = 0
                else:
                    stalled_scrolls += 1
                    print(f"[ARCHIVER] No progress in time ({stalled_scrolls} scrolls stalled)")
            else:
                stalled_scrolls += 1
                print(f"[ARCHIVER] No new tweets ({stalled_scrolls} scrolls stalled)")
            
            # If we're truly stuck (no scrolling progress AND no new tweets)
            if stalled_scrolls >= 20:
                print("[ARCHIVER] Completely stuck, trying to force-load more content...")
                # Try to trigger Twitter's infinite scroll loader
                page.evaluate("""
                    () => {
                        const timeline = document.querySelector('[data-testid="primaryColumn"]');
                        if (timeline) {
                            timeline.scrollTop = timeline.scrollHeight;
                        }
                    }
                """)
                time.sleep(3)  # Give it time to load
                stalled_scrolls = 0
            
            # Scroll carefully
            print(f"[ARCHIVER] Scrolling... (oldest seen: {oldest_seen_time})")
            if not careful_scroll(page):
                print("[ARCHIVER] Failed to scroll, waiting before retry...")
                time.sleep(3)
                stalled_scrolls += 1
        
        print("[ARCHIVER] Finished archiving tweets")
        print(f"[ARCHIVER] Total tweets archived: {len(seen_ids)}")
        print(f"[ARCHIVER] Oldest archived tweet: {oldest_archived_time}")
        print(f"[ARCHIVER] Oldest seen tweet: {oldest_seen_time}")
        
        browser.close()
        conn.close()

if __name__ == "__main__":
    archive_tweets()
