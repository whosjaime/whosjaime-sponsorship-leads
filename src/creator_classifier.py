from __future__ import annotations

import re
from collections import Counter

from sponsor_models import ChannelRecord, VideoRecord


GENRE_KEYWORDS = {
    "Gaming": {
        "gaming", "gamer", "gameplay", "minecraft", "fortnite", "roblox", "valorant",
        "call of duty", "warzone", "gta", "pokemon", "nintendo", "xbox", "playstation",
        "steam", "esports", "speedrun",
    },
    "Tech": {
        "tech", "technology", "iphone", "android", "computer", "pc build", "laptop",
        "software", "ai", "artificial intelligence", "coding", "developer", "gadgets",
    },
    "Finance": {
        "finance", "investing", "stocks", "stock market", "credit card", "banking",
        "money", "crypto", "personal finance", "real estate investing",
    },
    "Business": {
        "business", "entrepreneur", "startup", "marketing", "ecommerce", "e-commerce",
        "sales", "founder", "saas", "agency",
    },
    "Beauty": {"beauty", "makeup", "skincare", "cosmetics", "get ready with me", "grwm"},
    "Fashion": {"fashion", "outfit", "clothing", "streetwear", "style", "haul"},
    "Fitness": {"fitness", "workout", "gym", "bodybuilding", "running", "training", "lifting"},
    "Health": {"health", "wellness", "nutrition", "medical", "doctor", "mental health"},
    "Food": {"food", "cooking", "recipe", "chef", "restaurant", "baking", "meal prep"},
    "Travel": {"travel", "travelling", "traveling", "vacation", "hotel", "flight", "tourism"},
    "Sports": {
        "sports", "football", "soccer", "basketball", "baseball", "hockey", "golf",
        "tennis", "mma", "boxing", "ufc", "nfl", "nba", "nhl", "mlb",
    },
    "Automotive": {"car", "cars", "automotive", "supercar", "truck", "motorcycle", "racing"},
    "Family": {"family", "family vlog", "mom", "dad", "parenting", "kids", "children"},
    "Comedy": {"comedy", "funny", "skit", "parody", "prank", "comedian", "humor"},
    "Entertainment": {"entertainment", "challenge", "challenges", "vlog", "reaction", "storytime", "creator", "youtube", "viral"},
    "Education": {"education", "educational", "tutorial", "learn", "explained", "science", "history", "study"},
    "Music": {"music", "musician", "singer", "rapper", "producer", "song", "album"},
    "Home": {"home", "interior", "decor", "renovation", "diy", "woodworking", "cleaning"},
    "Outdoors": {"outdoors", "camping", "hiking", "fishing", "hunting", "survival"},
    "Pets": {"pet", "pets", "dog", "dogs", "cat", "cats", "animal", "animals"},
}

CATEGORY_ID_HINTS = {
    "1": "Entertainment", "2": "Automotive", "10": "Music", "15": "Pets", "17": "Sports",
    "19": "Travel", "20": "Gaming", "22": "Entertainment", "23": "Comedy", "24": "Entertainment",
    "25": "Entertainment", "26": "Lifestyle", "27": "Education", "28": "Tech",
}

TAG_KEYWORDS = {
    "Minecraft": {"minecraft"}, "Fortnite": {"fortnite"}, "Roblox": {"roblox"},
    "Family Friendly": {"family friendly", "family-friendly", "kid friendly", "kid-friendly"},
    "Challenges": {"challenge", "challenges"}, "Pranks": {"prank", "pranks"},
    "Comedy": {"comedy", "funny", "skit", "humor"}, "Reactions": {"reaction", "reacts", "reacting"},
    "Long Form": {"documentary", "episode", "full video", "long form", "long-form"},
    "Short Form": {"shorts", "short form", "short-form", "tiktok", "reels"},
    "Tech": {"tech", "technology", "software", "ai", "gadgets"},
    "Lifestyle": {"lifestyle", "vlog", "day in my life"},
}


def _clean_topic(topic: str) -> str:
    value = topic.rsplit("/", 1)[-1]
    value = value.replace("_", " ").replace("%20", " ")
    return re.sub(r"\s+", " ", value).strip().lower()


def _contains(text: str, phrase: str) -> bool:
    if " " in phrase or "-" in phrase:
        return phrase in text
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def classify_creator(video: VideoRecord, channel: ChannelRecord | None) -> tuple[str, list[str]]:
    pieces = [video.title, video.description, " ".join(video.tags)]
    if channel:
        pieces.extend([channel.title, channel.description])
        pieces.extend(_clean_topic(topic) for topic in channel.topic_categories)
    pieces.extend(_clean_topic(topic) for topic in video.topic_categories)
    text = " ".join(pieces).lower()

    scores: Counter[str] = Counter()
    for genre, keywords in GENRE_KEYWORDS.items():
        for keyword in keywords:
            if _contains(text, keyword):
                scores[genre] += 2

    hinted = CATEGORY_ID_HINTS.get(video.category_id)
    if hinted:
        scores[hinted] += 3

    topic_text = " ".join(_clean_topic(topic) for topic in (video.topic_categories + (channel.topic_categories if channel else [])))
    for genre in GENRE_KEYWORDS:
        if genre.lower() in topic_text:
            scores[genre] += 5

    primary = scores.most_common(1)[0][0] if scores else "Other"
    tags: list[str] = []
    for tag, keywords in TAG_KEYWORDS.items():
        if any(_contains(text, keyword) for keyword in keywords):
            tags.append(tag)
    if primary not in tags and primary != "Other":
        tags.insert(0, primary)
    return primary, tags[:8]
