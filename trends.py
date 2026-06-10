import json
import requests


def fetch_google_trends(geo="US", count=30):
    """Fetch today's trending searches from Google Trends."""
    url = f"https://trends.google.com/trends/api/dailytrends?hl=en-US&geo={geo}&ns=15"
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    resp = requests.get(url, headers=headers, timeout=15)

    text = resp.text
    if text.startswith(")]}'"):
        text = text[5:]

    data = json.loads(text)
    topics = []
    for day in data.get("default", {}).get("trendingSearchesDays", []):
        for search in day.get("trendingSearches", []):
            title = search.get("title", {}).get("query", "")
            traffic = search.get("formattedTraffic", "")
            articles = search.get("articles", [])
            snippet = articles[0].get("title", "") if articles else ""
            if title:
                topics.append({
                    "keyword": title,
                    "traffic": traffic,
                    "context": snippet,
                })
            if len(topics) >= count:
                break
    return topics
