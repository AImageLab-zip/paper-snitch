/*
 * Poster demo replay: plays back a completed workflow run from a single
 * timeline payload (see demo/timeline.py). Nothing is fetched after load.
 */
(function (global) {
    'use strict';

    const esc = function (t) { return NodeRenderers.escapeHtml(t); };
    const INTAKE_SECONDS = 7;
    const NODE_COLORS = ['#48c9b0', '#5dade2', '#af7ac5', '#f5b041', '#ec7063', '#58d68d', '#f7dc6f', '#85c1e9'];
    const NODE_ICONS = {
        paper_type_classification: '',   // tag
        section_embeddings: '',          // layer-group
        dataset_documentation_check: '', // database
        reproducibility_checklist: '',   // clipboard-check
        code_availability_check: '',     // code-branch
        code_embedding: '',              // cubes
        code_repository_analysis: '',    // code
        final_aggregation: ''            // trophy
    };

    let T = null;          // timeline payload
    let opts = null;
    let speed = 1;
    let clock = -INTAKE_SECONDS; // negative: intake phase
    let lastFrame = null;
    let finished = false;
    let nodeState = {};    // node_id -> 'pending' | 'running' | 'completed' | 'skipped'
    let logQueue = [];     // [{t, node, level, message}] sorted by t
    let logPos = 0;
    let layout = null;

    function fmtClock(s) {
        s = Math.max(0, Math.floor(s));
        return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    }

    function fmtDuration(s) {
        if (s === null || s === undefined) return '–';
        if (s < 60) return s.toFixed(s < 10 ? 1 : 0) + 's';
        return Math.floor(s / 60) + 'm ' + Math.round(s % 60) + 's';
    }

    function nodeName(id) {
        const n = T.dag.nodes.find(function (d) { return d.id === id; });
        return n ? n.name : id;
    }

    // ---- DAG layout ----------------------------------------------------

    function computeLayout() {
        const ids = T.dag.nodes.map(function (n) { return n.id; }).filter(function (id) { return T.nodes[id]; });
        const parents = {}, children = {};
        ids.forEach(function (id) { parents[id] = []; children[id] = []; });
        T.dag.edges.forEach(function (e) {
            if (parents[e.to] && children[e.from]) { parents[e.to].push(e.from); children[e.from].push(e.to); }
        });
        // Layer = longest path from a root.
        const layer = {};
        function depth(id) {
            if (layer[id] !== undefined) return layer[id];
            layer[id] = parents[id].length ? Math.max.apply(null, parents[id].map(depth)) + 1 : 0;
            return layer[id];
        }
        ids.forEach(depth);
        const nLayers = Math.max.apply(null, ids.map(function (id) { return layer[id]; })) + 1;
        const byLayer = [];
        for (let i = 0; i < nLayers; i++) byLayer.push(ids.filter(function (id) { return layer[id] === i; }));
        const widest = byLayer.reduce(function (best, l, i) { return l.length > byLayer[best].length ? i : best; }, 0);
        const width = byLayer[widest].length;

        const row = {};
        byLayer[widest].forEach(function (id, i) { row[id] = i; });
        const mean = function (a) { return a.reduce(function (s, x) { return s + x; }, 0) / a.length; };
        for (let i = widest + 1; i < nLayers; i++) {
            byLayer[i].forEach(function (id) {
                const pr = parents[id].map(function (p) { return row[p]; }).filter(function (r) { return r !== undefined; });
                row[id] = pr.length ? mean(pr) : (width - 1) / 2;
            });
        }
        for (let i = widest - 1; i >= 0; i--) {
            byLayer[i].forEach(function (id) {
                const cr = children[id].map(function (c) { return row[c]; }).filter(function (r) { return r !== undefined; });
                row[id] = cr.length ? mean(cr) : (width - 1) / 2;
            });
        }

        const W = 156, H = 58, GX = 34, GY = 22, PAD = 8;
        const pos = {};
        ids.forEach(function (id) {
            pos[id] = { x: PAD + layer[id] * (W + GX), y: PAD + row[id] * (H + GY), w: W, h: H };
        });
        return {
            ids: ids, pos: pos, parents: parents,
            width: PAD * 2 + nLayers * W + (nLayers - 1) * GX,
            height: PAD * 2 + width * H + (width - 1) * GY
        };
    }

    function drawDag() {
        layout = computeLayout();
        const svg = document.getElementById('dag');
        svg.setAttribute('viewBox', `0 0 ${layout.width} ${layout.height}`);
        let html = '';
        T.dag.edges.forEach(function (e) {
            const a = layout.pos[e.from], b = layout.pos[e.to];
            if (!a || !b) return;
            const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
            const mx = (x1 + x2) / 2;
            html += `<path class="edge" data-from="${e.from}" data-to="${e.to}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"></path>`;
        });
        layout.ids.forEach(function (id) {
            const p = layout.pos[id];
            html += `
                <g class="node pending" data-id="${id}" transform="translate(${p.x},${p.y})">
                    <rect width="${p.w}" height="${p.h}" rx="12"></rect>
                    <text class="icon" x="14" y="25">${NODE_ICONS[id] || ''}</text>
                    <text x="36" y="25">${esc(nodeName(id))}</text>
                    <text class="sub" x="14" y="44">waiting</text>
                    <rect class="bar-bg" x="10" y="${p.h - 8}" width="${p.w - 20}" height="3" rx="1.5"></rect>
                    <rect class="bar" x="10" y="${p.h - 8}" width="0" height="3" rx="1.5"></rect>
                </g>`;
        });
        svg.innerHTML = html;
        svg.querySelectorAll('.node').forEach(function (g) {
            g.addEventListener('click', function () { openNode(g.getAttribute('data-id')); });
        });
    }

    // ---- Console -------------------------------------------------------

    function buildLogQueue() {
        const colors = {};
        layout.ids.forEach(function (id, i) { colors[id] = NODE_COLORS[i % NODE_COLORS.length]; });
        logQueue = [];
        Object.keys(T.nodes).forEach(function (id) {
            const n = T.nodes[id];
            logQueue.push({ t: n.start, node: id, level: 'sys', message: '▶ started', color: colors[id] });
            n.logs.forEach(function (l) {
                // Keep log lines inside the node's visible run window.
                const t = Math.min(Math.max(l.t, n.start), n.end);
                logQueue.push({ t: t, node: id, level: l.level, message: l.message, color: colors[id] });
            });
            const done = n.status === 'skipped' ? '⤼ skipped' : '✔ completed in ' + fmtDuration(n.real_duration) + (n.was_cached ? ' (cached)' : '');
            logQueue.push({ t: n.end + 0.001, node: id, level: 'sys', message: done, color: colors[id] });
        });
        logQueue.sort(function (a, b) { return a.t - b.t; });
        logPos = 0;
    }

    function printLog(entry) {
        const el = document.getElementById('console');
        const line = document.createElement('div');
        line.className = 'line ' + entry.level;
        line.innerHTML = `<span class="t">${fmtClock(entry.t)}</span> <span class="tag" style="color:${entry.color}">[${esc(nodeName(entry.node))}]</span> <span class="msg">${esc(entry.message)}</span>`;
        el.appendChild(line);
        while (el.childNodes.length > 400) el.removeChild(el.firstChild);
        el.scrollTop = el.scrollHeight;
    }

    function printSys(message) {
        const el = document.getElementById('console');
        const line = document.createElement('div');
        line.className = 'line sys';
        line.innerHTML = `<span class="t">${fmtClock(Math.max(0, clock))}</span> <span class="msg">${esc(message)}</span>`;
        el.appendChild(line);
        el.scrollTop = el.scrollHeight;
    }

    // ---- Result feed ---------------------------------------------------

    function artifactsOf(id) { return (T.nodes[id] && T.nodes[id].detail.artifacts) || {}; }

    function feedSummary(id) {
        const n = T.nodes[id];
        const a = artifactsOf(id);
        const r = a.result || {};
        if (n.status === 'skipped') {
            return id === 'dataset_documentation_check'
                ? 'Skipped: the paper does not introduce a new dataset.'
                : 'Skipped for this paper type.';
        }
        switch (id) {
            case 'paper_type_classification': {
                const ev = (r.key_evidence || [])[0];
                return `Classified as <strong>${esc(String(r.paper_type || '').toUpperCase())}</strong> with ${Math.round((r.confidence || 0) * 100)}% confidence.`
                    + (ev ? `<div class="text-muted font-italic mt-1">&ldquo;${esc(ev.length > 160 ? ev.slice(0, 157) + '…' : ev)}&rdquo;</div>` : '');
            }
            case 'section_embeddings': {
                // GROBID sometimes yields figure captions or formula fragments as "sections".
                const names = (r.section_types || []).map(function (s) { return s.toLowerCase().replace(/_/g, ' ').trim(); })
                    .filter(function (s) { return /^[a-z][a-z0-9 &:\/'-]{1,60}$/.test(s) && !/^(fig|table)\b/.test(s); });
                return `${esc(r.sections_processed)} sections embedded for retrieval.<div class="chips">${names.slice(0, 10).map(function (s) { return '<span>' + esc(s) + '</span>'; }).join('')}</div>`;
            }
            case 'dataset_documentation_check':
                return `Dataset: <strong>${esc(r.dataset_name || 'unnamed')}</strong>${r.dataset_size ? ' (' + esc(r.dataset_size) + ')' : ''}, score <strong>${esc(r.overall_score)}</strong>`
                    + DemoScores.miniBars([['Collection', r.data_collection_score], ['Annotation', r.annotation_score], ['Ethics & availability', r.ethics_availability_score]]);
            case 'reproducibility_checklist': {
                const crit = NodeRenderers.unwrap(a.criterion_analyses) || [];
                const present = crit.filter(function (c) { return c.present; }).length;
                return `${present} / ${crit.length} checklist criteria satisfied, score <strong>${esc(r.weighted_score !== undefined ? r.weighted_score : r.overall_score)}</strong>`
                    + DemoScores.miniBars([['Models', r.models_score], ['Datasets', r.datasets_score], ['Experiments', r.experiments_score]]);
            }
            case 'code_availability_check':
                return r.code_available
                    ? `Repository found: <strong>${esc((r.code_url || '').replace(/^https?:\/\//, ''))}</strong>${r.found_online ? ' (via online search)' : ''}`
                    : 'No public code repository found.';
            case 'code_embedding': {
                const files = Array.from(new Set((r.embedded_files || []).map(function (f) { return f.file_path; })));
                return `${esc(r.total_files)} files selected by the LLM, ${esc(r.total_chunks)} chunks embedded.<div class="chips">${files.slice(0, 8).map(function (f) { return '<span>' + esc(f) + '</span>'; }).join('')}</div>`;
            }
            case 'code_repository_analysis':
                if (r.reproducibility_score === undefined) return esc(r.overall_assessment || 'No repository to analyse.');
                return `Code reproducibility score <strong>${esc(r.reproducibility_score)}</strong>`
                    + DemoScores.miniBars(Object.entries(r.score_breakdown || {}).map(function (kv) { return [kv[0].replace(/_/g, ' '), kv[1]]; }));
            case 'final_aggregation':
                return `Overall reproducibility score <strong>${esc(r.overall_score)}/100</strong>` + DemoScores.miniBars(DemoScores.components(r));
        }
        return '';
    }

    function addFeedCard(id) {
        const n = T.nodes[id];
        document.getElementById('feed-empty').style.display = 'none';
        const card = document.createElement('div');
        card.className = 'feed-card' + (n.status === 'skipped' ? ' skipped' : '');
        card.innerHTML = `
            <div class="h"><i class="fas ${n.status === 'skipped' ? 'fa-forward text-muted' : 'fa-circle-check text-success'}"></i>
                ${esc(nodeName(id))}
                <span class="time">${n.status === 'skipped' ? 'skipped' : fmtDuration(n.real_duration) + (n.was_cached ? ' · cached' : '')}${n.tokens_in ? ' · ' + (n.tokens_in + n.tokens_out).toLocaleString() + ' tok' : ''}</span></div>
            <div class="b">${feedSummary(id)}</div>`;
        card.addEventListener('click', function () { openNode(id); });
        const placeholder = document.getElementById('feed-empty');
        placeholder.parentNode.insertBefore(card, placeholder.nextSibling);
    }

    function openNode(id) {
        const n = T.nodes[id];
        if (!n) return;
        const state = nodeState[id];
        document.getElementById('nodeModalTitle').textContent = nodeName(id);
        let body;
        if (state === 'pending' || state === 'running') {
            body = `<p class="text-muted"><i class="fas fa-hourglass-half mr-1"></i> This node has not finished yet.</p>`;
        } else {
            const def = T.dag.nodes.find(function (d) { return d.id === id; }) || {};
            body = `
                <p class="text-muted mb-2">${esc(def.description || '')}</p>
                <p class="small mb-3">
                    <span class="badge badge-light border">real duration ${fmtDuration(n.real_duration)}</span>
                    ${n.tokens_in ? '<span class="badge badge-light border">' + n.tokens_in.toLocaleString() + ' in / ' + n.tokens_out.toLocaleString() + ' out tokens</span>' : ''}
                    ${n.was_cached ? '<span class="badge badge-info">cached</span>' : ''}
                </p>
                ${NodeRenderers.renderResult(id, n.detail.artifacts) || '<p class="text-muted">No result artifact.</p>'}`;
        }
        document.getElementById('nodeModalBody').innerHTML = body;
        $('#nodeModal').modal('show');
    }

    // ---- Intake --------------------------------------------------------

    function renderIntake(t) {
        // t in [0, INTAKE_SECONDS)
        const set = function (id, state) {
            const li = document.getElementById(id);
            li.className = state;
            const ic = li.querySelector('.ic');
            ic.innerHTML = state === 'done' ? '<i class="fas fa-circle-check"></i>'
                : state === 'active' ? '<i class="fas fa-circle-notch fa-spin"></i>' : '<i class="far fa-circle"></i>';
        };
        set('step-upload', t < 1.2 ? 'active' : 'done');
        set('step-grobid', t < 1.2 ? '' : t < 5.2 ? 'active' : 'done');
        set('step-launch', t < 5.2 ? '' : 'active');
        const sections = T.paper.sections || [];
        const shown = t < 1.2 ? 0 : Math.min(sections.length, Math.ceil((t - 1.2) / 3.6 * sections.length));
        const chips = document.getElementById('grobid-chips');
        while (chips.childNodes.length < shown) {
            const s = document.createElement('span');
            s.textContent = sections[chips.childNodes.length];
            chips.appendChild(s);
        }
        document.getElementById('grobid-count').textContent = shown ? '(' + shown + ' sections)' : '';
    }

    // ---- Main loop -----------------------------------------------------

    function update() {
        let done = 0, tokens = 0;
        layout.ids.forEach(function (id) {
            const n = T.nodes[id];
            let state = 'pending';
            if (clock >= n.end) state = n.status === 'skipped' ? 'skipped' : (n.status === 'failed' ? 'failed' : 'completed');
            else if (clock >= n.start) state = 'running';

            const g = document.querySelector(`#dag .node[data-id="${id}"]`);
            if (state !== nodeState[id]) {
                const prev = nodeState[id];
                nodeState[id] = state;
                g.setAttribute('class', 'node ' + state);
                if ((state === 'completed' || state === 'skipped' || state === 'failed') && prev !== undefined) addFeedCard(id);
            }
            const sub = g.querySelector('.sub');
            if (state === 'running') {
                const p = (clock - n.start) / Math.max(n.end - n.start, 0.01);
                g.querySelector('.bar').setAttribute('width', Math.max(0, Math.min(1, p)) * (layout.pos[id].w - 20));
                sub.textContent = 'running…';
                tokens += (n.tokens_in + n.tokens_out) * Math.max(0, Math.min(1, p));
            } else if (state === 'completed') {
                sub.textContent = '✓ ' + fmtDuration(n.real_duration) + (n.was_cached ? ' · cached' : '');
                tokens += n.tokens_in + n.tokens_out;
                done++;
            } else if (state === 'skipped') {
                sub.textContent = 'skipped (not applicable)';
                done++;
            } else {
                sub.textContent = 'waiting';
            }
        });

        document.querySelectorAll('#dag .edge').forEach(function (e) {
            const from = nodeState[e.getAttribute('data-from')];
            const to = nodeState[e.getAttribute('data-to')];
            let cls = 'edge';
            if (to === 'skipped' || from === 'skipped') cls += ' skip';
            else if (to === 'running') cls += ' flow';
            else if (from === 'completed') cls += ' done';
            e.setAttribute('class', cls);
        });

        while (logPos < logQueue.length && logQueue[logPos].t <= clock) {
            printLog(logQueue[logPos++]);
        }

        document.getElementById('stat-time').textContent = fmtClock(clock);
        document.getElementById('stat-nodes').textContent = done + ' / ' + layout.ids.length;
        document.getElementById('stat-tokens').textContent = Math.round(tokens).toLocaleString();
    }

    function frame(now) {
        if (finished) return;
        const dt = lastFrame === null ? 0 : Math.min(0.25, (now - lastFrame) / 1000);
        lastFrame = now;
        clock += dt * speed;

        if (clock < 0) {
            renderIntake(clock + INTAKE_SECONDS);
        } else {
            const intake = document.getElementById('intake');
            if (intake.style.display !== 'none') {
                intake.style.display = 'none';
                printSys(`Workflow "${T.run.workflow}" v${T.run.version} started on "${T.paper.title}"`);
            }
            update();
            if (clock >= T.duration + 1.0) {
                finish();
                return;
            }
        }
        requestAnimationFrame(frame);
    }

    function finish() {
        finished = true;
        clock = Math.max(clock, T.duration + 0.01);
        update();
        printSys('Workflow completed. Final assessment ready.');
        document.getElementById('btn-report').style.display = '';
        showOutcome();
    }

    function showOutcome() {
        const f = T.final || {};
        document.getElementById('outcome').style.display = 'flex';
        DemoScores.gauge(document.getElementById('outcome-gauge'), f.overall_score);
        document.getElementById('outcome-subscores').innerHTML = DemoScores.components(f).map(function (r) {
            return `<div class="subscore"><div class="v" style="color:${DemoScores.color(r[1])}">${r[1] === null || r[1] === undefined ? 'N/A' : Number(r[1]).toFixed(1)}</div><div class="k">${esc(r[0])}</div></div>`;
        }).join('');
        const ev = T.evidence;
        const quotes = (ev.checklist || []).concat(ev.dataset || []).filter(function (c) { return c.present && c.evidence_text; }).length;
        document.getElementById('outcome-summary').textContent =
            quotes + ' pieces of supporting evidence will be highlighted in the paper. Processing time ' + fmtDuration(T.run.real_duration_s) + '.';
        if (opts.kiosk) {
            let left = 12;
            const tick = function () {
                document.getElementById('outcome-countdown').textContent = 'Opening the report in ' + left + 's';
                if (left-- <= 0) {
                    window.location = opts.reportUrl + '?kiosk=1' + (opts.nextUrl ? '&next=' + encodeURIComponent(opts.nextUrl) : '');
                    return;
                }
                setTimeout(tick, 1000);
            };
            tick();
        }
    }

    function skipToEnd() {
        if (finished) return;
        // Show only the tail of the log instead of dumping everything.
        const tail = logQueue.filter(function (l) { return l.t <= T.duration + 1; });
        logPos = logQueue.length;
        document.getElementById('intake').style.display = 'none';
        clock = T.duration + 1;
        update();
        tail.slice(-25).forEach(printLog);
        finish();
    }

    function bindControls() {
        document.querySelectorAll('[data-speed]').forEach(function (b) {
            b.addEventListener('click', function () {
                speed = Number(b.getAttribute('data-speed'));
                document.querySelectorAll('[data-speed]').forEach(function (x) { x.classList.toggle('active', x === b); });
            });
        });
        document.getElementById('btn-skip').addEventListener('click', skipToEnd);
        document.getElementById('btn-restart').addEventListener('click', function () { window.location.reload(); });
        document.getElementById('outcome-close').addEventListener('click', function () {
            document.getElementById('outcome').style.display = 'none';
        });
        document.addEventListener('keydown', function (e) {
            if (e.target.tagName === 'INPUT') return;
            if (e.key === 'ArrowRight' || e.key === 'End') skipToEnd();
            else if (e.key === 'r') window.location.reload();
            else if (e.key === 'Enter' && finished) window.location = opts.reportUrl;
        });
    }

    function start(options) {
        opts = options;
        bindControls();
        fetch(opts.timelineUrl).then(function (r) { return r.json(); }).then(function (data) {
            T = data;
            document.getElementById('intake-file').textContent = T.paper.pdf_name || 'paper.pdf';
            document.getElementById('intake-title').textContent = T.paper.title;
            document.getElementById('launch-text').textContent =
                `Launching workflow ${T.run.workflow} v${T.run.version} (${Object.keys(T.nodes).length} nodes)`;
            document.getElementById('step-upload').querySelector('div').textContent =
                opts.uploaded ? 'PDF uploaded' : 'Sample paper selected';
            document.getElementById('wf-name').textContent = T.run.workflow + ' · v' + T.run.version;
            document.getElementById('stat-real').textContent = fmtDuration(T.run.real_duration_s);
            drawDag();
            buildLogQueue();
            layout.ids.forEach(function (id) { nodeState[id] = undefined; });
            update();
            requestAnimationFrame(frame);
        });
    }

    global.DemoReplay = { start: start };
})(window);
