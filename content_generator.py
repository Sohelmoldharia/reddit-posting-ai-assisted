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
        return ""
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


def humanize_title(title):
    title = _scrub(title).strip().strip('"').strip()
    # real people often don't capitalize titles at all
    if random.random() < 0.35:
        title = title.lower()
    # and often skip the trailing period
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
