"""
Build the replay timeline for a completed workflow run.

Nodes are scheduled along the DAG: each node starts when its parents have
finished and runs for a compressed version of its real duration
(sqrt(duration) + a small constant), then everything is scaled to the target
length. Real timestamps are not used directly because reruns and queueing make
them inconsistent with the DAG order. Log lines keep their relative position
within their node.
"""

import math
import re
from collections import defaultdict
from datetime import datetime

from webApp.views import node_detail_payload

MIN_DURATION = 0.8
EDGE_GAP = 0.3
MAX_LOGS_PER_NODE = 40
MAX_LOG_CHARS = 220
SECTION_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9 &:/'-]{1,60}$")

# Checklist-style nodes only log a few lines while evaluating many criteria in
# parallel; their per-criterion results are shown as log lines instead.
CRITERIA_NODES = {
    "reproducibility_checklist": "Criterion",
    "dataset_documentation_check": "Dataset criterion",
}


def _unwrap(artifact):
    if isinstance(artifact, dict) and isinstance(artifact.get("value"), list):
        return artifact["value"]
    return artifact


def _schedule(nodes, edges, target_duration=None):
    """
    Return {node_id: (start, end)} respecting the DAG. With a target duration,
    durations are compressed and scaled to it (display seconds); without one,
    real node durations are used (seconds of processing on the critical path).
    """
    parents = defaultdict(list)
    for e in edges:
        if e["from"] in nodes and e["to"] in nodes:
            parents[e["to"]].append(e["from"])

    weight = {}
    for node_id, n in nodes.items():
        real = max(n.duration or 0.0, 0.0)
        weight[node_id] = math.sqrt(real) + MIN_DURATION if target_duration else real

    times = {}

    def place(node_id, visiting=()):
        if node_id in times:
            return times[node_id]
        start = 0.0
        for p in parents[node_id]:
            if p not in visiting:
                gap = EDGE_GAP if target_duration else 0.0
                start = max(start, place(p, visiting + (node_id,))[1] + gap)
        times[node_id] = (start, start + weight[node_id])
        return times[node_id]

    for node_id in nodes:
        place(node_id)
    if not target_duration:
        return times
    total = max(end for _, end in times.values()) or 1.0
    scale = target_duration / total
    return {k: (s * scale, e * scale) for k, (s, e) in times.items()}


def _is_skipped(detail):
    if detail["status"] == "skipped":
        return True
    has_result = isinstance(detail["artifacts"].get("result"), dict)
    skipped_log = any("skip" in log["message"].lower() for log in detail["logs"])
    return detail["status"] == "completed" and not has_result and skipped_log


def _sample(items, limit):
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def _criteria_logs(node_id, detail, start, end):
    criteria = _unwrap(detail["artifacts"].get("criterion_analyses"))
    if not isinstance(criteria, list) or not criteria:
        return []
    prefix = CRITERIA_NODES[node_id]
    span = max(end - start, 0.1)
    logs = []
    for i, c in enumerate(criteria):
        verdict = "present" if c.get("present") else "missing"
        conf = c.get("confidence")
        logs.append(
            {
                "t": round(start + span * (i + 1) / (len(criteria) + 1), 3),
                "level": "INFO" if c.get("present") else "WARNING",
                "message": f"{prefix} {i + 1}/{len(criteria)} "
                f"{c.get('criterion_name')} [{c.get('importance')}] -> {verdict}"
                + (f" (confidence {conf:.2f})" if isinstance(conf, (int, float)) else ""),
            }
        )
    return logs


def build_timeline(run, target_duration=75, scenario=None):
    paper = run.paper
    dag = run.workflow_definition.dag_structure or {}
    nodes = {n.node_id: n for n in run.nodes.all()}
    details = {node_id: node_detail_payload(n) for node_id, n in nodes.items()}

    schedule = _schedule(nodes, dag.get("edges", []), target_duration)

    timeline_nodes = {}
    total_in = total_out = 0
    for node_id, n in nodes.items():
        detail = details[node_id]
        start, end = schedule[node_id]
        skipped = _is_skipped(detail)
        real_start = n.started_at.timestamp() if n.started_at else None
        real_span = n.duration or 0.0

        logs = []
        for log in detail["logs"]:
            frac = 0.0
            if real_start is not None and real_span > 0:
                ts = datetime.fromisoformat(log["timestamp"]).timestamp()
                frac = min(max((ts - real_start) / real_span, 0.0), 1.0)
            logs.append(
                {
                    "t": round(start + frac * (end - start), 3),
                    "level": log["level"],
                    "message": log["message"][:MAX_LOG_CHARS],
                }
            )
        logs = _sample(logs, MAX_LOGS_PER_NODE)
        if node_id in CRITERIA_NODES and not skipped:
            logs = sorted(logs + _criteria_logs(node_id, detail, start, end), key=lambda l: l["t"])

        # Embedding vectors are large and useless for display.
        result = detail["artifacts"].get("result")
        if isinstance(result, dict):
            for f in result.get("embedded_files", []):
                f.pop("embedding", None)
                f["file_content"] = (f.get("file_content") or "")[:400]
        detail.pop("logs", None)
        detail.pop("input_data", None)

        tokens_in = n.input_tokens or 0
        tokens_out = n.output_tokens or 0
        total_in += tokens_in
        total_out += tokens_out
        timeline_nodes[node_id] = {
            "start": round(start, 3),
            "end": round(end, 3),
            "status": "skipped" if skipped else n.status,
            "real_duration": round(n.duration or 0.0, 2),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "was_cached": n.was_cached,
            "logs": logs,
            "detail": detail,
        }

    def result_of(node_id):
        node = details.get(node_id)
        return node["artifacts"].get("result") if node else None

    def criteria_of(node_id):
        node = details.get(node_id)
        value = _unwrap(node["artifacts"].get("criterion_analyses")) if node else None
        return value if isinstance(value, list) else []

    paper_type = result_of("paper_type_classification") or {}
    # Processing time along the critical path; the run's wall-clock time can
    # include queueing and partial reruns.
    real_schedule = _schedule(nodes, dag.get("edges", []))
    real_duration = max((end for _, end in real_schedule.values()), default=None)

    return {
        "scenario": {"id": scenario.id, "label": scenario.label} if scenario else None,
        "paper": {
            "id": paper.id,
            "title": paper.title,
            "authors": paper.authors,
            "conference": str(paper.conference) if paper.conference_id else None,
            "pdf_name": paper.file.name.rsplit("/", 1)[-1] if paper.file else None,
            "sections": [
                name for name in (paper.sections if isinstance(paper.sections, dict) else {})
                if SECTION_NAME.match(name)
            ],
            "code_url": paper.code_url,
        },
        "run": {
            "id": str(run.id),
            "run_number": run.run_number,
            "workflow": run.workflow_definition.name,
            "version": run.workflow_definition.version,
            "real_duration_s": real_duration,
            "tokens_in": total_in,
            "tokens_out": total_out,
        },
        "duration": target_duration,
        "dag": {
            "nodes": [{"id": d["id"], "name": d.get("name", d["id"]), "description": d.get("description", "")} for d in dag.get("nodes", [])],
            "edges": [{"from": e["from"], "to": e["to"], "type": e.get("type")} for e in dag.get("edges", [])],
        },
        "nodes": timeline_nodes,
        "final": result_of("final_aggregation"),
        "evidence": {
            "checklist": criteria_of("reproducibility_checklist"),
            "dataset": criteria_of("dataset_documentation_check"),
            "paper_type": paper_type.get("key_evidence") or [],
        },
    }
