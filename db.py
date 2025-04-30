import sqlite3
import json
from datetime import datetime, timedelta

conn = sqlite3.connect("tweets.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

def init_db():
    c.execute("""
        CREATE TABLE IF NOT EXISTS tweets (
            tweet_id TEXT PRIMARY KEY,
            user_handle TEXT,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            likes_series TEXT DEFAULT '[]',
            retweets_series TEXT DEFAULT '[]',
            replies_series TEXT DEFAULT '[]',
            views_series TEXT DEFAULT '[]',
            engagement_timestamps TEXT DEFAULT '[]',
            update_phase TEXT DEFAULT 'minute',
            update_count INTEGER DEFAULT 0,
            next_update_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

def insert_new_tweets(tweets):
    init_db()
    for tweet in tweets:
        try:
            c.execute("""
                INSERT OR IGNORE INTO tweets (
                    tweet_id, user_handle, text
                ) VALUES (?, ?, ?)
            """, (
                tweet["id"], tweet["user"], tweet["text"]
            ))
        except Exception as e:
            print(f"[ERROR] Failed to insert tweet {tweet['id']}: {e}")
    conn.commit()

def get_tweets_to_update(hours_back=24, limit=None):
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=hours_back)
    if limit:
        c.execute("""
            SELECT * FROM tweets
            WHERE next_update_ts <= ?
              AND created_at >= ?
            ORDER BY next_update_ts ASC
            LIMIT ?
        """, (now.isoformat(), cutoff.isoformat(), int(limit)))
    else:
        c.execute("""
            SELECT * FROM tweets
            WHERE next_update_ts <= ?
              AND created_at >= ?
            ORDER BY next_update_ts ASC
        """, (now.isoformat(), cutoff.isoformat()))
    return [dict(row) for row in c.fetchall()]

def update_tweet_metrics(tweet_id, metrics):
    c.execute("""
        SELECT likes_series, retweets_series, replies_series, views_series,
               engagement_timestamps, update_count, update_phase, created_at
        FROM tweets WHERE tweet_id = ?
    """, (tweet_id,))
    row = c.fetchone()
    if not row:
        print(f"[ERROR] Tweet {tweet_id} not found in DB.")
        return

    # Parse data
    likes = json.loads(row["likes_series"])
    retweets = json.loads(row["retweets_series"])
    replies = json.loads(row["replies_series"])
    views = json.loads(row["views_series"])
    timestamps = json.loads(row["engagement_timestamps"])
    count = row["update_count"]
    phase = row["update_phase"]
    created_at = datetime.fromisoformat(row["created_at"])

    # Calculate time offset in seconds
    now = datetime.utcnow()
    time_offset = int((now - created_at).total_seconds())

    # Append metrics and timestamp
    likes.append(metrics["likes"])
    retweets.append(metrics["retweets"])
    replies.append(metrics["replies"])
    views.append(metrics["views"])
    timestamps.append(time_offset)

    # Update schedule
    count += 1
    if phase == "minute" and count >= 60:
        phase = "halfhour"
        next_ts = now + timedelta(minutes=30)
    elif phase == "minute":
        next_ts = now + timedelta(minutes=1)
    else:
        next_ts = now + timedelta(minutes=30)

    c.execute("""
        UPDATE tweets SET
            likes_series = ?,
            retweets_series = ?,
            replies_series = ?,
            views_series = ?,
            engagement_timestamps = ?,
            update_count = ?,
            update_phase = ?,
            next_update_ts = ?
        WHERE tweet_id = ?
    """, (
        json.dumps(likes),
        json.dumps(retweets),
        json.dumps(replies),
        json.dumps(views),
        json.dumps(timestamps),
        count,
        phase,
        next_ts.isoformat(),
        tweet_id
    ))
    conn.commit()

def get_all_tracked_ids():
    c.execute("SELECT tweet_id FROM tweets")
    return [row[0] for row in c.fetchall()]

def update_tweet_metrics_by_id(tweet_id, metrics):
    update_tweet_metrics(tweet_id, metrics)