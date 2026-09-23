/*
 * Demo report page: score overview, criteria tables and the pdf2htmlEX paper
 * with the evidence quotes highlighted. Rows and highlights are linked both
 * ways: clicking a criterion scrolls to its evidence, clicking a highlight
 * selects its criterion.
 */
(function (global) {
    'use strict';

    const esc = function (t) { return NodeRenderers.escapeHtml(t); };
    const COLORS = { checklist: '#16a085', dataset: '#8e44ad', type: '#e67e22' };
    const FRAME_CSS = `
        .highlight { cursor: pointer; border-radius: 2px; transition: outline-color .3s; }
        .highlight.pulse { animation: hlpulse 1.1s ease-in-out 3; }
        @keyframes hlpulse { 50% { outline: 3px solid #f39c12; outline-offset: 2px; } }
        #sidebar { display: none !important; }
        #page-container { left: 0 !important; background: #525659 !important; }
        .pf { margin: 14px auto !important; box-shadow: 0 2px 10px rgba(0,0,0,.35) !important; }
        /* pdf2htmlEX's viewer hides off-screen pages; keep them rendered so evidence can be scrolled to. */
        .pc { display: block !important; }
    `;

    let D = null;
    const located = {};   // annotation id -> {spans, status}

    function fmtDuration(s) {
        if (s === null || s === undefined) return '–';
        if (s < 60) return s.toFixed(s < 10 ? 1 : 0) + 's';
        return Math.floor(s / 60) + 'm ' + Math.round(s % 60) + 's';
    }

    function nodeName(id) {
        const n = D.dag.nodes.find(function (d) { return d.id === id; });
        return n ? n.name : id;
    }

    function list(title, icon, color, items) {
        if (!items || !items.length) return '';
        return `<h6 class="mt-3"><i class="fas ${icon} text-${color} mr-2"></i>${title}</h6>
                <ul class="mb-0">${items.map(function (i) { return '<li>' + esc(i) + '</li>'; }).join('')}</ul>`;
    }

    // ---- Tabs ------------------------------------------------------------

    function renderOverview() {
        const f = D.final || {};
        DemoScores.gauge(document.getElementById('report-gauge'), f.overall_score);
        document.getElementById('report-components').innerHTML =
            '<div class="font-weight-bold mb-1">Component scores</div>' + DemoScores.miniBars(DemoScores.components(f)) +
            `<div class="small text-muted mt-2">Paper type: <strong>${esc(String(f.paper_type || '').toUpperCase())}</strong>
             · processing time ${fmtDuration(D.run.real_duration_s)} · ${(D.run.tokens_in + D.run.tokens_out).toLocaleString()} tokens</div>`;
        document.getElementById('overview-body').innerHTML = `
            <h6><i class="fas fa-file-alt text-primary mr-2"></i>Executive summary</h6>
            <p style="white-space: pre-line;">${esc(f.executive_summary)}</p>
            ${list('Strengths', 'fa-check-circle', 'success', f.strengths)}
            ${list('Weaknesses', 'fa-exclamation-triangle', 'danger', f.weaknesses)}
            ${list('Recommendations', 'fa-lightbulb', 'warning', f.recommendations)}`;
    }

    function renderTabs() {
        const checklist = D.evidence.checklist || [];
        const present = checklist.filter(function (c) { return c.present; }).length;
        document.getElementById('count-checklist').textContent = present + '/' + checklist.length;
        document.getElementById('tab-checklist').innerHTML =
            '<p class="small text-muted">Click a criterion to jump to its evidence in the paper. Missing <span class="text-danger font-weight-bold">critical</span> criteria are marked in red.</p>' +
            NodeRenderers.criteriaTable(checklist);

        const ds = D.nodes.dataset_documentation_check;
        if (ds && ds.status !== 'skipped' && (D.evidence.dataset || []).length) {
            document.getElementById('tab-dataset').innerHTML = NodeRenderers.renderResult('dataset_documentation_check', ds.detail.artifacts);
            document.getElementById('legend-dataset').style.display = '';
        } else {
            document.getElementById('nav-dataset').style.display = 'none';
        }

        let code = '';
        ['code_availability_check', 'code_repository_analysis', 'code_embedding'].forEach(function (id) {
            const n = D.nodes[id];
            if (n && n.status !== 'skipped') code += NodeRenderers.renderResult(id, n.detail.artifacts);
        });
        document.getElementById('tab-code').innerHTML = code || '<p class="text-muted">No code repository was analysed for this paper.</p>';

        const order = D.dag.nodes.map(function (n) { return n.id; }).filter(function (id) { return D.nodes[id]; });
        document.getElementById('tab-pipeline').innerHTML =
            `<p class="small text-muted">Workflow <code>${esc(D.run.workflow)}</code> v${esc(D.run.version)}, run #${esc(D.run.run_number)}. Click a node for its full output.</p>
             <div class="node-list">${order.map(function (id) {
                const n = D.nodes[id];
                return `<div class="item" data-node="${id}">
                            <span class="dot ${n.status === 'skipped' ? 'skipped' : ''}"></span>
                            <strong>${esc(nodeName(id))}</strong>
                            <span class="meta">${n.status === 'skipped' ? 'skipped' : fmtDuration(n.real_duration)}${n.was_cached ? ' · cached' : ''}${n.tokens_in ? ' · ' + (n.tokens_in + n.tokens_out).toLocaleString() + ' tok' : ''}</span>
                        </div>`;
             }).join('')}</div>`;
        document.querySelectorAll('.node-list .item').forEach(function (el) {
            el.addEventListener('click', function () { openNode(el.getAttribute('data-node')); });
        });

        document.querySelectorAll('.criteria-table').forEach(function (table) {
            table.querySelectorAll('.criterion-row').forEach(function (row) {
                row.addEventListener('click', function () { focusCriterion(row.getAttribute('data-criterion-id'), false); });
            });
        });
        markMissingCritical();
    }

    function markMissingCritical() {
        const all = [].concat(
            (D.evidence.checklist || []).map(function (c) { return [c.criterion_id, c]; }),
            (D.evidence.dataset || []).map(function (c) { return ['ds:' + c.criterion_id, c]; })
        );
        all.forEach(function (pair) {
            const c = pair[1];
            if (!c.present && c.importance === 'critical') {
                document.querySelectorAll(`.criterion-row[data-criterion-id="${cssEscape(pair[0])}"]`).forEach(function (r) {
                    r.classList.add('missing-critical');
                });
            }
        });
    }

    function cssEscape(s) { return (global.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/"/g, '\\"'); }

    function openNode(id) {
        const n = D.nodes[id];
        document.getElementById('nodeModalTitle').textContent = nodeName(id);
        const def = D.dag.nodes.find(function (d) { return d.id === id; }) || {};
        document.getElementById('nodeModalBody').innerHTML =
            `<p class="text-muted">${esc(def.description || '')}</p>` +
            (n.status === 'skipped' ? '<p>Skipped: not applicable to this paper.</p>'
                : (NodeRenderers.renderResult(id, n.detail.artifacts) || '<p class="text-muted">No result artifact.</p>'));
        $('#nodeModal').modal('show');
    }

    // ---- Highlighting ----------------------------------------------------

    function fitPages(doc, frame) {
        const page = doc.querySelector('.pf');
        if (!page) return;
        const natural = page.offsetWidth;
        const avail = frame.clientWidth - 40;
        const zoom = Math.min(1, avail / natural);
        doc.querySelectorAll('.pf').forEach(function (p) { p.style.zoom = zoom; });
    }

    function highlightAll(doc) {
        const root = doc.getElementById('page-container') || doc.body;
        const onClick = function (ids) { onHighlightClick(ids.split(',')); };
        const hl = function (id, quote, category, color) {
            const res = EvidenceHighlighter.highlightQuote(root, quote, { id: id, category: category, color: color },
                { alpha: 0.32, titleSuffix: ' - click for details', onClick: onClick });
            located[id] = res;
        };
        (D.evidence.paper_type || []).forEach(function (q, i) {
            hl('pt:' + i, q.replace(/^["“]|["”]$/g, ''), 'Paper type evidence', COLORS.type);
        });
        (D.evidence.checklist || []).forEach(function (c) {
            if (c.present && c.evidence_text) hl(c.criterion_id, c.evidence_text, c.criterion_name, COLORS.checklist);
        });
        (D.evidence.dataset || []).forEach(function (c) {
            if (c.present && c.evidence_text) hl('ds:' + c.criterion_id, c.evidence_text, c.criterion_name, COLORS.dataset);
        });

        fillGaps(doc);

        // Row badges + summary.
        let withEvidence = 0, found = 0;
        document.querySelectorAll('.criterion-row').forEach(function (row) {
            const id = row.getAttribute('data-criterion-id');
            const slot = row.querySelector('.criterion-locate');
            const res = located[id];
            if (!res || !slot) return;
            withEvidence++;
            if (res.spans.length) {
                found++;
                slot.innerHTML = '<span class="loc yes"><i class="fas fa-location-dot"></i> in paper</span>';
            } else {
                slot.innerHTML = '<span class="loc no">quote not found</span>';
            }
        });
        document.getElementById('located-summary').innerHTML =
            `<i class="fas fa-highlighter mr-1"></i> ${found} of ${withEvidence} satisfied criteria located and highlighted in the paper.`;
    }

    // pdf2htmlEX renders inter-word spaces as empty spacer spans; colour the
    // spacers between two parts of the same highlight so it reads as one block.
    function fillGaps(doc) {
        doc.querySelectorAll('.highlight').forEach(function (span) {
            const gap = span.nextElementSibling;
            if (!gap || span.nextSibling !== gap || !gap.classList.contains('_')) return;
            const next = gap.nextElementSibling;
            if (!next || gap.nextSibling !== next || !next.classList.contains('highlight')) return;
            const ids = span.getAttribute('data-annotation-id').split(',');
            const shared = next.getAttribute('data-annotation-id').split(',').some(function (id) { return ids.indexOf(id) >= 0; });
            if (shared) {
                gap.style.background = span.style.background || span.style.backgroundColor;
                gap.style.borderBottom = span.style.borderBottom;
            }
        });
    }

    function spansFor(id) {
        const res = located[id];
        return res ? res.spans.filter(function (s) { return s.isConnected; }) : [];
    }

    function pulse(spans) {
        spans.forEach(function (s) {
            s.classList.remove('pulse');
            void s.offsetWidth;
            s.classList.add('pulse');
        });
    }

    function selectRow(id, scrollRow) {
        document.querySelectorAll('.criterion-row.active').forEach(function (r) { r.classList.remove('active'); });
        const row = document.querySelector(`.criterion-row[data-criterion-id="${cssEscape(id)}"]`);
        if (!row) return;
        row.classList.add('active');
        if (scrollRow) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }

    function focusCriterion(id, scrollRow) {
        selectRow(id, scrollRow);
        const spans = spansFor(id);
        if (spans.length) {
            spans[0].scrollIntoView({ block: 'center', behavior: 'smooth' });
            pulse(spans);
        }
    }

    function onHighlightClick(ids) {
        const id = ids.find(function (x) { return x.indexOf('pt:') !== 0; });
        if (!id) {
            $('a[href="#tab-overview"]').tab('show');
            return;
        }
        const tab = id.indexOf('ds:') === 0 ? '#tab-dataset' : '#tab-checklist';
        $(`a[href="${tab}"]`).tab('show');
        setTimeout(function () {
            selectRow(id, true);
            pulse(spansFor(id));
        }, 180);
    }

    function setupFrame() {
        const frame = document.getElementById('pdf-frame');
        if (!frame) return;
        const onLoad = function () {
            const doc = frame.contentDocument;
            if (!doc) return;
            const style = doc.createElement('style');
            style.textContent = FRAME_CSS;
            doc.head.appendChild(style);
            fitPages(doc, frame);
            highlightAll(doc);
            global.addEventListener('resize', function () { fitPages(doc, frame); });
            if (kioskParams().kiosk) startKiosk();
        };
        if (frame.contentDocument && frame.contentDocument.readyState === 'complete' && frame.contentDocument.querySelector('.pf')) onLoad();
        else frame.addEventListener('load', onLoad);
    }

    // ---- Kiosk: walk through the evidence, then move to the next paper ---

    function kioskParams() {
        const p = new URLSearchParams(location.search);
        return { kiosk: p.get('kiosk') === '1', next: p.get('next') };
    }

    function startKiosk() {
        const params = kioskParams();
        const ids = (D.evidence.checklist || []).concat(D.evidence.dataset || [])
            .map(function (c) { return (D.evidence.dataset || []).indexOf(c) >= 0 ? 'ds:' + c.criterion_id : c.criterion_id; })
            .filter(function (id) { return spansFor(id).length; });
        const banner = document.getElementById('kiosk-banner');
        banner.style.display = '';
        let i = 0;
        const step = function () {
            if (i < ids.length && i < 10) {
                const id = ids[i++];
                $(`a[href="${id.indexOf('ds:') === 0 ? '#tab-dataset' : '#tab-checklist'}"]`).tab('show');
                setTimeout(function () { focusCriterion(id, true); }, 200);
                banner.textContent = 'Kiosk mode: evidence ' + i + ' of ' + Math.min(ids.length, 10);
                setTimeout(step, 4500);
            } else {
                $('a[href="#tab-overview"]').tab('show');
                banner.textContent = params.next ? 'Next paper in a moment…' : 'Kiosk mode';
                if (params.next) setTimeout(function () { window.location = params.next; }, 8000);
            }
        };
        setTimeout(step, 2500);
    }

    function start(data) {
        D = data;
        renderOverview();
        renderTabs();
        setupFrame();
    }

    global.DemoReport = { start: start };
})(window);
