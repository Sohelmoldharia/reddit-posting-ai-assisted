import math
import os
import time
import random
from pathlib import Path

STATE_DIR = Path("browser_data")
_mouse_pos = [300, 400]


def _stealth_args():
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _headless_ctx(p):
    return p.chromium.launch_persistent_context(
        str(STATE_DIR),
        headless=True,
        viewport={"width": 1280, "height": 800},
        args=_stealth_args(),
    )


# ─── human mouse & keyboard ───

def _bezier(t, p0, p1, p2):
    return (
        (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
        (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1],
    )


def _human_move(page, x, y):
    sx, sy = _mouse_pos
    dx, dy = x - sx, y - sy
    dist = math.hypot(dx, dy) or 1

    mx, my = (sx + x) / 2, (sy + y) / 2
    perp = random.uniform(-0.35, 0.35) * dist
    cx = mx + (-dy / dist) * perp
    cy = my + (dx / dist) * perp

    steps = max(int(dist / 12), 8) + random.randint(-2, 4)
    for i in range(steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)
        px, py = _bezier(t, (sx, sy), (cx, cy), (x, y))
        px += random.gauss(0, 0.8)
        py += random.gauss(0, 0.8)
        page.mouse.move(px, py)
        speed = random.uniform(0.004, 0.016)
        if t < 0.15 or t > 0.85:
            speed *= 2
        time.sleep(speed)

    _mouse_pos[0], _mouse_pos[1] = x, y


def _human_click(page, el):
    box = el.bounding_box()
    if not box:
        el.click()
        return
    x = box["x"] + box["width"] * random.uniform(0.2, 0.8)
    y = box["y"] + box["height"] * random.uniform(0.25, 0.75)
    _human_move(page, x, y)
    time.sleep(random.uniform(0.04, 0.12))
    page.mouse.click(x, y)


def _human_type(page, el, text):
    _human_click(page, el)
    time.sleep(random.uniform(0.15, 0.4))

    if len(text) <= 120:
        for char in text:
            page.keyboard.type(char)
            d = random.uniform(0.025, 0.09)
            if char in " \n":
                d += random.uniform(0.02, 0.08)
            if char in ".,!?":
                d += random.uniform(0.04, 0.15)
            if random.random() < 0.03:
                d += random.uniform(0.2, 0.6)
            if random.random() < 0.12:
                d *= 0.3
            time.sleep(d)
    else:
        pos = 0
        while pos < len(text):
            chunk = random.randint(2, 6)
            page.keyboard.type(text[pos : pos + chunk])
            pos += chunk
            d = random.uniform(0.04, 0.14)
            end_char = text[min(pos - 1, len(text) - 1)]
            if end_char in " \n.!?,":
                d += random.uniform(0.05, 0.2)
            if random.random() < 0.05:
                d += random.uniform(0.3, 0.8)
            time.sleep(d)


def _idle_pause():
    time.sleep(random.uniform(0.6, 2.0))


def _reset_mouse():
    _mouse_pos[0] = random.randint(200, 600)
    _mouse_pos[1] = random.randint(150, 400)


# ─── login / session ───

def open_login_browser():
    """Open a visible browser for user to log in to Reddit. Blocks until closed."""
    from playwright.sync_api import sync_playwright

    STATE_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(STATE_DIR),
            headless=False,
            viewport={"width": 1100, "height": 750},
            args=_stealth_args(),
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.reddit.com/login")
        try:
            page.wait_for_event("close", timeout=600000)
        except Exception:
            pass
        context.close()


def is_session_saved():
    return STATE_DIR.exists() and any(STATE_DIR.iterdir())


def verify_login():
    """Check if saved session is logged in, return username."""
    from playwright.sync_api import sync_playwright

    if not is_session_saved():
        raise Exception("No browser session. Click 'Open Browser' to log in first.")

    with sync_playwright() as p:
        context = _headless_ctx(p)
        page = context.new_page()
        try:
            page.goto("https://old.reddit.com", timeout=20000)
            page.wait_for_load_state("domcontentloaded")
            user_el = page.query_selector("span.user a")
            if user_el:
                name = user_el.text_content().strip()
                if name and name != "login" and name != "register":
                    return name
            raise Exception("Not logged in. Click 'Open Browser' to log in.")
        finally:
            context.close()


# ─── posting ───

def post_text(subreddit, title, body):
    """Submit a text post via old.reddit.com with human-like behavior."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = _headless_ctx(p)
        page = context.new_page()
        _reset_mouse()
        try:
            page.goto(
                f"https://old.reddit.com/r/{subreddit}/submit?selftext=true",
                timeout=20000,
            )
            page.wait_for_load_state("domcontentloaded")
            _idle_pause()

            title_el = page.wait_for_selector('textarea[name="title"]', timeout=10000)
            _human_type(page, title_el, title)
            _idle_pause()

            text_el = page.query_selector('textarea[name="text"]')
            if text_el and body:
                _human_type(page, text_el, body)
            _idle_pause()

            submit_btn = page.query_selector('button[name="submit"]')
            if submit_btn:
                _human_click(page, submit_btn)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            time.sleep(2)

            url = page.url
            post_id = ""
            if "/comments/" in url:
                post_id = url.split("/comments/")[1].split("/")[0]
            return post_id, url
        finally:
            context.close()


def post_image(subreddit, title, image_path):
    """Submit an image post via old.reddit.com with human-like behavior."""
    from playwright.sync_api import sync_playwright

    abs_path = os.path.abspath(image_path)
    with sync_playwright() as p:
        context = _headless_ctx(p)
        page = context.new_page()
        _reset_mouse()
        try:
            page.goto(
                f"https://old.reddit.com/r/{subreddit}/submit",
                timeout=20000,
            )
            page.wait_for_load_state("domcontentloaded")
            _idle_pause()

            title_el = page.wait_for_selector('textarea[name="title"]', timeout=10000)
            _human_type(page, title_el, title)
            _idle_pause()

            file_input = page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(abs_path)
                _idle_pause()

            submit_btn = page.query_selector('button[name="submit"]')
            if submit_btn:
                _human_click(page, submit_btn)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(2)

            url = page.url
            post_id = ""
            if "/comments/" in url:
                post_id = url.split("/comments/")[1].split("/")[0]
            return post_id, url
        finally:
            context.close()


def post_comment(post_url, comment_body):
    """Comment on a post via old.reddit.com with human-like behavior."""
    from playwright.sync_api import sync_playwright

    old_url = post_url.replace("www.reddit.com", "old.reddit.com")
    if "old.reddit.com" not in old_url:
        old_url = old_url.replace("reddit.com", "old.reddit.com")

    with sync_playwright() as p:
        context = _headless_ctx(p)
        page = context.new_page()
        _reset_mouse()
        try:
            page.goto(old_url, timeout=20000)
            page.wait_for_load_state("domcontentloaded")
            _idle_pause()

            comment_box = page.query_selector('textarea[name="text"]')
            if comment_box:
                _human_type(page, comment_box, comment_body)
                _idle_pause()
                save_btn = page.query_selector('button[type="submit"]')
                if save_btn:
                    _human_click(page, save_btn)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    time.sleep(2)

            return "", page.url
        finally:
            context.close()


# ─── scraping (no interaction needed) ───

def get_post_info(url):
    """Scrape post info from old.reddit.com for comment generation."""
    from playwright.sync_api import sync_playwright

    old_url = url.replace("www.reddit.com", "old.reddit.com")
    if "old.reddit.com" not in old_url:
        old_url = old_url.replace("reddit.com", "old.reddit.com")

    with sync_playwright() as p:
        context = _headless_ctx(p)
        page = context.new_page()
        try:
            page.goto(old_url, timeout=20000)
            page.wait_for_load_state("domcontentloaded")

            title_el = page.query_selector("a.title.may-blank")
            title = title_el.text_content().strip() if title_el else ""

            body_el = page.query_selector("div.expando div.usertext-body div.md")
            body = body_el.text_content().strip()[:1000] if body_el else ""

            sub_el = page.query_selector("span.hover.pagename a")
            subreddit = sub_el.text_content().strip() if sub_el else ""

            score_el = page.query_selector("div.score span.number")
            score = 0
            if score_el:
                try:
                    score = int(score_el.text_content().strip().replace(",", ""))
                except ValueError:
                    pass

            num_comments = 0
            comments_link = page.query_selector("a.bylink.comments")
            if comments_link:
                txt = comments_link.text_content().strip()
                try:
                    num_comments = int(txt.split()[0].replace(",", ""))
                except (ValueError, IndexError):
                    pass

            top_comments = []
            comment_els = page.query_selector_all(
                "div.entry div.usertext-body div.md"
            )
            for c_body in comment_els[1:9]:
                cbody = c_body.text_content().strip()[:300]
                if cbody:
                    top_comments.append(
                        {"author": "user", "body": cbody, "score": 0}
                    )

            return {
                "title": title,
                "body": body,
                "subreddit": subreddit,
                "score": score,
                "num_comments": num_comments,
                "top_comments": top_comments,
            }
        finally:
            context.close()


def get_recent_titles(subreddit, limit=10):
    """Scrape recent post titles from a subreddit."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = _headless_ctx(p)
        page = context.new_page()
        try:
            page.goto(
                f"https://old.reddit.com/r/{subreddit}", timeout=20000
            )
            page.wait_for_load_state("domcontentloaded")
            titles = page.eval_on_selector_all(
                "a.title.may-blank",
                f"els => els.slice(0, {limit}).map(e => e.textContent)",
            )
            return titles
        finally:
            context.close()
