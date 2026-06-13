import os
import time
import random
from pathlib import Path

STATE_DIR = Path("browser_data")


def _stealth_args():
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]


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
        context = p.chromium.launch_persistent_context(
            str(STATE_DIR), headless=True, args=_stealth_args(),
        )
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


def _human_delay():
    time.sleep(random.uniform(0.3, 1.2))


def post_text(subreddit, title, body):
    """Submit a text post via old.reddit.com form."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(STATE_DIR), headless=True, args=_stealth_args(),
        )
        page = context.new_page()
        try:
            page.goto(
                f"https://old.reddit.com/r/{subreddit}/submit?selftext=true",
                timeout=20000,
            )
            page.wait_for_load_state("domcontentloaded")

            page.wait_for_selector('textarea[name="title"]', timeout=10000)
            _human_delay()
            page.fill('textarea[name="title"]', title)
            _human_delay()

            text_area = page.query_selector('textarea[name="text"]')
            if text_area:
                text_area.fill(body)
            _human_delay()

            page.click('button[name="submit"]')
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
    """Submit an image post via old.reddit.com."""
    from playwright.sync_api import sync_playwright

    abs_path = os.path.abspath(image_path)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(STATE_DIR), headless=True, args=_stealth_args(),
        )
        page = context.new_page()
        try:
            page.goto(
                f"https://old.reddit.com/r/{subreddit}/submit",
                timeout=20000,
            )
            page.wait_for_load_state("domcontentloaded")

            page.wait_for_selector('textarea[name="title"]', timeout=10000)
            _human_delay()
            page.fill('textarea[name="title"]', title)
            _human_delay()

            file_input = page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(abs_path)
                _human_delay()

            page.click('button[name="submit"]')
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
    """Comment on a post via old.reddit.com."""
    from playwright.sync_api import sync_playwright

    old_url = post_url.replace("www.reddit.com", "old.reddit.com")
    if "old.reddit.com" not in old_url:
        old_url = old_url.replace("reddit.com", "old.reddit.com")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(STATE_DIR), headless=True, args=_stealth_args(),
        )
        page = context.new_page()
        try:
            page.goto(old_url, timeout=20000)
            page.wait_for_load_state("domcontentloaded")
            _human_delay()

            comment_box = page.query_selector('textarea[name="text"]')
            if comment_box:
                comment_box.fill(comment_body)
                _human_delay()
                save_btn = page.query_selector('button[type="submit"]')
                if save_btn:
                    save_btn.click()
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    time.sleep(2)

            return "", page.url
        finally:
            context.close()


def get_post_info(url):
    """Scrape post info from old.reddit.com for comment generation."""
    from playwright.sync_api import sync_playwright

    old_url = url.replace("www.reddit.com", "old.reddit.com")
    if "old.reddit.com" not in old_url:
        old_url = old_url.replace("reddit.com", "old.reddit.com")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(STATE_DIR), headless=True, args=_stealth_args(),
        )
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
            comment_els = page.query_selector_all("div.entry div.usertext-body div.md")
            for c_body in comment_els[1:9]:
                cbody = c_body.text_content().strip()[:300]
                if cbody:
                    top_comments.append({"author": "user", "body": cbody, "score": 0})

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
        context = p.chromium.launch_persistent_context(
            str(STATE_DIR), headless=True, args=_stealth_args(),
        )
        page = context.new_page()
        try:
            page.goto(f"https://old.reddit.com/r/{subreddit}", timeout=20000)
            page.wait_for_load_state("domcontentloaded")
            titles = page.eval_on_selector_all(
                "a.title.may-blank",
                f"els => els.slice(0, {limit}).map(e => e.textContent)",
            )
            return titles
        finally:
            context.close()
