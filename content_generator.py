import os
import json
import random


TITLE_STYLES = [
    "question",
    "statement",
    "observation",
    "discussion",
    "story",
]

SYSTEM_PROMPT = """You write Reddit posts that sound like a real person. You are NOT an AI assistant — you are a regular Reddit user sharing thoughts, asking questions, or starting discussions.

Rules:
- Write casually, like talking to friends online
- Mix short sentences with longer ones
- NEVER use these words: delve, crucial, landscape, paradigm, leverage, furthermore, comprehensive, utilize, innovative, streamline, robust, synergy, game-changer, cutting-edge
- Don't hedge everything with "I think" or "in my opinion" — just say it
- Be slightly opinionated, people engage with takes
- Use simple everyday words
- NO bullet points or numbered lists unless it truly fits
- NO markdown headers or bold text
- NO emojis or excessive punctuation
- Keep the body between 80-250 words
- Sound like you actually care about the topic, not like you're writing a report"""


def _build_prompt(topic, subreddit, style):
    style_instructions = {
        "question": "Start the post by asking a question or sharing curiosity about the topic.",
        "statement": "Start with a direct statement or opinion about the topic.",
        "observation": "Start by sharing something you noticed or experienced related to the topic.",
        "discussion": "Frame this as wanting to hear what others think about the topic.",
        "story": "Start with a brief personal anecdote or something that happened recently related to the topic.",
    }

    return f"""Write a Reddit post for r/{subreddit} about this topic: {topic}

Style: {style_instructions[style]}

The title should feel natural for r/{subreddit} — look at how people actually title posts there. Don't make it clickbait.

Return ONLY valid JSON with exactly two fields:
{{"title": "your title here", "body": "your post body here"}}"""


def _build_image_prompt(topic, subreddit):
    return f"""Write a short Reddit title for an image post in r/{subreddit} about: {topic}

The title should work as a standalone caption for an image. Keep it short and natural.

Return ONLY valid JSON:
{{"title": "your title here"}}"""


def _parse_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def generate_content(topic, subreddit, provider="openai", is_image=False):
    style = random.choice(TITLE_STYLES)

    if is_image:
        prompt = _build_image_prompt(topic, subreddit)
    else:
        prompt = _build_prompt(topic, subreddit, style)

    if provider == "openai":
        return _generate_openai(prompt)
    elif provider == "anthropic":
        return _generate_anthropic(prompt)
    elif provider == "google":
        return _generate_google(prompt)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _generate_openai(prompt):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
    )
    return _parse_response(response.choices[0].message.content)


def _generate_anthropic(prompt):
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_response(response.content[0].text)


def _generate_google(prompt):
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )
    response = model.generate_content(prompt)
    return _parse_response(response.text)
