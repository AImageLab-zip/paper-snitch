/* Workflow DAG drawn as SVG: shared by the demo replay and the paper page. */
(function (global) {
    'use strict';

    const NODE_ICONS = {
        paper_type_classification: '',   // tag
        section_embeddings: '',          // layer-group
        dataset_documentation_check: '', // database
        reproducibility_checklist: '',   // clipboard-check
        code_availability_check: '',     // code-branch
        code_embedding: '',              // cubes
        code_repository_analysis: '',    // code
        final_aggregation: '',           // trophy
        join_parallel_branches: '\uf387'       // code-merge
    };

    // Vertical order of the parallel branches: paper analysis on top, code in
    // the middle, dataset at the bottom. Other nodes keep their DAG order.
    const BRANCH_ORDER = ['reproducibility_checklist', 'code_availability_check', 'dataset_documentation_check'];
    const LABEL_X = 36, LABEL_PAD = 10, LABEL_MIN_FONT = 10;
    const W = 172, H = 58, GX = 44, GY = 22, PAD = 8;

    function esc(t) {
        return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // nodes: [{id, name}] in definition order; edges: [{from, to}]
    function computeLayout(nodes, edges) {
        const ids = nodes.map(function (n) { return n.id; });
        const parents = {}, children = {};
        ids.forEach(function (id) { parents[id] = []; children[id] = []; });
        edges.forEach(function (e) {
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
        const rank = function (id) { const i = BRANCH_ORDER.indexOf(id); return i === -1 ? BRANCH_ORDER.length : i; };
        byLayer[widest].slice().sort(function (a, b) { return rank(a) - rank(b); })
            .forEach(function (id, i) { row[id] = i; });
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

        const pos = {};
        ids.forEach(function (id) {
            pos[id] = { x: PAD + layer[id] * (W + GX), y: PAD + row[id] * (H + GY), w: W, h: H };
        });
        return {
            ids: ids, pos: pos, parents: parents, layer: layer, gapX: GX,
            width: PAD * 2 + nLayers * W + (nLayers - 1) * GX,
            height: PAD * 2 + width * H + (width - 1) * GY
        };
    }

    // Shrink node labels that would overflow their box.
    function fitLabels(svg, layout) {
        svg.querySelectorAll('.node').forEach(function (g) {
            const label = g.querySelector('.label');
            const avail = layout.pos[g.getAttribute('data-id')].w - LABEL_X - LABEL_PAD;
            const width = label.getComputedTextLength();
            if (width <= avail) return;
            const size = parseFloat(getComputedStyle(label).fontSize);
            const fitted = Math.floor(size * avail / width * 10) / 10;
            label.style.fontSize = Math.max(fitted, LABEL_MIN_FONT) + 'px';
            if (fitted < LABEL_MIN_FONT) {
                label.setAttribute('textLength', avail);
                label.setAttribute('lengthAdjust', 'spacingAndGlyphs');
            }
        });
    }

    // Draw the graph into an <svg class="dag">. Returns the layout.
    // opts.onClick(nodeId) is called when a node is clicked.
    // opts.maxScale caps the upscaling of small graphs (e.g. a single node).
    function render(svg, graph, opts) {
        opts = opts || {};
        const layout = computeLayout(graph.nodes, graph.edges);
        const names = {};
        graph.nodes.forEach(function (n) { names[n.id] = n.name || n.id; });
        svg.setAttribute('viewBox', `0 0 ${layout.width} ${layout.height}`);
        svg.style.maxWidth = opts.maxScale ? (layout.width * opts.maxScale) + 'px' : '';
        let html = '';
        graph.edges.forEach(function (e) {
            const a = layout.pos[e.from], b = layout.pos[e.to];
            if (!a || !b) return;
            const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x;
            // Fan incoming edges out along the target's left side.
            const y2 = b.y + b.h / 2 + Math.max(-b.h / 3, Math.min(b.h / 3, (y1 - (b.y + b.h / 2)) / 4));
            // Edges that skip layers run along their own row and only bend in
            // the last gap, so they never pass behind intermediate nodes.
            const bendX = layout.layer[e.to] - layout.layer[e.from] > 1 ? x2 - layout.gapX : x1;
            const mx = (bendX + x2) / 2;
            html += `<path class="edge" data-from="${esc(e.from)}" data-to="${esc(e.to)}" d="M${x1},${y1} H${bendX} C${mx},${y1} ${mx},${y2} ${x2},${y2}"></path>`;
        });
        layout.ids.forEach(function (id) {
            const p = layout.pos[id];
            html += `
                <g class="node pending" data-id="${esc(id)}" transform="translate(${p.x},${p.y})">
                    <rect width="${p.w}" height="${p.h}" rx="12"></rect>
                    <text class="icon" x="14" y="25">${NODE_ICONS[id] || ''}</text>
                    <text class="label" x="${LABEL_X}" y="25">${esc(names[id])}</text>
                    <text class="sub" x="14" y="44">waiting</text>
                    <rect class="bar-bg" x="10" y="${p.h - 8}" width="${p.w - 20}" height="3" rx="1.5"></rect>
                    <rect class="bar" x="10" y="${p.h - 8}" width="0" height="3" rx="1.5"></rect>
                </g>`;
        });
        svg.innerHTML = html;
        fitLabels(svg, layout);
        if (opts.onClick) {
            svg.querySelectorAll('.node').forEach(function (g) {
                g.addEventListener('click', function () { opts.onClick(g.getAttribute('data-id')); });
            });
        }
        return layout;
    }

    function edgeClass(from, to) {
        if (to === 'skipped' || from === 'skipped' || to === 'cancelled' || from === 'cancelled') return 'edge skip';
        if (to === 'running') return 'edge flow';
        if (from === 'completed') return 'edge done';
        return 'edge';
    }

    // Apply {nodeId: {state, sub}} to an already rendered graph, in place.
    function setStates(svg, states) {
        Object.keys(states).forEach(function (id) {
            const g = svg.querySelector(`.node[data-id="${id}"]`);
            if (!g) return;
            g.setAttribute('class', 'node ' + states[id].state);
            if (states[id].sub !== undefined) g.querySelector('.sub').textContent = states[id].sub;
        });
        svg.querySelectorAll('.edge').forEach(function (e) {
            const from = states[e.getAttribute('data-from')], to = states[e.getAttribute('data-to')];
            e.setAttribute('class', edgeClass(from && from.state, to && to.state));
        });
    }

    global.DagView = { render: render, setStates: setStates, edgeClass: edgeClass, icons: NODE_ICONS };
})(window);
