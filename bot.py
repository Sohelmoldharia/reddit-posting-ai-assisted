import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from dotenv import load_dotenv

import content_generator
import reddit_poster

load_dotenv()

CONFIG_PATH = Path("config.json")
TOPICS_PATH = Path("topics.txt")
LOG_PATH = Path("posts_log.json")
IMAGES_DIR = Path("images")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_topics():
    if not TOPICS_PATH.exists():
        return []
    topics = []
    with open(TOPICS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            topics.append(line)
    return topics


def parse_topic(topic_line):
    if topic_line.startswith("[image:"):
        end = topic_line.index("]")
        image_path = topic_line[7:end]
        text = topic_line[end + 1:].strip()
        return {"text": text, "image": image_path}
    return {"text": topic_line, "image": None}


def load_log():
    if not LOG_PATH.exists():
        return {}
    with open(LOG_PATH) as f:
        return json.load(f)


def save_log(log):
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def get_today():
    return date.today().isoformat()


def get_posts_today(log):
    today = get_today()
    day_data = log.get(today, {})
    count = 0
    for posts in day_data.values():
        count += len(posts)
    return count


def log_post(log, subreddit, topic, post_id, post_url, post_type):
    today = get_today()
    if today not in log:
        log[today] = {}
    if subreddit not in log[today]:
        log[today][subreddit] = []
    log[today][subreddit].append({
        "topic": topic,
        "post_id": post_id,
        "url": post_url,
        "type": post_type,
        "time": datetime.now().strftime("%H:%M:%S"),
    })
    save_log(log)


def pick_topic(topics, log):
    if not topics:
        print("No topics available. Add topics to topics.txt")
        return None

    today_data = log.get(get_today(), {})
    used_topics = set()
    for posts in today_data.values():
        for p in posts:
            used_topics.add(p["topic"])

    available = [t for t in topics if parse_topic(t)["text"] not in used_topics]
    if not available:
        available = topics

    return random.choice(available)


def pick_subreddit(config, log):
    today_data = log.get(get_today(), {})
    subs = config["subreddits"]
    # weight toward subs that haven't been posted to yet today
    unposted = [s for s in subs if s not in today_data]
    if unposted:
        return random.choice(unposted)
    return random.choice(subs)


def do_post(subreddit, topic_line, config):
    topic = parse_topic(topic_line)
    provider = config["ai_provider"]
    is_image = topic["image"] is not None

    try:
        example_titles = reddit_poster.get_recent_titles(subreddit)
    except Exception:
        example_titles = None

    print(f"  Generating content with {provider}...")
    content = content_generator.generate_content(
        topic["text"], subreddit, provider, is_image, example_titles
    )

    title = content["title"]

    if is_image and os.path.exists(topic["image"]):
        print(f"  Posting image to r/{subreddit}: {title}")
        post_id, post_url = reddit_poster.post_image(
            subreddit, title, topic["image"]
        )
        return topic["text"], post_id, post_url, "image"
    else:
        body = content.get("body", "")
        print(f"  Posting text to r/{subreddit}: {title}")
        post_id, post_url = reddit_poster.post_text(subreddit, title, body)
        return topic["text"], post_id, post_url, "text"


_daily_start_cache = {}
_daily_target_cache = {}


def _start_minute_for(day_key, config):
    if day_key not in _daily_start_cache:
        jitter = config["schedule"].get("daily_start_jitter_minutes", 0)
        offset = random.randint(0, jitter) if jitter else 0
        _daily_start_cache[day_key] = config["schedule"]["start_hour"] * 60 + offset
    return _daily_start_cache[day_key]


def _target_posts_for(day_key, config):
    if day_key not in _daily_target_cache:
        lo = config["min_posts_per_day"]
        hi = config["max_posts_per_day"]
        _daily_target_cache[day_key] = random.randint(lo, hi)
    return _daily_target_cache[day_key]


def is_within_schedule(config):
    now = datetime.now()
    now_min = now.hour * 60 + now.minute
    start_min = _start_minute_for(now.date().isoformat(), config)
    end_min = config["schedule"]["end_hour"] * 60
    return start_min <= now_min < end_min


def next_start_datetime(config):
    now = datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = midnight + timedelta(minutes=_start_minute_for(now.date().isoformat(), config))
    if now < today_start:
        return today_start
    tomorrow = now + timedelta(days=1)
    start_min = _start_minute_for(tomorrow.date().isoformat(), config)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=start_min)


def _compute_delay(config, posts_done, target):
    """Spread remaining posts across the remaining schedule window."""
    now = datetime.now()
    end_min = config["schedule"]["end_hour"] * 60
    now_min = now.hour * 60 + now.minute
    remaining_minutes = max(end_min - now_min, 30)
    remaining_posts = max(target - posts_done, 1)

    avg_gap = remaining_minutes / remaining_posts
    # randomize around the average so gaps aren't uniform
    lo = max(int(avg_gap * 0.5), 15)
    hi = max(int(avg_gap * 1.5), lo + 10)
    return random.randint(lo, hi)


