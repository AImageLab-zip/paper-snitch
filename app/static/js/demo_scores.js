/* Score gauge and mini bar charts shared by the demo replay and report pages. */
(function (global) {
    'use strict';

    const COLORS = { success: '#1abc9c', warning: '#f39c12', danger: '#e74c3c', secondary: '#aab4bc' };

    function color(v) {
        return COLORS[NodeRenderers.scoreClass(v)];
    }

    // Draw a ring gauge into an <svg viewBox="0 0 200 200">; animates from 0.
    function gauge(svg, value, opts) {
        opts = opts || {};
        const r = 80;
        const c = 2 * Math.PI * r;
        svg.innerHTML = `
            <circle class="track" cx="100" cy="100" r="${r}"></circle>
            <circle class="val" cx="100" cy="100" r="${r}" stroke="${color(value)}"
                    stroke-dasharray="${c}" stroke-dashoffset="${c}"></circle>
            <text class="num" x="100" y="112" text-anchor="middle">0</text>
            <text class="den" x="100" y="138" text-anchor="middle">/ 100</text>`;
        const arc = svg.querySelector('.val');
        const num = svg.querySelector('.num');
        const target = Math.max(0, Math.min(100, Number(value) || 0));
        const duration = opts.instant ? 0 : 1600;
        requestAnimationFrame(function () {
            arc.style.strokeDashoffset = c * (1 - target / 100);
        });
        const t0 = performance.now();
        (function tick(now) {
            const p = duration ? Math.min(1, (now - t0) / duration) : 1;
            const eased = 1 - Math.pow(1 - p, 3);
            num.textContent = (target * eased).toFixed(target % 1 ? 1 : 0);
            if (p < 1) requestAnimationFrame(tick);
        })(t0);
    }

    // rows: [[label, value], ...] -> grid of labelled bars.
    function miniBars(rows) {
        return '<div class="mini-bars">' + rows.filter(function (r) { return r[1] !== null && r[1] !== undefined; }).map(function (r) {
            const v = Number(r[1]);
            return `<span>${NodeRenderers.escapeHtml(r[0])}</span>
                    <div class="track"><div class="fill" style="width: ${Math.max(2, v)}%; background: ${color(v)};"></div></div>
                    <span class="font-weight-bold" style="font-variant-numeric: tabular-nums;">${v.toFixed(0)}</span>`;
        }).join('') + '</div>';
    }

    // Component scores of a final_aggregation result.
    function components(final) {
        const rows = [['Paper checklist', final.paper_checklist_score]];
        if (final.has_code_analysis) rows.push(['Code repository', final.code_analysis_score]);
        if (final.has_dataset_analysis) rows.push(['Dataset documentation', final.dataset_documentation_score]);
        return rows;
    }

    global.DemoScores = { color: color, gauge: gauge, miniBars: miniBars, components: components };
})(window);
