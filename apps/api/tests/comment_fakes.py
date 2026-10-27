"""A fake YouTube API for the comment crawler tests: one callable with requests.get's signature."""
from datetime import UTC, datetime, timedelta

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
KEY = "TEST-KEY-123"

TOPICS = [
    "gardening", "engines", "pottery", "chess", "baking", "drones", "violins", "surfing", "welding", "origami",
    "archery", "bicycles", "volcanoes", "knitting", "sailing", "robotics", "skiing", "painting", "fishing", "rockets",
    "carpentry", "astronomy", "boxing", "sushi", "tennis", "weather", "tractors", "cheese", "typing", "caves",
]


def english(topic: str, n: int = 0) -> str:
    return f"I really enjoyed the part about {topic} because it was explained so clearly number {n}"


def error(status: int, reason: str) -> "FakeResponse":
    return FakeResponse(status, {"error": {"code": status, "errors": [{"reason": reason}], "message": reason}})


class FakeResponse:
    def __init__(self, status: int = 200, body: dict | None = None):
        self.status_code, self._body = status, body or {}

    def json(self) -> dict:
        return self._body


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def video_item(video_id, channel_id, category="20", views=500, comments=40, age_days=10, kids=False, language="en"):
    statistics = {"viewCount": str(views)}
    if comments is not None:
        statistics["commentCount"] = str(comments)
    return {
        "id": video_id,
        "snippet": {
            "channelId": channel_id, "title": f"Title {video_id}", "categoryId": category,
            "publishedAt": iso(NOW - timedelta(days=age_days)), "defaultLanguage": language,
        },
        "statistics": statistics,
        "status": {"madeForKids": kids},
    }


def thread(comment_id, text, likes=1, replies=0, author="UCauthor1"):
    return {"id": comment_id, "snippet": {
        "videoId": "v", "totalReplyCount": replies,
        "topLevelComment": {"id": comment_id, "snippet": {
            "textDisplay": text, "textOriginal": text, "likeCount": likes,
            "authorDisplayName": "Some Person", "authorProfileImageUrl": "http://img/x", "authorChannelUrl": "http://c/x",
            "authorChannelId": {"value": author},
            "publishedAt": iso(NOW - timedelta(days=1)), "updatedAt": iso(NOW - timedelta(hours=5)),
        }},
    }}


class FakeYouTube:
    """Answers search, videos, channels, playlistItems and commentThreads from dictionaries; records every call."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.search: list[tuple[str, str]] = []  # (video_id, channel_id) returned by every search
        self.videos: dict[str, dict] = {}
        self.charts: dict[str, list[str]] = {}  # category -> video ids
        self.channels: dict[str, dict] = {}  # channel id -> statistics
        self.uploads: dict[str, list[str]] = {}  # channel id -> video ids
        self.threads: dict[str, list[list[dict]]] = {}  # video id -> pages of threads
        self.errors: dict[str, FakeResponse] = {}  # method (or "method:videoId") -> response to give

    def __call__(self, url, params, timeout):
        method = url.rsplit("/", 1)[1]
        assert params["key"] == KEY
        self.calls.append((method, params))
        if response := self.errors.get(f"{method}:{params.get('videoId')}") or self.errors.get(method):
            return response
        return FakeResponse(200, getattr(self, f"_{method}")(params))

    def count(self, method: str) -> int:
        return sum(1 for m, _ in self.calls if m == method)

    def _search(self, params):
        return {"items": [{"id": {"kind": "youtube#video", "videoId": v}, "snippet": {"channelId": c}}
                          for v, c in self.search]}

    def _videos(self, params):
        if params.get("chart"):
            ids = self.charts.get(params["videoCategoryId"], [])
            return {"items": [{"id": i, "snippet": {"channelId": self.videos[i]["snippet"]["channelId"]}}
                              for i in ids]}
        ids = params["id"].split(",")
        assert len(ids) <= 50
        return {"items": [self.videos[i] for i in ids if i in self.videos]}

    def _channels(self, params):
        ids = params["id"].split(",")
        if params["part"] == "contentDetails":
            return {"items": [{"id": i, "contentDetails": {"relatedPlaylists": {"uploads": "UU" + i[2:]}}}
                              for i in ids if i in self.uploads]}
        return {"items": [{"id": i, "statistics": self.channels[i]} for i in ids if i in self.channels]}

    def _playlistItems(self, params):
        channel = "UC" + params["playlistId"][2:]
        return {"items": [{"snippet": {"resourceId": {"videoId": v}}} for v in self.uploads.get(channel, [])]}

    def _commentThreads(self, params):
        pages = self.threads.get(params["videoId"], [[]])
        index = int(params.get("pageToken", "0"))
        body = {"items": pages[index]}
        if index + 1 < len(pages):
            body["nextPageToken"] = str(index + 1)
        return body

    def add_video(self, video_id, channel_id, subscribers=5000, comments_per_page=(20,), **kwargs):
        """Register a video, its channel, and English comments with distinct text."""
        self.videos[video_id] = video_item(video_id, channel_id, **kwargs)
        self.channels.setdefault(channel_id, {"subscriberCount": str(subscribers), "hiddenSubscriberCount": False})
        seed = sum(map(ord, video_id))
        self.threads[video_id] = [
            [thread(f"{video_id}-{p}-{i}", english(TOPICS[(seed + i) % len(TOPICS)], seed * 100 + p * 50 + i))
             for i in range(n)]
            for p, n in enumerate(comments_per_page)
        ]
