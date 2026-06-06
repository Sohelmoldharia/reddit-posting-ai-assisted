import json
import os
import random
import threading
import time
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

from dotenv import load_dotenv, set_key
from flask import Flask, render_template, request, jsonify

import content_generator
import reddit_poster

load_dotenv()

app = Flask(__name__)

CONFIG_PATH = Path("config.json")
TOPICS_PATH = Path("topics.txt")
LOG_PATH = Path("posts_log.json")
SCHEDULE_PATH = Path("scheduled_posts.json")
ENV_PATH = Path(".env")

_bot_thread = None
_bot_running = False
_bot_status = {"state": "stopped", "message": "Bot is not running", "last_post": None}
_daily_start_cache = {}
_daily_target_cache = {}


# ─── helpers ───

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


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


def save_topics(topics):
    with open(TOPICS_PATH, "w") as f:
        for t in topics:
            f.write(t + "\n")


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
    day_data = log.get(get_today(), {})
    return sum(len(posts) for posts in day_data.values())


def get_env_value(key):
    return os.getenv(key, "")


def get_env_status():
    keys = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME",
            "REDDIT_PASSWORD", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
    return {k: bool(os.getenv(k)) for k in keys}


def save_env_value(key, value):
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), key, value)
    os.environ[key] = value


# ─── scheduled posts ───

def load_scheduled():
    if not SCHEDULE_PATH.exists():
        return []
    with open(SCHEDULE_PATH) as f:
        return json.load(f)


def save_scheduled(items):
    with open(SCHEDULE_PATH, "w") as f:
        json.dump(items, f, indent=2)


def check_scheduled_posts(config, log):
    """Run any scheduled posts whose time has come. Returns number posted."""
    items = load_scheduled()
    now = datetime.now()
    posted = 0
    remaining = []

    for item in items:
        if item.get("status") == "done":
            remaining.append(item)
            continue
        sched_time = datetime.fromisoformat(item["scheduled_at"])
        if now >= sched_time:
            try:
                topic_text, post_id, post_url, post_type = do_post(
                    item["subreddit"], item["topic"], config
                )
                today = get_today()
                if today not in log:
                    log[today] = {}
                if item["subreddit"] not in log[today]:
                    log[today][item["subreddit"]] = []
                log[today][item["subreddit"]].append({
                    "topic": topic_text, "post_id": post_id,
                    "url": post_url, "type": post_type,
                    "time": now.strftime("%H:%M:%S"),
                })
                save_log(log)
                item["status"] = "done"
                item["post_url"] = post_url
                posted += 1
            except Exception as e:
                item["status"] = "failed"
                item["error"] = str(e)
        remaining.append(item)

    save_scheduled(remaining)
    return posted


# ─── bot thread logic ───

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


def pick_topic(topics, log):
    if not topics:
        return None
    today_data = log.get(get_today(), {})
    used = set()
    for posts in today_data.values():
        for p in posts:
            used.add(p["topic"])
    available = [t for t in topics if parse_topic(t)["text"] not in used]
    if not available:
        available = topics
    return random.choice(available)


def pick_subreddit(config, log):
    today_data = log.get(get_today(), {})
    subs = config["subreddits"]
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
    content = content_generator.generate_content(
        topic["text"], subreddit, provider, is_image, example_titles
    )
    title = content["title"]
    if is_image and os.path.exists(topic["image"]):
        post_id, post_url = reddit_poster.post_image(subreddit, title, topic["image"])
        return topic["text"], post_id, post_url, "image"
    else:
        body = content.get("body", "")
        post_id, post_url = reddit_poster.post_text(subreddit, title, body)
        return topic["text"], post_id, post_url, "text"


