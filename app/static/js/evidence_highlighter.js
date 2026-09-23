/*
 * Evidence highlighter: shared text-highlighting core for the annotator and
 * the demo report.
 *
 * Highlights are <span class="highlight"> elements carrying comma-separated
 * data-annotation-id / data-category lists. When a new highlight overlaps an
 * existing one, the ids are merged into the existing span and the colours are
 * blended (the annotator's delete logic relies on this).
 *
 * highlightQuote() does tolerant matching for LLM evidence quotes against
 * pdf2htmlEX output, where words are split across spans and spaces are often
 * rendered as positioning elements. Both sides are reduced to lowercase
 * letters/digits (ligatures expanded), then searched for an exact match,
 * falling back to a set of long common anchors.
 * demo/matching.py mirrors this algorithm for server-side dry runs.
 */
(function (global) {
    'use strict';

    const LIGATURES = {
        'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl',
        'ﬃ': 'ffi', 'ﬄ': 'ffl', 'ﬅ': 'st', 'ﬆ': 'st'
    };
    const ALNUM = /[\p{L}\p{N}]/u;
    const MIN_QUOTE = 12;
    const MIN_ANCHOR = 30;

    function hexToRGBA(hex, alpha) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    // Yield the normalised characters of a raw character.
    function normChars(ch) {
        const expanded = LIGATURES[ch] || ch;
        const out = [];
        for (const c of expanded.normalize('NFKD')) {
            if (ALNUM.test(c)) {
                for (const l of c.toLowerCase()) out.push(l);
            }
        }
        return out;
    }

    function normalize(text) {
        let s = '';
        for (const ch of text) s += normChars(ch).join('');
        return s;
    }

    function isHighlight(node) {
        return node.nodeType === Node.ELEMENT_NODE &&
            node.classList && node.classList.contains('highlight');
    }

    // Collect text nodes and existing highlight spans under container, in
    // document order. Text inside an already-collected highlight is skipped so
    // the highlight is treated as one unit.
    function collectUnits(container) {
        const walker = container.ownerDocument.createTreeWalker(
            container,
            NodeFilter.SHOW_ALL,
            {
                acceptNode: function (node) {
                    if (node.nodeType === Node.TEXT_NODE) return NodeFilter.FILTER_ACCEPT;
                    if (isHighlight(node)) return NodeFilter.FILTER_ACCEPT;
                    return NodeFilter.FILTER_SKIP;
                }
            },
            false
        );
        const units = [];
        const seen = new Set();
        let node;
        while ((node = walker.nextNode())) {
            if (node.nodeType === Node.TEXT_NODE && node.parentNode && seen.has(node.parentNode)) {
                continue;
            }
            if (isHighlight(node)) seen.add(node);
            units.push({ node: node, text: node.textContent, isHighlight: isHighlight(node) });
        }
        return units;
    }

    // Add an annotation to an existing highlight span (overlap case).
    function mergeIntoHighlight(span, annotation, opts) {
        const existingIds = span.getAttribute('data-annotation-id') || '';
        const existingCategories = span.getAttribute('data-category') || '';
        if (existingIds.split(',').includes(String(annotation.id))) return;

        span.setAttribute('data-annotation-id', existingIds + ',' + annotation.id);
        span.setAttribute('data-category', existingCategories + ',' + annotation.category);

        const existingBg = span.style.backgroundColor;
        const newBg = hexToRGBA(annotation.color, opts.alpha);
        span.style.background = `linear-gradient(to bottom, ${existingBg} 50%, ${newBg} 50%)`;
        span.style.boxShadow = `inset 0 -4px 0 -2px ${annotation.color}`;

        const categories = span.getAttribute('data-category').split(',');
        span.title = categories.join(', ') + opts.titleSuffix;
    }

    function wrapText(textNode, start, end, annotation, opts) {
        const text = textNode.textContent;
        const before = text.substring(0, start);
        const middle = text.substring(start, end);
        const after = text.substring(end);
        if (!middle) return null;

        const parent = textNode.parentNode;
        const doc = textNode.ownerDocument;
        const span = doc.createElement('span');
        span.className = 'highlight';
        span.setAttribute('data-category', annotation.category);
        span.setAttribute('data-annotation-id', annotation.id);
        span.style.backgroundColor = hexToRGBA(annotation.color, opts.alpha);
        span.style.borderBottom = `2px solid ${annotation.color}`;
        span.textContent = middle;
        span.title = annotation.category + opts.titleSuffix;
        if (opts.onClick) {
            span.addEventListener('click', function (e) {
                e.stopPropagation();
                opts.onClick(this.getAttribute('data-annotation-id'), this, e);
            });
        }

        if (before) parent.insertBefore(doc.createTextNode(before), textNode);
        parent.insertBefore(span, textNode);
        if (after) parent.insertBefore(doc.createTextNode(after), textNode);
        parent.removeChild(textNode);
        return span;
    }

    /*
     * Apply an annotation to a list of segments {node, start, end}, where node
     * is a text node or an existing highlight span. Returns the spans touched.
     *
     * annotation: {id, category, color}
     * opts: {alpha=0.3, titleSuffix=' - Click to manage', onClick(ids, span, event)}
     */
    function applySegments(segments, annotation, opts) {
        opts = Object.assign({ alpha: 0.3, titleSuffix: ' - Click to manage', onClick: null }, opts || {});
        const touched = [];
        segments.forEach(function (seg) {
            const node = seg.node;
            if (isHighlight(node)) {
                mergeIntoHighlight(node, annotation, opts);
                touched.push(node);
                return;
            }
            if (node.nodeType === Node.TEXT_NODE && node.parentNode && isHighlight(node.parentNode)) {
                mergeIntoHighlight(node.parentNode, annotation, opts);
                touched.push(node.parentNode);
                return;
            }
            if (node.nodeType === Node.TEXT_NODE) {
                const span = wrapText(node, seg.start, seg.end, annotation, opts);
                if (span) touched.push(span);
            }
        });
        return touched;
    }

    // Segments covered by a DOM Range (used by the annotator's XPath restore).
    function segmentsForRange(container, range) {
        const segments = [];
        collectUnits(container).forEach(function (unit) {
            const node = unit.node;
            try {
                const len = node.nodeType === Node.TEXT_NODE ? node.length : node.childNodes.length;
                const compareStart = range.comparePoint(node, 0);
                const compareEnd = range.comparePoint(node, len);
                if (compareStart === 0 || compareEnd === 0 || (compareStart < 0 && compareEnd > 0)) {
                    const start = node === range.startContainer ? range.startOffset : 0;
                    const end = node === range.endContainer ? range.endOffset : len;
                    if (start < end || node.nodeType === Node.ELEMENT_NODE) {
                        segments.push({ node: node, start: start, end: end });
                    }
                }
            } catch (e) {
                console.warn('Could not compare node:', e);
            }
        });
        return segments;
    }

    // Segments for the first exact (raw text) occurrence of text.
    function segmentsForExactText(container, text) {
        if (!text) return null;
        const units = collectUnits(container);
        let full = '';
        const starts = units.map(function (u) { const s = full.length; full += u.text; return s; });
        const index = full.indexOf(text);
        if (index === -1) return null;
        const endIndex = index + text.length;
        const segments = [];
        units.forEach(function (u, i) {
            const uEnd = starts[i] + u.text.length;
            if (uEnd > index && starts[i] < endIndex) {
                segments.push({
                    node: u.node,
                    start: Math.max(0, index - starts[i]),
                    end: Math.min(u.text.length, endIndex - starts[i])
                });
            }
        });
        return segments;
    }

    // ---- Tolerant quote matching -----------------------------------------

    // Normalised index of the container: norm string plus, for each normalised
    // char, the unit index and raw offset it came from.
    function buildNormIndex(container) {
        const units = collectUnits(container);
        let norm = '';
        const unitOf = [];
        const offsetOf = [];
        units.forEach(function (u, ui) {
            const text = u.text;
            let offset = 0;
            for (const ch of text) {
                const chars = normChars(ch);
                for (let k = 0; k < chars.length; k++) {
                    norm += chars[k];
                    unitOf.push(ui);
                    offsetOf.push(offset);
                }
                offset += ch.length;
            }
        });
        return { units: units, norm: norm, unitOf: unitOf, offsetOf: offsetOf };
    }

    // Find the longest substring of q (>= minLen) that occurs in doc.
    function longestAnchor(q, doc, minLen) {
        let lo = minLen, hi = q.length, best = null;
        while (lo <= hi) {
            const L = (lo + hi) >> 1;
            const step = Math.max(1, L >> 3);
            let found = null;
            for (let st = 0; st + L <= q.length; st += step) {
                const di = doc.indexOf(q.substr(st, L));
                if (di !== -1) { found = { qStart: st, dStart: di, len: L }; break; }
            }
            if (found) { best = found; lo = L + 1; } else { hi = L - 1; }
        }
        if (!best) return null;
        // Extend the anchor in both directions while characters keep matching.
        while (best.qStart > 0 && best.dStart > 0 && q[best.qStart - 1] === doc[best.dStart - 1]) {
            best.qStart--; best.dStart--; best.len++;
        }
        while (best.qStart + best.len < q.length && best.dStart + best.len < doc.length &&
               q[best.qStart + best.len] === doc[best.dStart + best.len]) {
            best.len++;
        }
        return best;
    }

    function anchors(q, doc, minLen) {
        if (q.length < minLen) return [];
        const a = longestAnchor(q, doc, minLen);
        if (!a) return [];
        return anchors(q.substring(0, a.qStart), doc, minLen)
            .concat([[a.dStart, a.dStart + a.len]])
            .concat(anchors(q.substring(a.qStart + a.len), doc, minLen));
    }

    /*
     * Locate a quote in a normalised document string.
     * Returns {status: 'exact'|'partial'|'missing'|'short', ranges: [[s, e]], coverage}.
     */
    function locateNormalized(quoteNorm, docNorm) {
        if (quoteNorm.length < MIN_QUOTE) return { status: 'short', ranges: [], coverage: 0 };
        const idx = docNorm.indexOf(quoteNorm);
        if (idx !== -1) {
            return { status: 'exact', ranges: [[idx, idx + quoteNorm.length]], coverage: 1 };
        }
        const ranges = anchors(quoteNorm, docNorm, MIN_ANCHOR);
        const covered = ranges.reduce(function (s, r) { return s + (r[1] - r[0]); }, 0);
        return {
            status: ranges.length ? 'partial' : 'missing',
            ranges: ranges,
            coverage: covered / quoteNorm.length
        };
    }

    // Convert a normalised range into DOM segments.
    function segmentsForNormRange(index, range) {
        const byUnit = new Map();
        for (let i = range[0]; i < range[1]; i++) {
            const ui = index.unitOf[i];
            const off = index.offsetOf[i];
            const cur = byUnit.get(ui);
            if (!cur) byUnit.set(ui, { start: off, end: off + 1 });
            else cur.end = off + 1;
        }
        const segments = [];
        byUnit.forEach(function (se, ui) {
            const unit = index.units[ui];
            // Extend the end over the full raw character (surrogates, ligatures).
            let end = se.end;
            const text = unit.text;
            while (end < text.length && (text.charCodeAt(end) & 0xFC00) === 0xDC00) end++;
            segments.push({ node: unit.node, start: se.start, end: end });
        });
        return segments;
    }

    /*
     * Highlight a (possibly inexact) quote under container.
     * Returns {status, coverage, spans}.
     */
    function highlightQuote(container, quote, annotation, opts) {
        const quoteNorm = normalize(quote || '');
        const index = buildNormIndex(container);
        const result = locateNormalized(quoteNorm, index.norm);
        // Apply ranges right-to-left, recomputing segments from a fresh index
        // each time because wrapping splits text nodes.
        let spans = [];
        const ranges = result.ranges.slice().sort(function (a, b) { return b[0] - a[0]; });
        let current = index;
        ranges.forEach(function (range, i) {
            if (i > 0) current = buildNormIndex(container);
            const segments = segmentsForNormRange(current, range);
            spans = spans.concat(applySegments(segments, annotation, opts));
        });
        return { status: result.status, coverage: result.coverage, spans: spans };
    }

    global.EvidenceHighlighter = {
        hexToRGBA: hexToRGBA,
        normalize: normalize,
        collectUnits: collectUnits,
        applySegments: applySegments,
        segmentsForRange: segmentsForRange,
        segmentsForExactText: segmentsForExactText,
        locateNormalized: locateNormalized,
        highlightQuote: highlightQuote
    };
})(window);
