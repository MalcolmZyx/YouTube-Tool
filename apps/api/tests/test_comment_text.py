"""Comment cleaning and filters: the one definition shared by building the corpus and scoring new comments."""
import pytest

from youtube.text import (
    clean_comment,
    dedupe_key,
    english_probability,
    is_english,
    is_substantial,
    normalise_for_dedupe,
)


@pytest.mark.parametrize(("raw", "cleaned"), [
    ("great video @SomeCreator.Official thanks", "great video @user thanks"),
    ("@a_b-c: you are right", "@user: you are right"),
    ("thanks @bob.", "thanks @user."),  # the final dot is punctuation
    ("mail me at name@example.com", "mail me at name@example.com"),  # not a handle
    ("see https://example.com/x?y=1 and www.example.org now", "see <url> and <url> now"),
    ("HTTP://EXAMPLE.COM/A", "<url>"),
    ("too   many\n\nspaces\t here ", "too many spaces here"),
    ("", ""),
])
def test_clean_comment(raw, cleaned):
    assert clean_comment(raw) == cleaned


def test_cleaning_twice_changes_nothing():
    once = clean_comment("hi @Bob see https://x.y  now")
    assert clean_comment(once) == once


@pytest.mark.parametrize("text", [
    "", "   ", "\U0001F602\U0001F602\U0001F602", "3:20", "1:02:03", "3:20 5:45 7:10", "lol", "so good", "@user @user",
    "<url>", "@user check <url>", "1 2 3 4 5", "!!!???",
])
def test_insubstantial_comments_are_rejected(text):
    assert not is_substantial(text)


@pytest.mark.parametrize("text", [
    "I really liked this", "3:20 this part is great", "Don't skip the intro \U0001F602", "you're right about that",
])
def test_substantial_comments_are_accepted(text):
    assert is_substantial(text)


def test_dedupe_ignores_case_punctuation_emoji_and_spacing():
    variants = ["Great video!!", "great   video", "GREAT VIDEO \U0001F44D", "great, video."]
    assert {normalise_for_dedupe(v) for v in variants} == {"great video"}
    assert len({dedupe_key(v) for v in variants}) == 1
    assert dedupe_key("great video") != dedupe_key("great videos")


def test_dedupe_sees_through_mentions_and_urls():
    assert normalise_for_dedupe("check @Ann out https://a.b/1") == normalise_for_dedupe("check @Bob out https://c.d/2")


def test_english_is_recognised_and_other_languages_are_not():
    assert is_english(english_probability("This tutorial explained the whole process really clearly, thank you"))
    assert not is_english(english_probability("Este video me ayudo mucho a entender como funciona todo esto"))
    assert not is_english(english_probability("Dieses Video hat mir sehr geholfen, vielen Dank dafuer"))


def test_language_detection_is_repeatable():
    text = "I think the second half dragged a bit but the ending was good"
    assert len({english_probability(text) for _ in range(5)}) == 1


def test_a_comment_with_nothing_to_detect_is_not_english():
    assert english_probability("") == 0.0
    assert english_probability("\U0001F602\U0001F602") == 0.0
    assert english_probability("<url> @user") == 0.0
