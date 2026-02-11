
function interpolateColor(value) {
    value = Math.max(0, Math.min(100, value));
    const t = value / 100;

    // Hue 0..270 (rosso → violetto)
    const hue = t * 270;

    // Toni meno accesi: saturazione e luminosità moderate
    const saturation = 0.55; // 0.5–0.6 produce tonalità più vicine ai tuoi colori
    const brightness = 0.70;

    function hsvToRgb(h, s, v) {
        const c = v * s;
        const hh = (h / 60) % 6;
        const x = c * (1 - Math.abs((hh % 2) - 1));
        let r = 0, g = 0, b = 0;

        if (0 <= hh && hh < 1) { r = c; g = x; b = 0; }
        else if (1 <= hh && hh < 2) { r = x; g = c; b = 0; }
        else if (2 <= hh && hh < 3) { r = 0; g = c; b = x; }
        else if (3 <= hh && hh < 4) { r = 0; g = x; b = c; }
        else if (4 <= hh && hh < 5) { r = x; g = 0; b = c; }
        else if (5 <= hh && hh < 6) { r = c; g = 0; b = x; }

        const m = v - c;
        return {
            r: Math.round((r + m) * 255),
            g: Math.round((g + m) * 255),
            b: Math.round((b + m) * 255)
        };
    }

    function rgbToHex({ r, g, b }) {
        return (
            "#" +
            r.toString(16).padStart(2, "0") +
            g.toString(16).padStart(2, "0") +
            b.toString(16).padStart(2, "0")
        );
    }

    return rgbToHex(hsvToRgb(hue, saturation, brightness));
}

