"""Language detection for routing zh → Plaud, en → Apple TTML / Plaud (en).

We deliberately keep this dumb and offline. The signal that matters most
in practice is "does the title contain CJK characters?" — Apple Podcasts
stores titles as Unicode strings exactly as the publisher shipped them.

If we ever want fancier detection (langdetect, fasttext, …) the public
function signature can stay; just swap the implementation.
"""

from __future__ import annotations

import re

# Common CJK Unified Ideographs ranges; covers Chinese, Japanese kanji, etc.
_CJK = re.compile(
    "["
    "一-鿿"   # CJK unified
    "㐀-䶿"   # CJK extension A
    "豈-﫿"   # CJK compatibility
    "]"
)
_HIRAGANA_KATAKANA = re.compile("[぀-ヿ]")
_HANGUL = re.compile("[가-힯]")


def detect(*texts: str) -> str:
    """Return an ISO-ish language code for routing decisions.

    Looks at every passed string (typically podcast title + episode title)
    and picks the dominant non-Latin script if any. Falls back to ``en``.

    Plaud language codes used downstream: ``zh``, ``ja``, ``ko``, ``en``.
    """
    blob = "".join(t for t in texts if t)
    if _HIRAGANA_KATAKANA.search(blob):
        return "ja"
    if _HANGUL.search(blob):
        return "ko"
    if _CJK.search(blob):
        # Pure CJK ideographs without kana/hangul → Chinese.
        return "zh"
    return "en"