def bot_loop():
    global _bot_running, _bot_status

    _bot_status = {"state": "running", "message": "Starting up...", "last_post": None}

    try:
        user = reddit_poster.verify_login()
        _bot_status["message"] = f"Logged in as u/{user}"
    except Exception as e:
        _bot_status = {"state": "error", "message": f"Login failed: {e}", "last_post": None}
        _bot_running = False
        return

    while _bot_running:
        config = load_config()
        today = get_today()
        target = _target_posts_for(today, config)
        log = load_log()
        posts_done = get_posts_today(log)

        # check scheduled posts regardless of schedule window
        try:
            scheduled_count = check_scheduled_posts(config, log)
            if scheduled_count:
                posts_done += scheduled_count
                _bot_status["message"] = f"Posted {scheduled_count} scheduled post(s)"
                log = load_log()
        except Exception:
            pass

        if not is_within_schedule(config):
            _bot_status["message"] = f"Outside schedule. Waiting... ({posts_done}/{target} today)"
            _sleep_check(60)
            continue

        if posts_done >= target:
            _bot_status["message"] = f"All {target} posts done for today. Waiting for tomorrow."
            _sleep_check(300)
            continue

        topics = load_topics()
        topic_line = pick_topic(topics, log)
        if not topic_line:
            _bot_status["message"] = "No topics available. Add some in the panel."
            _sleep_check(60)
            continue

        subreddit = pick_subreddit(config, log)
        _bot_status["message"] = f"Posting {posts_done + 1}/{target} to r/{subreddit}..."

        try:
            topic_text, post_id, post_url, post_type = do_post(subreddit, topic_line, config)
            log = load_log()
            today = get_today()
            if today not in log:
                log[today] = {}
            if subreddit not in log[today]:
                log[today][subreddit] = []
            log[today][subreddit].append({
                "topic": topic_text,
                "post_id": post_id,
                "url": post_url,
                "type": post_type,
                "time": datetime.now().strftime("%H:%M:%S"),
            })
            save_log(log)
            posts_done += 1
            _bot_status["message"] = f"Posted to r/{subreddit} ({posts_done}/{target})"
            _bot_status["last_post"] = {
                "subreddit": subreddit, "topic": topic_text,
                "url": post_url, "time": datetime.now().strftime("%H:%M")
            }
        except Exception as e:
            _bot_status["message"] = f"Failed posting to r/{subreddit}: {e}"

        # compute delay
        now = datetime.now()
        end_min = config["schedule"]["end_hour"] * 60
        now_min = now.hour * 60 + now.minute
        remaining_min = max(end_min - now_min, 30)
        remaining_posts = max(target - posts_done, 1)
        avg_gap = remaining_min / remaining_posts
        lo = max(int(avg_gap * 0.5), 15)
        hi = max(int(avg_gap * 1.5), lo + 10)
        delay = random.randint(lo, hi)
        _bot_status["message"] += f" — next in ~{delay}m"
        _sleep_check(delay * 60)

    _bot_status = {"state": "stopped", "message": "Bot stopped", "last_post": _bot_status.get("last_post")}


def _sleep_check(seconds):
    """Sleep in small chunks so we can stop quickly."""
    for _ in range(int(seconds)):
        if not _bot_running:
            return
        time.sleep(1)


# ─── routes ───

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    log = load_log()
    config = load_config()
    today = get_today()
    today_data = log.get(today, {})
    target = _target_posts_for(today, config)
    posts_done = get_posts_today(log)

    all_posts = []
    for sub, posts in today_data.items():
        for p in posts:
            all_posts.append({**p, "subreddit": sub})
    all_posts.sort(key=lambda x: x["time"], reverse=True)

    return jsonify({
        "bot": _bot_status,
        "bot_running": _bot_running,
        "today": today,
        "posts_done": posts_done,
        "target": target,
        "posts": all_posts,
    })


@app.route("/api/config")
def api_get_config():
    config = load_config()
    env_status = get_env_status()
    topics = load_topics()
    return jsonify({"config": config, "env_status": env_status, "topics": topics})


@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.json
    config = load_config()
    if "ai_provider" in data:
        config["ai_provider"] = data["ai_provider"]
    if "min_posts_per_day" in data:
        config["min_posts_per_day"] = int(data["min_posts_per_day"])
    if "max_posts_per_day" in data:
        config["max_posts_per_day"] = int(data["max_posts_per_day"])
    if "schedule" in data:
        for k, v in data["schedule"].items():
            config["schedule"][k] = int(v)
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/credentials", methods=["POST"])
def api_save_credentials():
    data = request.json
    for key, value in data.items():
        if value:
            save_env_value(key, value)
    return jsonify({"ok": True, "env_status": get_env_status()})


@app.route("/api/subreddits", methods=["POST"])
def api_add_subreddit():
    data = request.json
    name = data.get("name", "").strip().lower()
    if not name:
        return jsonify({"error": "Empty name"}), 400
    config = load_config()
    if name not in config["subreddits"]:
        config["subreddits"].append(name)
        save_config(config)
    return jsonify({"ok": True, "subreddits": config["subreddits"]})


@app.route("/api/subreddits/<name>", methods=["DELETE"])
def api_remove_subreddit(name):
    config = load_config()
    config["subreddits"] = [s for s in config["subreddits"] if s != name]
    save_config(config)
    return jsonify({"ok": True, "subreddits": config["subreddits"]})


