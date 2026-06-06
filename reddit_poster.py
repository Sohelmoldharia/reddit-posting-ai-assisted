import os
import praw


def _get_reddit():
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        username=os.getenv("REDDIT_USERNAME"),
        password=os.getenv("REDDIT_PASSWORD"),
        user_agent=f"RedditPoster/1.0 by u/{os.getenv('REDDIT_USERNAME', 'bot')}",
    )


def post_text(subreddit_name, title, body):
    reddit = _get_reddit()
    subreddit = reddit.subreddit(subreddit_name)
    submission = subreddit.submit(title=title, selftext=body)
    return submission.id, submission.url


def post_image(subreddit_name, title, image_path):
    reddit = _get_reddit()
    subreddit = reddit.subreddit(subreddit_name)
    submission = subreddit.submit_image(title=title, image_path=image_path)
    return submission.id, submission.url


def get_recent_titles(subreddit_name, limit=10):
    """Pull recent non-stickied post titles so the AI can match the community's voice."""
    reddit = _get_reddit()
    subreddit = reddit.subreddit(subreddit_name)
    titles = []
    for post in subreddit.hot(limit=limit + 6):
        if post.stickied:
            continue
        titles.append(post.title)
        if len(titles) >= limit:
            break
    return titles


def get_post_info(url):
    """Fetch a post's title, body, subreddit, and top comments for context."""
    reddit = _get_reddit()
    submission = reddit.submission(url=url)
    submission.comments.replace_more(limit=0)
    top_comments = []
    for c in submission.comments[:8]:
        top_comments.append({"author": str(c.author), "body": c.body[:300], "score": c.score})
    return {
        "title": submission.title,
        "body": submission.selftext[:1000] if submission.selftext else "",
        "subreddit": str(submission.subreddit),
        "score": submission.score,
        "num_comments": submission.num_comments,
        "top_comments": top_comments,
    }


def post_comment(url, comment_body):
    reddit = _get_reddit()
    submission = reddit.submission(url=url)
    comment = submission.reply(comment_body)
    return comment.id, f"https://reddit.com{comment.permalink}"


def verify_login():
    reddit = _get_reddit()
    user = reddit.user.me()
    return user.name
