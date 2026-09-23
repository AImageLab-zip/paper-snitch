/*
 * Node result renderers for the paper-processing workflow.
 * Shared by the paper detail node modal and the demo replay/report pages.
 *
 * Markup uses Bootstrap 4 + FontAwesome classes. Every renderer takes the
 * node's artifacts dict (as returned by /workflow/node/<id>/) and returns HTML.
 */
(function (global) {
    'use strict';

    let uid = 0;
    function nextId(prefix) { uid += 1; return prefix + '-' + uid; }

    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
        return String(text).replace(/[&<>"']/g, function (m) { return map[m]; });
    }

    // List artifacts are stored as {"value": [...]}.
    function unwrap(artifact) {
        if (artifact && !Array.isArray(artifact) && Array.isArray(artifact.value)) return artifact.value;
        return artifact;
    }

    function scoreClass(v) {
        if (v === null || v === undefined) return 'secondary';
        return v >= 70 ? 'success' : v >= 40 ? 'warning' : 'danger';
    }

    function fmtScore(v) {
        return (v === null || v === undefined) ? 'N/A' : Number(v).toFixed(1) + '/100';
    }

    function titleCase(key) {
        return String(key).replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    }

    function scoreBar(label, value, applicable) {
        if (applicable === false || value === null || value === undefined) {
            return `
                <tr class="table-secondary">
                    <td style="vertical-align: middle;">${escapeHtml(label)}</td>
                    <td class="text-center" style="vertical-align: middle;"><span class="badge badge-secondary">N/A</span></td>
                </tr>`;
        }
        const pct = Number(value).toFixed(0);
        return `
            <tr>
                <td style="vertical-align: middle;">${escapeHtml(label)}</td>
                <td style="position: relative; vertical-align: middle; padding: 0.5rem; width: 45%;">
                    <div class="progress" style="height: 20px;">
                        <div class="progress-bar bg-${scoreClass(value)}" role="progressbar"
                             style="width: ${Math.max(pct, 5)}%" aria-valuenow="${value}" aria-valuemin="0" aria-valuemax="100"></div>
                    </div>
                    <span style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: 500; font-family: monospace; color: ${pct > 50 ? '#fff' : '#333'};">
                        ${fmtScore(value)}
                    </span>
                </td>
            </tr>`;
    }

    function scoreTable(title, icon, rows) {
        return `
            <div class="mb-3">
                <h6><i class="fas ${icon} text-success mr-2"></i>${title}</h6>
                <table class="table table-sm table-bordered mb-0">
                    <thead class="thead-light"><tr><th>Component</th><th>Score</th></tr></thead>
                    <tbody>${rows.join('')}</tbody>
                </table>
            </div>`;
    }

    function textList(title, icon, color, items) {
        if (!items || !items.length) return '';
        return `
            <div class="mb-3">
                <h6><i class="fas ${icon} text-${color} mr-2"></i>${title}</h6>
                <ul class="mb-0">${items.map(function (i) { return '<li>' + escapeHtml(i) + '</li>'; }).join('')}</ul>
            </div>`;
    }

    function paragraph(title, icon, text) {
        if (!text) return '';
        return `
            <div class="mb-3">
                <h6><i class="fas ${icon} text-primary mr-2"></i>${title}</h6>
                <p class="mb-0" style="white-space: pre-line;">${escapeHtml(text)}</p>
            </div>`;
    }

    function jsonToggle(obj, label) {
        const id = nextId('json');
        return `
            <div class="mt-3">
                <a class="btn btn-sm btn-outline-secondary" data-toggle="collapse" href="#${id}" role="button">
                    <i class="fas fa-code mr-1"></i> ${label || 'View Full JSON'}
                </a>
                <div class="collapse mt-2" id="${id}">
                    <pre class="bg-light p-3 rounded" style="max-height: 400px; overflow-y: auto;"><code>${escapeHtml(JSON.stringify(obj, null, 2))}</code></pre>
                </div>
            </div>`;
    }

    function card(headerClass, icon, title, badgeHtml, body) {
        return `
            <div class="card mb-3">
                <div class="card-header ${headerClass} text-white">
                    <h6 class="mb-0">
                        <i class="fas ${icon} mr-2"></i>${title}
                        ${badgeHtml ? '<span class="float-right">' + badgeHtml + '</span>' : ''}
                    </h6>
                </div>
                <div class="card-body">${body}</div>
            </div>`;
    }

    function yesNo(flag) {
        if (flag === null || flag === undefined) return '<span class="badge badge-secondary">n/a</span>';
        return flag ? '<span class="badge badge-success"><i class="fas fa-check"></i> Yes</span>'
                    : '<span class="badge badge-danger"><i class="fas fa-times"></i> No</span>';
    }

    const IMPORTANCE_BADGE = { critical: 'danger', important: 'warning', optional: 'secondary' };

    /*
     * Criteria table (reproducibility checklist or dataset documentation).
     * Rows carry data-criterion-id so the report page can link them to PDF highlights.
     */
    function criteriaTable(criteria, opts) {
        opts = opts || {};
        if (!criteria || !criteria.length) return '<p class="text-muted mb-0">No criteria analysed.</p>';
        const rows = criteria.map(function (c) {
            const conf = c.confidence !== undefined && c.confidence !== null ? Math.round(c.confidence * 100) : null;
            const evidence = c.evidence_text
                ? `<div class="criterion-evidence small text-muted mt-1">&ldquo;${escapeHtml(c.evidence_text)}&rdquo;
                      ${c.page_reference ? '<span class="badge badge-light ml-1">' + escapeHtml(c.page_reference) + '</span>' : ''}</div>`
                : '';
            const notes = c.notes ? `<div class="criterion-notes small mt-1">${escapeHtml(c.notes)}</div>` : '';
            return `
                <tr class="criterion-row" data-criterion-id="${escapeHtml((opts.idPrefix || '') + c.criterion_id)}">
                    <td class="text-muted">${escapeHtml(c.criterion_number)}</td>
                    <td>
                        <strong>${escapeHtml(c.criterion_name)}</strong>
                        <span class="badge badge-${IMPORTANCE_BADGE[c.importance] || 'light'} ml-1">${escapeHtml(c.importance)}</span>
                        <span class="badge badge-light ml-1">${escapeHtml(titleCase(c.category || ''))}</span>
                        <span class="criterion-locate ml-1"></span>
                        ${opts.compact ? '' : evidence + notes}
                    </td>
                    <td class="text-center" style="white-space: nowrap;">
                        ${c.present ? '<span class="badge badge-success"><i class="fas fa-check"></i> Present</span>'
                                    : '<span class="badge badge-danger"><i class="fas fa-times"></i> Missing</span>'}
                        ${conf !== null ? '<div class="small text-muted">conf. ' + conf + '%</div>' : ''}
                    </td>
                </tr>`;
        }).join('');
        const present = criteria.filter(function (c) { return c.present; }).length;
        return `
            <div class="small text-muted mb-1">${present} / ${criteria.length} criteria satisfied</div>
            <table class="table table-sm table-hover criteria-table mb-0">
                <thead class="thead-light"><tr><th style="width: 32px;">#</th><th>Criterion</th><th style="width: 110px;">Result</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    // ---- Per-node renderers ----------------------------------------------

    function renderPaperType(result) {
        const paperType = result.paper_type || 'unknown';
        const names = { method: 'method', dataset: 'dataset', both: 'Dataset&Method', theoretical: 'theoretical', unknown: 'unknown' };
        const colors = { method: 'primary', dataset: 'success', both: 'warning', theoretical: 'info', unknown: 'secondary' };
        const body = `
            <p><strong>Confidence:</strong> ${(result.confidence * 100).toFixed(1)}%</p>
            <p><strong>Reasoning:</strong> ${escapeHtml(result.reasoning)}</p>
            ${result.key_evidence && result.key_evidence.length ? `
                <h6>Key Evidence:</h6>
                <ul>${result.key_evidence.map(function (e) { return '<li>' + escapeHtml(e) + '</li>'; }).join('')}</ul>` : ''}
            ${jsonToggle(result)}`;
        return card('bg-info', 'fa-tag', 'Paper Type Classification',
            `<span class="badge badge-${colors[paperType] || 'secondary'}" style="font-size: 0.9rem;">${escapeHtml(names[paperType] || paperType).toUpperCase()}</span>`,
            body);
    }

    function renderSectionEmbeddings(result) {
        const types = result.section_types || [];
        const body = `
            <div class="row text-center mb-3">
                <div class="col"><div class="h4 mb-0">${escapeHtml(result.sections_processed)}</div><small class="text-muted">sections embedded</small></div>
                <div class="col"><div class="h4 mb-0">${escapeHtml(result.embedding_dimension)}</div><small class="text-muted">dimensions</small></div>
                <div class="col"><div class="h4 mb-0">${escapeHtml(result.estimated_tokens)}</div><small class="text-muted">tokens</small></div>
            </div>
            <p class="mb-1"><strong>Model:</strong> <code>${escapeHtml(result.embedding_model)}</code></p>
            <div>${types.map(function (t) { return '<span class="badge badge-light border mr-1 mb-1">' + escapeHtml(titleCase(t.toLowerCase())) + '</span>'; }).join('')}</div>`;
        return card('bg-secondary', 'fa-layer-group', 'Section Embeddings', '', body);
    }

    function renderCodeAvailability(result) {
        const body = `
            <table class="table table-sm mb-0">
                <tr><th style="width: 35%;">Code available</th><td>${yesNo(result.code_available)}</td></tr>
                ${result.code_url ? `<tr><th>Repository</th><td><a href="${escapeHtml(result.code_url)}" target="_blank" rel="noopener">${escapeHtml(result.code_url)}</a></td></tr>` : ''}
                <tr><th>Source</th><td>${result.found_online ? 'Found by online search' : 'Linked in the paper / paper database'}</td></tr>
                ${result.availability_notes ? `<tr><th>Notes</th><td>${escapeHtml(result.availability_notes)}</td></tr>` : ''}
            </table>`;
        return card(result.code_available ? 'bg-success' : 'bg-danger', 'fa-code-branch', 'Code Availability', '', body);
    }

    function renderCodeEmbedding(result) {
        const files = (result.embedded_files || []).map(function (f) { return f.file_path; });
        const uniqueFiles = Array.from(new Set(files));
        const body = `
            <div class="row text-center mb-3">
                <div class="col"><div class="h4 mb-0">${escapeHtml(result.total_files)}</div><small class="text-muted">files selected</small></div>
                <div class="col"><div class="h4 mb-0">${escapeHtml(result.total_chunks)}</div><small class="text-muted">chunks embedded</small></div>
                <div class="col"><div class="h4 mb-0">${escapeHtml(result.total_tokens)}</div><small class="text-muted">tokens</small></div>
            </div>
            ${uniqueFiles.length ? `<h6><i class="fas fa-file-code text-primary mr-2"></i>Files selected by the LLM</h6>
                <ul class="mb-2">${uniqueFiles.map(function (f) { return '<li><code>' + escapeHtml(f) + '</code></li>'; }).join('')}</ul>` : ''}
            ${result.tree_structure ? `<h6><i class="fas fa-sitemap text-primary mr-2"></i>Repository tree</h6>
                <pre class="bg-light p-2 rounded small" style="max-height: 220px; overflow-y: auto;">${escapeHtml(result.tree_structure)}</pre>` : ''}`;
        return card('bg-secondary', 'fa-cubes', 'Code Embedding', '', body);
    }

    function checkRow(label, flag, detail) {
        return `<tr><td>${escapeHtml(label)}</td><td style="width: 90px;">${yesNo(flag)}</td><td class="small text-muted">${detail || ''}</td></tr>`;
    }

    function codeChecklist(result) {
        const rs = result.repository_structure || {};
        const cc = result.code_components || {};
        const ar = result.artifacts || {};
        const ds = result.dataset_splits || {};
        const doc = result.documentation || {};
        const paths = function (p) { return (p || []).map(function (x) { return '<code>' + escapeHtml(x) + '</code>'; }).join(', '); };
        return `
            <table class="table table-sm mb-0">
                <tbody>
                    ${checkRow('Training code', cc.has_training_code, paths(cc.training_code_paths))}
                    ${checkRow('Evaluation code', cc.has_evaluation_code, paths(cc.evaluation_code_paths))}
                    ${checkRow('Documented run commands', cc.has_documented_commands, escapeHtml(cc.command_documentation_location))}
                    ${checkRow('Dependency specification', rs.has_requirements, escapeHtml((rs.requirements_issues || []).join(' ')))}
                    ${checkRow('Model checkpoints', ar.has_checkpoints, paths(ar.checkpoint_locations))}
                    ${checkRow('Dataset links', ar.has_dataset_links, ar.dataset_coverage ? 'coverage: ' + escapeHtml(ar.dataset_coverage) : '')}
                    ${checkRow('Splits provided', ds.splits_provided, escapeHtml(ds.splits_notes))}
                    ${checkRow('Random seeds documented', ds.random_seeds_documented, '')}
                    ${checkRow('README', doc.has_readme, '')}
                    ${checkRow('Results table', doc.has_results_table, '')}
                    ${checkRow('Reproduction commands', doc.has_reproduction_commands, escapeHtml(doc.documentation_notes))}
                </tbody>
            </table>`;
    }

    function renderCodeRepository(result) {
        if (result.reproducibility_score === undefined) {
            return card('bg-secondary', 'fa-code', 'Code Repository Analysis', '',
                `<p class="mb-0">${escapeHtml(result.overall_assessment || result.message || 'No code repository analysed.')}</p>${jsonToggle(result)}`);
        }
        const methodology = result.research_methodology || {};
        const applicability = {
            artifacts: methodology.requires_training !== false || methodology.requires_datasets !== false,
            dataset_splits: methodology.requires_splits !== false
        };
        const rows = Object.entries(result.score_breakdown || {}).map(function (kv) {
            return scoreBar(titleCase(kv[0]), kv[1], applicability[kv[0]]);
        });
        const body = `
            ${methodology.methodology_type ? `
                <div class="mb-3">
                    <h6><i class="fas fa-flask text-info mr-2"></i>Research Methodology</h6>
                    <span class="badge badge-info">${escapeHtml(titleCase(methodology.methodology_type))}</span>
                    ${methodology.methodology_notes ? '<div class="small text-muted mt-1">' + escapeHtml(methodology.methodology_notes) + '</div>' : ''}
                </div>` : ''}
            ${paragraph('Overall Assessment', 'fa-clipboard-check', result.overall_assessment)}
            ${rows.length ? scoreTable('Score Breakdown', 'fa-tasks', rows) : ''}
            <div class="mb-3">
                <h6><i class="fas fa-list-check text-primary mr-2"></i>Repository Checklist</h6>
                ${codeChecklist(result)}
            </div>
            ${textList('Recommendations', 'fa-lightbulb', 'warning', result.recommendations)}
            ${jsonToggle(result)}`;
        return card('bg-primary', 'fa-chart-bar', 'Code Reproducibility Analysis',
            `<span class="badge badge-light text-primary">Score: ${fmtScore(result.reproducibility_score)}</span>`, body);
    }

    function renderChecklist(result, artifacts) {
        const criteria = unwrap(artifacts.criterion_analyses);
        const rows = [
            scoreBar('Models', result.models_score),
            scoreBar('Datasets', result.datasets_score),
            scoreBar('Experiments', result.experiments_score)
        ];
        const body = `
            ${paragraph('Summary', 'fa-file-alt', result.summary)}
            ${scoreTable('Category Scores', 'fa-chart-pie', rows)}
            ${textList('Strengths', 'fa-check-circle', 'success', result.strengths)}
            ${textList('Weaknesses', 'fa-exclamation-triangle', 'danger', result.weaknesses)}
            ${Array.isArray(criteria) ? '<h6 class="mt-3"><i class="fas fa-clipboard-list text-info mr-2"></i>Criteria</h6>' + criteriaTable(criteria) : ''}`;
        return card('bg-primary', 'fa-clipboard-check', 'Paper Reproducibility Checklist',
            `<span class="badge badge-light text-primary">Score: ${fmtScore(result.weighted_score !== undefined ? result.weighted_score : result.overall_score)}</span>`, body);
    }

    function renderDataset(result, artifacts) {
        const criteria = unwrap(artifacts.criterion_analyses);
        const rows = [
            scoreBar('Data Collection', result.data_collection_score),
            scoreBar('Annotation', result.annotation_score),
            scoreBar('Ethics & Availability', result.ethics_availability_score)
        ];
        const body = `
            <table class="table table-sm mb-3">
                <tr><th style="width: 35%;">Dataset</th><td>${escapeHtml(result.dataset_name) || '<span class="text-muted">not stated</span>'}</td></tr>
                <tr><th>Size</th><td>${escapeHtml(result.dataset_size) || '<span class="text-muted">not stated</span>'}</td></tr>
                <tr><th>Download link</th><td>${result.download_link ? '<a href="' + escapeHtml(result.download_link) + '" target="_blank" rel="noopener">' + escapeHtml(result.download_link) + '</a>' : '<span class="text-muted">not provided</span>'}</td></tr>
            </table>
            ${paragraph('Summary', 'fa-file-alt', result.summary)}
            ${scoreTable('Category Scores', 'fa-chart-pie', rows)}
            ${textList('Strengths', 'fa-check-circle', 'success', result.strengths)}
            ${textList('Weaknesses', 'fa-exclamation-triangle', 'danger', result.weaknesses)}
            ${Array.isArray(criteria) ? '<h6 class="mt-3"><i class="fas fa-clipboard-list text-info mr-2"></i>Criteria</h6>' + criteriaTable(criteria, { idPrefix: 'ds:' }) : ''}`;
        return card('bg-success', 'fa-database', 'Dataset Documentation',
            `<span class="badge badge-light text-success">Score: ${fmtScore(result.overall_score)}</span>`, body);
    }

    function renderFinal(result) {
        const rows = [scoreBar('Paper Checklist', result.paper_checklist_score)];
        if (result.has_code_analysis) rows.push(scoreBar('Code Analysis', result.code_analysis_score));
        if (result.has_dataset_analysis) rows.push(scoreBar('Dataset Documentation', result.dataset_documentation_score));

        let details = '';
        const ed = result.evaluation_details;
        if (ed) {
            const sections = [];
            if (ed.paper_checklist) {
                sections.push(['Paper Checklist', 'fa-file-alt', criteriaTable(unwrap(ed.paper_checklist.criteria), { compact: true })]);
            }
            if (ed.code_analysis) {
                sections.push(['Code Analysis', 'fa-code', codeChecklist(ed.code_analysis)]);
            }
            if (ed.dataset_documentation) {
                sections.push(['Dataset Documentation', 'fa-database', criteriaTable(unwrap(ed.dataset_documentation.criteria), { compact: true, idPrefix: 'ds:' })]);
            }
            const accId = nextId('evaluationDetails');
            details = `
                <div class="mb-3">
                    <h6><i class="fas fa-clipboard-list text-info mr-2"></i>Detailed Evaluation Criteria</h6>
                    <div class="accordion" id="${accId}">
                        ${sections.map(function (s) {
                            const cid = nextId('evalSection');
                            return `
                                <div class="card">
                                    <div class="card-header p-2">
                                        <button class="btn btn-link btn-sm btn-block text-left" type="button" data-toggle="collapse" data-target="#${cid}">
                                            <i class="fas ${s[1]} mr-2"></i>${s[0]}<i class="fas fa-chevron-down float-right mt-1"></i>
                                        </button>
                                    </div>
                                    <div id="${cid}" class="collapse" data-parent="#${accId}">
                                        <div class="card-body p-2" style="max-height: 420px; overflow-y: auto;">${s[2]}</div>
                                    </div>
                                </div>`;
                        }).join('')}
                    </div>
                </div>`;
        }

        const body = `
            ${scoreTable('Component Scores', 'fa-chart-pie', rows)}
            ${paragraph('Executive Summary', 'fa-file-alt', result.executive_summary)}
            ${textList('Strengths', 'fa-check-circle', 'success', result.strengths)}
            ${textList('Weaknesses', 'fa-exclamation-triangle', 'danger', result.weaknesses)}
            ${textList('Recommendations', 'fa-lightbulb', 'warning', result.recommendations)}
            ${details}`;
        return card('bg-success', 'fa-trophy', 'Final Reproducibility Assessment',
            `<span class="badge badge-light text-success">Overall Score: ${escapeHtml(result.overall_score)}/100</span>`, body);
    }

    const RENDERERS = {
        paper_type_classification: renderPaperType,
        section_embeddings: renderSectionEmbeddings,
        code_availability_check: renderCodeAvailability,
        code_embedding: renderCodeEmbedding,
        code_repository_analysis: renderCodeRepository,
        reproducibility_checklist: renderChecklist,
        dataset_documentation_check: renderDataset,
        final_aggregation: renderFinal
    };

    // Guess the renderer from the result shape (older workflow versions use other node ids).
    function rendererForShape(result) {
        if (result.overall_score !== undefined && result.paper_checklist_score !== undefined && result.executive_summary) return renderFinal;
        if (result.reproducibility_score !== undefined) return renderCodeRepository;
        if (result.paper_type !== undefined) return renderPaperType;
        if (result.models_score !== undefined) return renderChecklist;
        if (result.data_collection_score !== undefined) return renderDataset;
        return null;
    }

    /*
     * Render the main 'result' artifact of a node.
     */
    function renderResult(nodeId, artifacts) {
        artifacts = artifacts || {};
        const result = artifacts.result;
        if (!result || typeof result !== 'object') {
            if (nodeId === 'dataset_documentation_check') {
                return '<div class="alert alert-light border mb-3"><i class="fas fa-forward mr-2"></i>Skipped: the paper does not introduce a dataset.</div>';
            }
            return '';
        }
        const renderer = RENDERERS[nodeId] || rendererForShape(result);
        if (renderer) {
            try {
                return renderer(result, artifacts);
            } catch (e) {
                console.error('Renderer failed for', nodeId, e);
            }
        }
        return `<pre class="bg-light p-3 rounded" style="max-height: 300px; overflow-y: auto;"><code>${escapeHtml(JSON.stringify(result, null, 2))}</code></pre>`;
    }

    // Remaining artifacts (not rendered by the result renderer) as collapsible JSON.
    function renderOtherArtifacts(artifacts) {
        const skip = { result: 1, token_usage: 1, criterion_analyses: 1 };
        return Object.entries(artifacts || {}).filter(function (kv) { return !skip[kv[0]]; }).map(function (kv) {
            return `<div class="mb-2"><h6 class="text-muted mb-0">${escapeHtml(kv[0])}</h6>${jsonToggle(kv[1], 'Show ' + escapeHtml(kv[0]))}</div>`;
        }).join('');
    }

    global.NodeRenderers = {
        escapeHtml: escapeHtml,
        unwrap: unwrap,
        scoreClass: scoreClass,
        criteriaTable: criteriaTable,
        renderResult: renderResult,
        renderOtherArtifacts: renderOtherArtifacts
    };
})(window);
