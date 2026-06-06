import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, date
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


def get_posted_today(log):
    today = get_today()
    return log.get(today, {})


def has_posted(log, subreddit, config):
    posted = get_posted_today(log)
    count = len(posted.get(subreddit, []))
    return count >= config["posts_per_day"]


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


def get_pending_subreddits(config, log):
    pending = []
    for sub in config["subreddits"]:
        if not has_posted(log, sub, config):
            pending.append(sub)
    return pending


def pick_topic(topics, log):
    if not topics:
        print("No topics available. Add topics to topics.txt")
        return None

    today_posts = get_posted_today(log)
    used_topics = set()
    for posts in today_posts.values():
        for p in posts:
            used_topics.add(p["topic"])

    available = [t for t in topics if parse_topic(t)["text"] not in used_topics]
    if not available:
        available = topics

    return random.choice(available)


def do_post(subreddit, topic_line, config):
    topic = parse_topic(topic_line)
    provider = config["ai_provider"]
    is_image = topic["image"] is not None

    print(f"  Generating content with {provider}...")
    content = content_generator.generate_content(
        topic["text"], subreddit, provider, is_image
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


def is_within_schedule(config):
    now = datetime.now().hour
    start = config["schedule"]["start_hour"]
    end = config["schedule"]["end_hour"]
    return start <= now < end


def run_bot():
    config = load_config()
    topics = load_topics()
    log = load_log()

    if not topics:
        print("No topics found. Add topics to topics.txt first.")
        sys.exit(1)

    print(f"Bot started — {len(config['subreddits'])} subreddits, {len(topics)} topics")
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
        if not is_within_schedule(config):
            now = datetime.now()
            start = config["schedule"]["start_hour"]
            if now.hour >= config["schedule"]["end_hour"]:
                wake = now.replace(day=now.day + 1, hour=start, minute=0, second=0)
            else:
                wake = now.replace(hour=start, minute=0, second=0)
            wait_secs = (wake - now).total_seconds()
            print(f"Outside schedule. Sleeping until {start}:00 ({int(wait_secs // 3600)}h {int((wait_secs % 3600) // 60)}m)")
            time.sleep(wait_secs)
            log = load_log()
            continue

        pending = get_pending_subreddits(config, log)

        if not pending:
            now = datetime.now()
            tomorrow_start = now.replace(
                day=now.day + 1,
                hour=config["schedule"]["start_hour"],
                minute=0, second=0,
            )
            wait_secs = (tomorrow_start - now).total_seconds()
            print(f"All posts done for today. Sleeping until tomorrow ({int(wait_secs // 3600)}h)")
            time.sleep(wait_secs)
            log = load_log()
            continue

        topics = load_topics()
        topic_line = pick_topic(topics, log)
        if not topic_line:
            time.sleep(60)
            continue

        subreddit = random.choice(pending)
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Posting to r/{subreddit}...")

        try:
            topic_text, post_id, post_url, post_type = do_post(
                subreddit, topic_line, config
            )
            log_post(log, subreddit, topic_text, post_id, post_url, post_type)
            print(f"  Done! {post_url}")
        except Exception as e:
            print(f"  Failed: {e}")

        min_delay = config["schedule"]["min_delay_minutes"]
        max_delay = config["schedule"]["max_delay_minutes"]
        delay = random.randint(min_delay, max_delay)
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
    posted = get_posted_today(log)

    print(f"=== Status for {get_today()} ===\n")
    for sub in config["subreddits"]:
        posts = posted.get(sub, [])
        if posts:
            for p in posts:
                print(f"  r/{sub} — posted at {p['time']}: {p['topic']}")
        else:
            print(f"  r/{sub} — pending")
    print()

    pending = get_pending_subreddits(config, log)
    print(f"{len(config['subreddits']) - len(pending)}/{len(config['subreddits'])} subreddits done")


def add_topic(topic):
    with open(TOPICS_PATH, "a") as f:
        f.write(f"\n{topic}")
    print(f"Added topic: {topic}")


def main():
    parser = argparse.ArgumentParser(description="Reddit posting bot")
    parser.add_argument("--run", action="store_true", help="Start the bot")
    parser.add_argument("--post-now", metavar="SUBREDDIT", help="Post immediately to a subreddit")
    parser.add_argument("--status", action="store_true", help="Show today's posting status")
    parser.add_argument("--add-topic", metavar="TOPIC", help="Add a topic to topics.txt")
    parser.add_argument("--verify", action="store_true", help="Verify Reddit login")

    args = parser.parse_args()

    if args.verify:
        try:
            user = reddit_poster.verify_login()
            print(f"Login OK — logged in as u/{user}")
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
