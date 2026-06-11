import json
import requests


def fetch_google_trends(geo="US", count=30):
    """Fetch today's trending searches from Google Trends."""
    errors = []

    # Method 1: Daily trends API
    try:
        url = f"https://trends.google.com/trends/api/dailytrends?hl=en-US&geo={geo}&ns=15"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
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
                    topics.append({"keyword": title, "traffic": traffic, "context": snippet})
                if len(topics) >= count:
                    break
        if topics:
            return topics
    except Exception as e:
        errors.append(f"Daily API: {e}")

    # Method 2: RSS feed
    try:
        url = f"https://trends.google.com/trending/rss?geo={geo}"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)
        topics = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                topics.append({"keyword": title_el.text, "traffic": "", "context": ""})
        if topics:
            return topics[:count]
    except Exception as e:
        errors.append(f"RSS: {e}")

    # Method 3: pytrends library
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US")
        geo_map = {"US": "united_states", "GB": "united_kingdom", "IN": "india",
                    "CA": "canada", "AU": "australia"}
        pn = geo_map.get(geo, "united_states")
        df = pytrends.trending_searches(pn=pn)
        topics = [{"keyword": kw, "traffic": "", "context": ""} for kw in df[0].tolist()]
        if topics:
            return topics[:count]
    except Exception as e:
        errors.append(f"pytrends: {e}")

    raise RuntimeError(f"All trend sources failed: {'; '.join(errors)}")