def run_bot():
    config = load_config()
    topics = load_topics()
    log = load_log()

    if not topics:
        print("No topics found. Add topics to topics.txt first.")
        sys.exit(1)

    today = get_today()
    target = _target_posts_for(today, config)

    print(f"Bot started — {len(config['subreddits'])} subreddits, {len(topics)} topics")
    print(f"Today's target: {target} posts")
    print(f"Schedule: {config['schedule']['start_hour']}:00 - {config['schedule']['end_hour']}:00")
    print(f"AI provider: {config['ai_provider']}")
    print()

    try:
        user = reddit_poster.verify_login()
        print(f"Logged in as u/{user}")
    except Exception as e:
        print(f"Reddit login failed: {e}")
        print("Check your .env file credentials.")
        sys.exit(1)

    while True:
        config = load_config()
        today = get_today()
        target = _target_posts_for(today, config)
        log = load_log()
        posts_done = get_posts_today(log)

        if not is_within_schedule(config):
            wake = next_start_datetime(config)
            wait_secs = max((wake - datetime.now()).total_seconds(), 60)
            print(f"\nOutside schedule. Sleeping until {wake.strftime('%Y-%m-%d %H:%M')} "
                  f"({int(wait_secs // 3600)}h {int((wait_secs % 3600) // 60)}m)")
            time.sleep(wait_secs)
            continue

        if posts_done >= target:
            wake = next_start_datetime(config)
            wait_secs = max((wake - datetime.now()).total_seconds(), 60)
            print(f"\nAll {target} posts done for today. Sleeping until {wake.strftime('%Y-%m-%d %H:%M')}")
            time.sleep(wait_secs)
            continue

        topics = load_topics()
        topic_line = pick_topic(topics, log)
        if not topic_line:
            time.sleep(60)
            continue

        subreddit = pick_subreddit(config, log)
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Post {posts_done + 1}/{target} — r/{subreddit}...")

        try:
            topic_text, post_id, post_url, post_type = do_post(
                subreddit, topic_line, config
            )
            log_post(log, subreddit, topic_text, post_id, post_url, post_type)
            posts_done += 1
            print(f"  Done! {post_url}")
        except Exception as e:
            print(f"  Failed: {e}")

        delay = _compute_delay(config, posts_done, target)
        print(f"  Next post in ~{delay} minutes")
        time.sleep(delay * 60)


def post_now(subreddit):
    config = load_config()
    topics = load_topics()
    log = load_log()

    if not topics:
        print("No topics. Add some to topics.txt")
        return

    topic_line = pick_topic(topics, log)
    if not topic_line:
        return

    print(f"Posting to r/{subreddit} now...")
    try:
        topic_text, post_id, post_url, post_type = do_post(
            subreddit, topic_line, config
        )
        log_post(log, subreddit, topic_text, post_id, post_url, post_type)
        print(f"Done! {post_url}")
    except Exception as e:
        print(f"Failed: {e}")


def show_status():
    config = load_config()
    log = load_log()
    today = get_today()
    today_data = log.get(today, {})
    target = _target_posts_for(today, config)
    posts_done = get_posts_today(log)

    print(f"=== {today} — {posts_done}/{target} posts ===\n")
    for sub in config["subreddits"]:
        posts = today_data.get(sub, [])
        if posts:
            for p in posts:
                print(f"  r/{sub} [{p['time']}] {p['topic']}")
    if not any(today_data.values()):
        print("  No posts yet today.")
    print()


def add_topic(topic):
    with open(TOPICS_PATH, "a") as f:
        f.write(f"\n{topic}")
    print(f"Added: {topic}")


def main():
    parser = argparse.ArgumentParser(description="Reddit posting bot")
    parser.add_argument("--run", action="store_true", help="Start the bot (runs all day)")
    parser.add_argument("--post-now", metavar="SUBREDDIT", help="Post to a subreddit right now")
    parser.add_argument("--status", action="store_true", help="Show today's posting status")
    parser.add_argument("--add-topic", metavar="TOPIC", help="Add a trending keyword")
    parser.add_argument("--verify", action="store_true", help="Verify Reddit login works")

    args = parser.parse_args()

    if args.verify:
        try:
            user = reddit_poster.verify_login()
            print(f"Login OK — u/{user}")
        except Exception as e:
            print(f"Login failed: {e}")
    elif args.add_topic:
        add_topic(args.add_topic)
    elif args.status:
        show_status()
    elif args.post_now:
        post_now(args.post_now)
    elif args.run:
        run_bot()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
