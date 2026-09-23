"""
Server-side mirror of the quote matching in static/js/evidence_highlighter.js.

Used by `prepare_demo` to dry-run evidence highlighting against the pdf2htmlEX
output, so papers whose evidence cannot be located are spotted before the
poster session. Keep the algorithm in sync with the JS version.
"""

import unicodedata
from html.parser import HTMLParser

LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}
MIN_QUOTE = 12
MIN_ANCHOR = 30


def normalize(text):
    """Lowercase letters/digits only, ligatures expanded, accents stripped."""
    out = []
    for ch in text or "":
        for c in unicodedata.normalize("NFKD", LIGATURES.get(ch, ch)):
            if c.isalnum():
                out.append(c.lower())
    return "".join(out)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_normalized_text(html):
    parser = _TextExtractor()
    parser.feed(html)
    return normalize("".join(parser.parts))


def _longest_anchor(q, doc, min_len):
    lo, hi, best = min_len, len(q), None
    while lo <= hi:
        length = (lo + hi) // 2
        step = max(1, length >> 3)
        found = None
        for start in range(0, len(q) - length + 1, step):
            idx = doc.find(q[start : start + length])
            if idx != -1:
                found = [start, idx, length]
                break
        if found:
            best = found
            lo = length + 1
        else:
            hi = length - 1
    if not best:
        return None
    q_start, d_start, length = best
    while q_start > 0 and d_start > 0 and q[q_start - 1] == doc[d_start - 1]:
        q_start, d_start, length = q_start - 1, d_start - 1, length + 1
    while (
        q_start + length < len(q)
        and d_start + length < len(doc)
        and q[q_start + length] == doc[d_start + length]
    ):
        length += 1
    return q_start, d_start, length


def _anchors(q, doc, min_len):
    if len(q) < min_len:
        return []
    anchor = _longest_anchor(q, doc, min_len)
    if not anchor:
        return []
    q_start, d_start, length = anchor
    return (
        _anchors(q[:q_start], doc, min_len)
        + [(d_start, d_start + length)]
        + _anchors(q[q_start + length :], doc, min_len)
    )


def locate(quote, doc_norm):
    """Return (status, coverage) with status in exact/partial/missing/short."""
    q = normalize(quote)
    if len(q) < MIN_QUOTE:
        return "short", 0.0
    if q in doc_norm:
        return "exact", 1.0
    ranges = _anchors(q, doc_norm, MIN_ANCHOR)
    covered = sum(end - start for start, end in ranges)
    return ("partial" if ranges else "missing"), covered / len(q)