function loadAnalysisDetails(analysisId) {
    const modalContent = document.getElementById('analysis-modal-content');
    modalContent.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-spinner fa-spin fa-2x"></i>
                <p class="mt-2">Loading analysis...</p>
            </div>
        `;

    fetch(`/analysis/${analysisId}/`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                modalContent.innerHTML = `
                        <div class="alert alert-danger">
                            <strong>Error:</strong> ${data.error}
                        </div>
                    `;
                return;
            }

            modalContent.innerHTML = renderAnalysisDetails(data, true);
        })
        .catch(error => {
            modalContent.innerHTML = `
                    <div class="alert alert-danger">
                        <strong>Error:</strong> Failed to load analysis details.
                    </div>
                `;
        });
}

function renderAnalysisDetails(data, is_details = true) {
    const result = data.result;
    const uniqueId = Math.random().toString(36).slice(2, 11);

    // Icon mapping for known criteria - falls back to generic icon
    const criterionIcons = {
        'code': 'fa-code',
        'annotation': 'fa-tags',
        'preprocessing': 'fa-cogs',
        'evaluation': 'fa-chart-bar',
        'licensing': 'fa-balance-scale',
        'datasets': 'fa-database',
        'reproducibility': 'fa-redo',
        'methodology': 'fa-flask',
        'documentation': 'fa-book',
        'data_availability': 'fa-folder-open',
        'statistical_analysis': 'fa-calculator'
    };

    // Helper function to format criterion key to title
    function formatCriterionTitle(key) {
        return key
            .replace(/_/g, ' ')
            .replace(/\b\w/g, char => char.toUpperCase());
    }

    // Helper function to get icon for criterion
    function getCriterionIcon(key) {
        return criterionIcons[key] || 'fa-clipboard-check';
    }

    let html_start = `
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                    `;
    let html_end = `
                            <i class="fas fa-clock mr-1"></i>${data.duration}s |
                            <i class="fas fa-arrow-down mr-1"></i>Input: ${data.input_tokens} tokens |
                            <i class="fas fa-arrow-up mr-1"></i>Output: ${data.output_tokens} tokens
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="h4 mb-0 text-primary font-weight-bold">
                            ${data.final_score !== undefined ? data.final_score : 'N/A'}
                        </div>
                        <small class="text-muted">Final Score</small>
                    </div>
                </div>
            </div>
        `;
    let html_mid = ``;
    //For details 
    if (is_details) {
        html_mid = `
                        <h6 class="text-primary"><i class="fas fa-file-alt mr-2"></i>${data.paper_title}</h6>
                        <div class="text-muted small">
                            <span class="badge badge-info mr-2">${data.model_name}</span>
                            <i class="fas fa-calendar mr-1"></i>${data.created_at} |
                            `;
    }
    else {
        // For analysis
        html_mid = `
                        <div class="text-muted small">
                            `;
    }

    let html = html_start + html_mid + html_end;
    //For details 
    if (is_details) {
        if (data.error) {
            html += `
                <div class="alert alert-danger">
                    <strong>Error:</strong> ${data.error}
                </div>
            `;
            return html;
        }
    }

    if (is_details) {
        if (!result) {
            html += `<div class="alert alert-warning">No analysis data available.</div>`;
            return html;
        }
    }

    // Dynamically iterate over all criteria in the result
    for (const [criterionKey, criterionData] of Object.entries(result)) {
        // Skip if criterionData is not an object or doesn't have expected structure
        if (!criterionData || typeof criterionData !== 'object') {
            continue;
        }

        const icon = getCriterionIcon(criterionKey);
        const title = formatCriterionTitle(criterionKey);
        const score = typeof criterionData.score === 'number' ? criterionData.score : null;
        const collapseId = `${criterionKey}-${uniqueId}`;

        // Handle datasets specially if it has an 'extracted' array
        if (criterionKey === 'datasets' && Array.isArray(criterionData.extracted)) {
            html += `
                <div class="card criterion-card">
                    <div class="card-header bg-light collapsible" data-toggle="collapse" data-target="#${collapseId}" aria-expanded="true">
                        <div class="d-flex justify-content-between align-items-center">
                            <h6 class="mb-0"><i class="fas ${icon} mr-2"></i>${title}</h6>
                            <i class="fas fa-chevron-down toggle-icon"></i>
                        </div>
                    </div>
                    <div id="${collapseId}" class="collapse show">
                        <div class="card-body">
                            ${criterionData.extracted.length > 0
                    ? `<ul class="dataset-list mb-0">${criterionData.extracted.map(d => `<li>${d}</li>`).join('')}</ul>`
                    : '<p class="text-muted mb-0">No datasets identified</p>'}
                        </div>
                    </div>
                </div>
            `;
            continue;
        }

        // Render scored criterion section
        html += `
            <div class="card criterion-card">
                <div class="card-header bg-light collapsible" data-toggle="collapse" data-target="#${collapseId}" aria-expanded="true">
                    <div class="d-flex justify-content-between align-items-center">
                        <h6 class="mb-0">
                            <i class="fas ${icon} mr-2"></i>${title}
                            ${criterionKey === 'code' && criterionData.url
                ? `<a href="${criterionData.url}" target="_blank" class="btn btn-sm btn-outline-secondary ml-2">
                                       <i class="fas fa-external-link-alt mr-1"></i>View Repository
                                   </a>`
                : ''}
                        </h6>
                        <div class="d-flex align-items-center">
                            ${score !== null
                ? (score === -1
                    ? `<span class="score-badge score-${score} mr-2">n/a</span>`
                    : `<span class="score-badge score-${score} mr-2">${score}</span>`)
                : ''}
                            <i class="fas fa-chevron-down toggle-icon"></i>
                        </div>
                    </div>
                </div>
                <div id="${collapseId}" class="collapse show">
                    <div class="card-body">
                        ${criterionData.extracted
                ? `
                                <h6 class="text-muted">Extracted Information:</h6>
                                <div class="extracted-text">${criterionData.extracted}</div>
                                ${criterionData.score_explanation
                    ? `<h6 class="text-muted mt-3">Score Explanation:</h6><p class="mb-0">${criterionData.score_explanation}</p>`
                    : ''}
                              `
                : '<p class="text-muted mb-0">No information extracted for this criterion</p>'}
                    </div>
                </div>
            </div>
        `;
    }

    return html;
}

function renderLocatorsDetails(data, is_details = true) {

    const result = data.result;
    const uniqueId = Math.random().toString(36).slice(2, 11);

    // --- 1. Metadata Header ---
    // We strictly render values present in the 'data' object.

    let metaHtml = '';

    // Check for common metadata fields and append them if they exist
    const metaFields = [];
    if (data.duration !== undefined) metaFields.push(`<i class="fas fa-clock mr-1"></i>${data.duration}s`);
    if (data.input_tokens !== undefined) metaFields.push(`<i class="fas fa-arrow-down mr-1"></i>In: ${data.input_tokens}`);
    if (data.output_tokens !== undefined) metaFields.push(`<i class="fas fa-arrow-up mr-1"></i>Out: ${data.output_tokens}`);

    // Build Header HTML
    let html = `
    <div class="mb-3">
        <div class="d-flex justify-content-between align-items-start">
            <div>
                    ${is_details && data.paper_title ? `<h6 class="text-primary"><i class="fas fa-file-alt mr-2"></i>${data.paper_title}</h6>` : ''}
                    <div class="text-muted small">
                    ${data.model_name ? `<span class="badge badge-info mr-2">${data.model_name}</span>` : ''}
                    ${data.created_at ? `<i class="fas fa-calendar mr-1"></i>${data.created_at} |` : ''}
                    ${metaFields.join(' | ')}
                    </div>
            </div>
            ${data.final_score !== undefined ? `
            <div class="text-right">
                <div class="h4 mb-0 text-primary font-weight-bold">${data.final_score}</div>
                <small class="text-muted">Score</small>
            </div>` : ''}
        </div>
    </div>
`;

    // Handle Errors or Missing Data
    if (data.error) {
        html += `<div class="alert alert-danger"><strong>Error:</strong> ${data.error}</div>`;
        return html;
    }

    if (!result || typeof result !== 'object') {
        html += `<div class="alert alert-warning">No analysis data available.</div>`;
        return html;
    }

    // Grouping Logic
    const metadata = window.categoriesMetadata || {};
    const grouped = {};
    const hasMetadata = Object.keys(metadata).length > 0;

    // Iterate over whatever keys are returned in the result object
    for (const [key, items] of Object.entries(result)) {
        const meta = metadata[key] || {};
        let parentName = meta.parent;
        let color = meta.color || '#e9ecef';

        if (!parentName) {
            // Fallback logic
            parentName = hasMetadata ? (meta.description ? 'Other' : 'Uncategorized') : key;
            if (!hasMetadata) {
                parentName = key;
            }
        }

        if (!grouped[parentName]) {
            grouped[parentName] = [];
        }

        grouped[parentName].push({
            name: key,
            items: Array.isArray(items) ? items : [items],
            color: color
        });
    }

    if (Object.keys(grouped).length === 0) {
        html += `<div class="alert alert-info">No locators found.</div>`;
        return html;
    }

    const sortOrder = Object.keys(grouped).sort((a, b) => {
        const orderA = (metadata[a] && metadata[a].order) !== undefined ? metadata[a].order : 999;
        const orderB = (metadata[b] && metadata[b].order) !== undefined ? metadata[b].order : 999;
        return orderA - orderB || a.localeCompare(b);
    });

    // --- 2. Dynamic Content Generation ---
    for (const parentName of sortOrder) {
        // Sort subcategories alphabetically
        const subcategories = grouped[parentName].sort((a, b) => a.name.localeCompare(b.name));

        const collapseId = `cat-${uniqueId}-${parentName.replace(/\s+/g, '-')}`;

        const totalItems = subcategories.reduce((acc, sub) => acc + sub.items.length, 0);

        // Build Inner HTML
        let contentHtml = '';

        subcategories.forEach((sub, idx) => {
            const listHtml = sub.items.length > 0 ?
                `<ul style="list-style-type: disc;" class="pl-4 mb-2">
                ${sub.items.map(item => `<li class="py-1">${item}</li>`).join('')}
                </ul>` : '<div class="text-muted small pl-3 mb-2">No items extracted.</div>';

            const showSubHeader = hasMetadata || subcategories.length > 1 || sub.name !== parentName;

            if (showSubHeader) {
                const subCollapseId = `sub-${collapseId}-${idx}`;
                contentHtml += `
                    <div class="mb-2">
                        <div class="p-2 rounded mb-1 d-flex align-items-center collapsed" 
                             style="background-color: ${sub.color}40; border-left: 4px solid ${sub.color}; cursor: pointer;"
                             data-toggle="collapse"
                             data-target="#${subCollapseId}"
                             aria-expanded="false">
                             <span class="badge badge-dot mr-2" style="background-color: ${sub.color};"></span>
                             <strong class="text-dark">${sub.name}</strong>
                             <span class="badge badge-light ml-auto">${sub.items.length}</span>
                        </div>
                        <div id="${subCollapseId}" class="collapse">
                            <div class="pt-1">
                                ${listHtml}
                            </div>
                        </div>
                    </div>
                 `;
            } else {
                contentHtml += listHtml;
            }
        });

        // Build the Card HTML
        html += `
        <div class="card mb-2 shadow-sm">
            <div class="card-header bg-light py-2 px-3 collapsible" 
                    data-toggle="collapse" 
                    data-target="#${collapseId}" 
                    aria-expanded="true" 
                    style="cursor: pointer;">
                <div class="d-flex justify-content-between align-items-center">
                    <h6 class="mb-0 text-dark font-weight-bold">
                        ${parentName}
                        <span class="badge badge-pill badge-light border ml-2">${totalItems}</span>
                    </h6>
                    <i class="fas fa-chevron-down text-muted toggle-icon"></i>
                </div>
            </div>
            <div id="${collapseId}" class="collapse show">
                <div class="card-body p-2">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
    }

    return html;
}


