import os
import json
import random
import re


TITLE_STYLES = ["question", "statement", "observation", "discussion", "story"]

STYLE_INSTRUCTIONS = {
    "question": "Open by asking a real question or sharing genuine curiosity about the topic.",
    "statement": "Open with a direct take or opinion. Don't hedge it.",
    "observation": "Open with something you noticed or ran into related to the topic.",
    "discussion": "Frame it as wanting to hear how other people see this.",
    "story": "Open with a quick personal anecdote or something that just happened.",
}

LENGTH_TARGETS = [
    "Keep it to 1-2 sentences. Short and off the cuff.",
    "Keep it short, three or four sentences at most.",
    "A normal-sized post, one solid paragraph.",
    "A bit longer, two short paragraphs.",
]

SYSTEM_PROMPT = """You are a regular Reddit user writing a post. You are NOT an AI assistant and you are NOT writing an article. You're just a person sharing a thought.

How real people write on Reddit:
- Casual and a little messy. Sentence fragments are fine. Starting mid-thought is fine.
- Vary sentence length a lot. Some very short. Some run on a bit.
- Have an actual opinion. Don't water everything down with "I think" or "in my opinion".
- Contractions always (don't, can't, it's, gonna, kinda). Lowercase is fine.

NEVER do these (they scream AI):
- The words: delve, crucial, landscape, paradigm, leverage, furthermore, comprehensive, utilize, innovative, streamline, robust, synergy, game-changer, cutting-edge, tapestry, testament, realm, navigate, foster, underscore.
- Em dashes (—). Use a comma or just a period.
- The "it's not just X, it's Y" construction.
- "Here's the thing", "Let's be honest", "Honestly," as an opener.
- Listing things in perfect threes.
- A neat little summary/wrap-up sentence at the end.
- Canned endings like "Let me know your thoughts!" or "What are your thoughts on this?"
- Markdown: no bold, no headers, no bullet lists unless it genuinely fits.
- Emojis. Hashtags. Exclamation-point spam.
- Titles where Every Word Is Capitalized like a headline.

Just sound like a person who cares about the topic and is typing quickly."""


def _build_examples_block(subreddit, example_titles):
    if not example_titles:
        return (
            f"\n\nThis subreddit (r/{subreddit}) is new or has few posts. "
            "Write a title and post that would fit a growing community. "
            "Keep it welcoming and conversational.\n"
        )
    sample = "\n".join(f"- {t}" for t in example_titles[:8])
    return (
        f"\n\nHere are real recent titles from r/{subreddit}. Match this community's "
        f"vibe, format and length. Do NOT copy them:\n{sample}\n"
    )


def _build_prompt(topic, subreddit, style, length, example_titles):
    examples = _build_examples_block(subreddit, example_titles)
    return f"""Write a Reddit post for r/{subreddit}.

The keyword/topic is: {topic}

IMPORTANT: The title MUST include the keyword "{topic}" (or a very close natural variation of it). Work it into the title naturally, don't force it awkwardly.

{STYLE_INSTRUCTIONS[style]}
{length}

The title should look like something a real person in r/{subreddit} would type, not a headline.{examples}

Return ONLY valid JSON with exactly two fields:
{{"title": "...", "body": "..."}}"""


def _build_image_prompt(topic, subreddit, example_titles):
    examples = _build_examples_block(subreddit, example_titles)
    return f"""Write a short Reddit title for an image post in r/{subreddit}.

The keyword/topic is: {topic}

IMPORTANT: The title MUST include the keyword "{topic}" naturally.

It should read like a natural caption, short and casual.{examples}

Return ONLY valid JSON:
{{"title": "..."}}"""


# --- post-processing: scrub the mechanical AI tells out of the output ---

AI_SIGNOFFS = [
    r"\s*let me know (what you think|your thoughts).*$",
    r"\s*(i'?d|i would) love to hear.*$",
    r"\s*what (are|do) (your|you all|you guys) think.*$",
    r"\s*curious (to hear|what).*$",
    r"\s*interested to hear.*$",
]