@app.route("/api/topics", methods=["POST"])
def api_add_topic():
    data = request.json
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "Empty topic"}), 400
    topics = load_topics()
    topics.append(topic)
    save_topics(topics)
    return jsonify({"ok": True, "topics": topics})


@app.route("/api/topics/<int:index>", methods=["DELETE"])
def api_remove_topic(index):
    topics = load_topics()
    if 0 <= index < len(topics):
        topics.pop(index)
        save_topics(topics)
    return jsonify({"ok": True, "topics": topics})


@app.route("/api/bot/start", methods=["POST"])
def api_start_bot():
    global _bot_thread, _bot_running
    if _bot_running:
        return jsonify({"error": "Bot is already running"}), 400
    _bot_running = True
    _bot_thread = threading.Thread(target=bot_loop, daemon=True)
    _bot_thread.start()
    return jsonify({"ok": True})


@app.route("/api/bot/stop", methods=["POST"])
def api_stop_bot():
    global _bot_running
    _bot_running = False
    return jsonify({"ok": True})


@app.route("/api/post-now", methods=["POST"])
def api_post_now():
    data = request.json
    subreddit = data.get("subreddit", "").strip()
    config = load_config()
    if not subreddit:
        subreddit = pick_subreddit(config, load_log())

    topics = load_topics()
    log = load_log()
    topic_line = pick_topic(topics, log)
    if not topic_line:
        return jsonify({"error": "No topics available"}), 400

    try:
        topic_text, post_id, post_url, post_type = do_post(subreddit, topic_line, config)
        today = get_today()
        if today not in log:
            log[today] = {}
        if subreddit not in log[today]:
            log[today][subreddit] = []
        log[today][subreddit].append({
            "topic": topic_text, "post_id": post_id,
            "url": post_url, "type": post_type,
            "time": datetime.now().strftime("%H:%M:%S"),
        })
        save_log(log)
        return jsonify({"ok": True, "subreddit": subreddit, "topic": topic_text, "url": post_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/verify-login", methods=["POST"])
def api_verify_login():
    try:
        user = reddit_poster.verify_login()
        return jsonify({"ok": True, "username": user})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─── scheduled posts routes ───

@app.route("/api/scheduled")
def api_get_scheduled():
    items = load_scheduled()
    return jsonify({"scheduled": items})


@app.route("/api/scheduled", methods=["POST"])
def api_add_scheduled():
    data = request.json
    topic = data.get("topic", "").strip()
    subreddit = data.get("subreddit", "").strip().lower()
    scheduled_at = data.get("scheduled_at", "")
    if not topic or not subreddit or not scheduled_at:
        return jsonify({"error": "topic, subreddit, and scheduled_at are required"}), 400
    item = {
        "id": str(uuid.uuid4())[:8],
        "topic": topic,
        "subreddit": subreddit,
        "scheduled_at": scheduled_at,
        "created_at": datetime.now().isoformat(),
        "status": "pending",
    }
    items = load_scheduled()
    items.append(item)
    save_scheduled(items)
    return jsonify({"ok": True, "scheduled": items})


@app.route("/api/scheduled/<item_id>", methods=["DELETE"])
def api_cancel_scheduled(item_id):
    items = load_scheduled()
    items = [i for i in items if i["id"] != item_id]
    save_scheduled(items)
    return jsonify({"ok": True, "scheduled": items})


@app.route("/api/scheduled/clear-done", methods=["POST"])
def api_clear_done_scheduled():
    items = load_scheduled()
    items = [i for i in items if i.get("status") == "pending"]
    save_scheduled(items)
    return jsonify({"ok": True, "scheduled": items})


# ─── commenting routes ───

@app.route("/api/comment/preview", methods=["POST"])
def api_comment_preview():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400
    try:
        post_info = reddit_poster.get_post_info(url)
        config = load_config()
        comment_text = content_generator.generate_comment(post_info, config["ai_provider"])
        return jsonify({"ok": True, "post_info": post_info, "comment": comment_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/comment/post", methods=["POST"])
def api_comment_post():
    data = request.json
    url = data.get("url", "").strip()
    comment_body = data.get("comment", "").strip()
    if not url or not comment_body:
        return jsonify({"error": "URL and comment are required"}), 400
    try:
        comment_id, comment_url = reddit_poster.post_comment(url, comment_body)
        return jsonify({"ok": True, "comment_id": comment_id, "comment_url": comment_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
