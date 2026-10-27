"""Comment text: one cleaning function, shared by building the training corpus and by scoring new comments.

Everything here is pure (text in, value out) so that training and serving cannot drift apart. A model trained on
text cleaned one way and fed text cleaned another way silently loses accuracy, so `clean_comment` is the only place
that defines "what a comment looks like to the model".
"""
import hashlib
import re

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

MIN_WORDS = 3
MIN_ENGLISH_PROBABILITY = 0.8
USER_TOKEN = "@user"
URL_TOKEN = "<url>"

# langdetect is randomised; with a fixed seed the same text always gets the same answer.
DetectorFactory.seed = 0

_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# A handle is letters, digits, "_", "-" and "." inside; a "." at the end is sentence punctuation, not part of it.
# It must not follow a word character, so the "@" of an e-mail address is left alone.
_HANDLE = re.compile(r"(?<![\w.@])@[\w\-]+(?:\.[\w\-]+)*")
_TIMESTAMP = re.compile(r"\b\d{1,2}(?::\d{2}){1,2}\b")
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")  # letters only: digits, emoji and punctuation are not words
_NOT_ALNUM = re.compile(r"[\W_]+")


def clean_comment(text: str) -> str:
    """Replace @handles with "@user" and URLs with "<url>", and collapse every run of whitespace to one space."""
    text = _URL.sub(URL_TOKEN, text)
    text = _HANDLE.sub(USER_TOKEN, text)
    return " ".join(text.split())


def _words(text: str) -> list[str]:
    stripped = _TIMESTAMP.sub(" ", clean_comment(text)).replace(USER_TOKEN, " ").replace(URL_TOKEN, " ")
    return _WORD.findall(stripped)


def is_substantial(text: str) -> bool:
    """False for an empty comment, emoji only, a timestamp only ("3:20"), or fewer than MIN_WORDS words.

    A word is a run of letters. Mentions, URLs and timestamps are removed first, so "@user 3:20 lol" has one word.
    """
    return len(_words(text)) >= MIN_WORDS


def normalise_for_dedupe(text: str) -> str:
    """Lower-cased cleaned text with punctuation, emoji and extra spaces removed, so that copy-pasted spam that
    differs only in case, punctuation or a trailing emoji compares equal."""
    return _NOT_ALNUM.sub(" ", clean_comment(text).casefold()).strip()


def dedupe_key(text: str) -> str:
    """A short fingerprint of `normalise_for_dedupe`, for an index in the store."""
    return hashlib.sha1(normalise_for_dedupe(text).encode("utf-8")).hexdigest()


def english_probability(text: str) -> float:
    """langdetect's probability that the comment is English; 0.0 when it cannot decide (too little text)."""
    body = " ".join(_words(text))  # letters only, so "<url>" and "@user" do not count as English words
    if not body:
        return 0.0
    try:
        return next((language.prob for language in detect_langs(body) if language.lang == "en"), 0.0)
    except LangDetectException:
        return 0.0


def is_english(probability: float) -> bool:
    return probability >= MIN_ENGLISH_PROBABILITY