def _scrub(text):
    if not text:
        return text
    # straighten smart punctuation
    text = (text.replace("’", "'").replace("‘", "'")
                .replace("“", '"').replace("”", '"')
                .replace("…", "..."))
    # em / en dashes -> something a human would actually type
    text = re.sub(r"\s*[—–]\s*", lambda m: random.choice([", ", " - ", " "]), text)
    # strip markdown
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    # drop canned sign-offs
    for pat in AI_SIGNOFFS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    # tidy whitespace
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


PROPER_CAPS = {
    "ai": "AI", "vr": "VR", "ar": "AR", "gpu": "GPU", "cpu": "CPU",
    "iphone": "iPhone", "ipad": "iPad", "ios": "iOS", "macos": "macOS",
    "youtube": "YouTube", "chatgpt": "ChatGPT", "openai": "OpenAI",
    "nasa": "NASA", "nfl": "NFL", "nba": "NBA", "ufc": "UFC", "mlb": "MLB",
    "usa": "USA", "uk": "UK", "eu": "EU", "un": "UN",
    "ps5": "PS5", "ps4": "PS4", "xbox": "Xbox", "pc": "PC",
    "covid": "COVID", "adhd": "ADHD",
    "usb": "USB", "hdmi": "HDMI", "wifi": "WiFi",
    "api": "API", "html": "HTML", "css": "CSS",
    "amd": "AMD", "intel": "Intel", "nvidia": "Nvidia",
    "tesla": "Tesla", "spacex": "SpaceX", "google": "Google",
    "amazon": "Amazon", "microsoft": "Microsoft", "apple": "Apple",
    "netflix": "Netflix", "disney": "Disney", "marvel": "Marvel",
    "dc": "DC", "hbo": "HBO", "spotify": "Spotify", "tiktok": "TikTok",
    "naruto": "Naruto", "anime": "Anime", "manga": "Manga",
    "samsung": "Samsung", "sony": "Sony", "nintendo": "Nintendo",
    "reddit": "Reddit", "twitter": "Twitter",
}


def _fix_proper_caps(text):
    words = text.split()
    fixed = []
    for w in words:
        stripped = w.strip(".,!?;:'\"()-")
        if stripped.lower() in PROPER_CAPS:
            w = w.replace(stripped, PROPER_CAPS[stripped.lower()])
        fixed.append(w)
    return " ".join(fixed)


def humanize_title(title):
    title = _scrub(title).strip().strip('"').strip()
    if random.random() < 0.35:
        title = title.lower()
    title = _fix_proper_caps(title)
    if title.endswith(".") and random.random() < 0.75:
        title = title[:-1]
    return title


def _parse_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def generate_content(topic, subreddit, provider="openai", is_image=False, example_titles=None):
    style = random.choice(TITLE_STYLES)
    length = random.choice(LENGTH_TARGETS)

    if is_image:
        prompt = _build_image_prompt(topic, subreddit, example_titles)
    else:
        prompt = _build_prompt(topic, subreddit, style, length, example_titles)

    # a little temperature wobble so output isn't uniform
    temperature = round(random.uniform(0.85, 1.0), 2)

    if provider == "openai":
        result = _generate_openai(prompt, temperature)
    elif provider == "anthropic":
        result = _generate_anthropic(prompt, temperature)
    elif provider == "google":
        result = _generate_google(prompt, temperature)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    result["title"] = humanize_title(result["title"])
    if "body" in result:
        result["body"] = _scrub(result["body"])
    return result


def _generate_openai(prompt, temperature):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
    )
    return _parse_response(response.choices[0].message.content)


def _generate_anthropic(prompt, temperature):
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        temperature=temperature,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_response(response.content[0].text)


def _generate_google(prompt, temperature):
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )
    response = model.generate_content(
        prompt,
        generation_config={"temperature": temperature},
    )
    return _parse_response(response.text)


# ─── comment generation ───

COMMENT_SYSTEM = """You are a regular Reddit user leaving a comment on a post. You are NOT an AI. You're just a person reacting to what you read.

How real people comment on Reddit:
- Short and casual, usually 1-3 sentences
- React to something specific in the post, don't just summarize it
- Contractions always. Lowercase fine. Sentence fragments fine.
- Have an opinion. Agree, disagree, add something, ask a follow-up.
- Sometimes just one line is perfect.

NEVER do these:
- Start with "Great post!" or "Thanks for sharing!"
- Use the words: delve, crucial, landscape, insightful, comprehensive
- Use em dashes (—)
- Write a structured response with points or lists
- End with a generic question like "What do you think?"
- Sound like you're writing an essay
- Use emojis

Just sound like a real person who read the post and had a reaction."""


def _build_comment_prompt(post_info):
    comments_ctx = ""
    if post_info.get("top_comments"):
        samples = post_info["top_comments"][:4]
        comments_ctx = "\n\nExisting comments (for context, don't repeat them):\n"
        for c in samples:
            comments_ctx += f"- u/{c['author']}: {c['body'][:150]}\n"

    body_ctx = ""
    if post_info.get("body"):
        body_ctx = f"\n\nPost body:\n{post_info['body'][:500]}"

    return f"""Write a comment on this Reddit post in r/{post_info['subreddit']}:

Title: {post_info['title']}{body_ctx}{comments_ctx}

Write a natural, casual comment. Just the comment text, nothing else. No JSON, no quotes, just the comment."""


def generate_comment(post_info, provider="openai"):
    prompt = _build_comment_prompt(post_info)
    temperature = round(random.uniform(0.85, 1.0), 2)

    if provider == "openai":
        raw = _generate_raw_openai(prompt, COMMENT_SYSTEM, temperature)
    elif provider == "anthropic":
        raw = _generate_raw_anthropic(prompt, COMMENT_SYSTEM, temperature)
    elif provider == "google":
        raw = _generate_raw_google(prompt, COMMENT_SYSTEM, temperature)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return _scrub(raw.strip().strip('"'))


def _generate_raw_openai(prompt, system, temperature):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content


def _generate_raw_anthropic(prompt, system, temperature):
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _generate_raw_google(prompt, system, temperature):
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=system)
    response = model.generate_content(prompt, generation_config={"temperature": temperature})
    return response.text


# ─── auto pilot: AI plans the whole day ───

AUTO_PLAN_SYSTEM = """You are a Reddit community manager planning today's posts.
You will be given trending topics and a list of subreddits.
Match relevant trending topics to subreddits where they'd actually fit.
Not every sub needs a match — skip subs with no good fit.
Pick angles that would genuinely interest that community.
Return valid JSON only."""


def generate_day_plan(trends, subreddits, provider="openai"):
    trends_text = "\n".join(
        f"- {t['keyword']}" + (f" ({t['context']})" if t.get('context') else "")
        for t in trends[:25]
    )
    subs_text = "\n".join(f"- r/{s}" for s in subreddits)

    prompt = f"""Today's trending topics:
{trends_text}

Subreddits to post in:
{subs_text}

For each subreddit, pick the most relevant trending topic and write a specific angle/spin for that community. If no trending topic fits a sub, come up with a general engaging topic that fits it.

Return ONLY a JSON array:
[
  {{"subreddit": "name", "topic": "the keyword or topic", "angle": "specific angle for this sub"}}
]"""

    temperature = 0.7
    if provider == "openai":
        raw = _generate_raw_openai(prompt, AUTO_PLAN_SYSTEM, temperature)
    elif provider == "anthropic":
        raw = _generate_raw_anthropic(prompt, AUTO_PLAN_SYSTEM, temperature)
    elif provider == "google":
        raw = _generate_raw_google(prompt, AUTO_PLAN_SYSTEM, temperature)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return _parse_response(raw)
