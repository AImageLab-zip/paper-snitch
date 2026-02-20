# Token Statistics Improvements

## Overview

This document describes improvements to the token statistics system to provide more accurate and detailed analysis of API token usage across conferences and workflow nodes.

## Key Changes

### 1. Latest Run Per Paper (Not All Runs)

**Problem:** Previous implementation averaged ALL completed workflow runs, which inflated statistics when papers were re-analyzed.

**Solution:** Statistics now use only the **latest completed workflow run per paper**, providing accurate current-state analysis.

**Impact:**
- Averages reflect actual current token usage per paper
- Standard deviations are more meaningful
- Statistics are not skewed by historical re-runs

### 2. Split Statistics by Token Type

**Problem:** Only total tokens were displayed as averages.

**Solution:** Now display separate statistics for:
- **Input tokens** (tokens sent to API)
- **Output tokens** (tokens received from API)
- **Total tokens** (sum of input + output)

Each with its own average and standard deviation.

**Impact:**
- Better cost analysis (input/output have different pricing)
- Identify which direction (input vs output) varies more
- More detailed reporting for budgeting

### 3. Per-Node Token Statistics

**Problem:** No visibility into which workflow nodes consume most tokens.

**Solution:** Conference detail page now shows per-node averages with standard deviations.

**Impact:**
- Identify expensive nodes in workflows
- Optimize workflows by targeting high-token nodes
- Compare token usage across different node types

## Implementation Details

### Helper Functions

Two new helper functions in [views.py](app/webApp/views.py):

#### 1. `compute_conference_token_statistics(conferences)`

Computes per-conference statistics from latest runs:

```python
def compute_conference_token_statistics(conferences):
    """
    Compute token statistics for conferences based on latest workflow run per paper.
    
    Adds these attributes to each conference:
    - avg_input_tokens, stddev_input_tokens
    - avg_output_tokens, stddev_output_tokens
    - avg_total_tokens, stddev_total_tokens
    """
```

**Algorithm:**
1. Get latest completed run per paper for all conferences
2. Group token values by conference
3. Compute mean and standard deviation for each token type
4. Attach results as attributes to conference objects

**Efficiency:** Single database query with filtering, processes results in Python

#### 2. `compute_node_statistics(conference_id)`

Computes per-node statistics for a conference:

```python
def compute_node_statistics(conference_id):
    """
    Compute per-node token statistics for a conference based on latest workflow runs.
    
    Returns dict:
    {
        'node_name': {
            'avg_input_tokens': float,
            'stddev_input_tokens': float,
            'avg_output_tokens': float,
            'stddev_output_tokens': float,
            'avg_total_tokens': float,
            'stddev_total_tokens': float,
            'count': int
        }
    }
    """
```

**Algorithm:**
1. Get latest completed run per paper for conference
2. Fetch all nodes from these runs
3. Group by node_id
4. Compute statistics for each node
5. Return as dictionary

**Efficiency:** Two database queries (latest runs + nodes), group/compute in Python

### View Updates

#### ConferenceListView

**File:** [webApp/views.py](app/webApp/views.py#L734-L770)

**Changes:**
- Removed old `avg_tokens_per_paper` annotation (was averaging all runs)
- Call `compute_conference_token_statistics(list(page_obj))` after pagination
- Statistics computed only for displayed conferences (20 per page)

**Performance:** Minimal overhead (~2 queries for 20 conferences)

#### ConferenceDetailView

**File:** [webApp/views.py](app/webApp/views.py#L773-L850)

**Changes:**
- Call `compute_node_statistics(conference_id)` to get per-node stats
- Add `node_statistics` to template context

**Performance:** 2 additional queries (latest runs + nodes)

### Template Updates

#### Conference List Template

**File:** [conference_list.html](app/webApp/templates/webApp/conference_list.html#L89-L137)

**Display:**
```
📄 15 papers
💰 125,450 total tokens

Latest Run Averages (per paper):
↓ Input: 8,200 (±1,500)
↑ Output: 163 (±50)
= Total: 8,363 (±1,520)
```

**Icons:**
- 🔽 (arrow-down) for input tokens
- 🔼 (arrow-up) for output tokens
- = (equals) for total tokens

#### Conference Detail Template

**File:** [conference_detail.html](app/webApp/templates/webApp/conference_detail.html#L50-L133)

**New Section:** "Workflow Node Statistics" card displayed between conference header and papers list

**Display:**
```
┌────────────────────────────────────────────────────────────────┐
│ Workflow Node Statistics (Latest Run per Paper)               │
├─────────────────────┬──────┬────────────┬────────────┬────────┤
│ Node                │Papers│ Avg Input  │ Avg Output │  Total │
├─────────────────────┼──────┼────────────┼────────────┼────────┤
│ Paper Type Class.   │  15  │ 1,200 (±80)│  50 (±12)  │ 1,250  │
│ Section Embeddings  │  15  │ 3,500(±450)│   0        │ 3,500  │
│ Code Availability   │  15  │ 2,500(±800)│  80 (±25)  │ 2,580  │
│ Code Repo Analysis  │  12  │ 1,000(±300)│  33 (±10)  │ 1,033  │
└─────────────────────┴──────┴────────────┴────────────┴────────┘
```

**Features:**
- Color-coded: Input (blue), Output (green), Total (bold)
- Paper count shows how many papers have this node
- Standard deviations in parentheses
- Node names formatted nicely (title case, underscores replaced)

## Statistical Details

### Mean (Average)

```python
avg = statistics.mean(values)
```

Central tendency of token usage. Represents typical token consumption for a paper/node.

### Standard Deviation

```python
stddev = statistics.stdev(values) if len(values) > 1 else 0
```

Measure of variability/spread in token usage:
- **Low stddev**: Consistent token usage across papers
- **High stddev**: Large variation (some papers use much more/less than average)

**Note:** Requires at least 2 data points. Returns 0 for single-paper conferences.

### Interpreting Results

**Example Conference Statistics:**
```
Input: 8,200 (±1,500)
Output: 163 (±50)
Total: 8,363 (±1,520)
```

**Interpretation:**
- 68% of papers use 6,700-9,700 input tokens (±1σ)
- Output is much more consistent (163 ± 50 vs 8,200 ± 1,500)
- Total variance dominated by input variance

**Example Node Statistics:**
```
Code Availability: 2,500 (±800) input tokens
Section Embeddings: 3,500 (±450) input tokens
```

**Interpretation:**
- Code availability has higher variance (±800 vs ±450)
- Likely due to variable search queries/results
- Section embeddings more predictable (depends on paper length)

## Use Cases

### 1. Conference Budget Planning

**Scenario:** Estimate costs for analyzing a new conference

**Approach:**
1. Find similar conference (same field/year)
2. Look at "Latest Run Averages"
3. Multiply by expected paper count

**Example:**
```
Conference A (similar): 8,363 total tokens/paper (±1,520)
New Conference B: Expecting 50 papers

Estimated tokens: 50 × 8,363 = 418,150 tokens
Conservative estimate (mean + 1σ): 50 × (8,363 + 1,520) = 494,150 tokens

Cost calculation (OpenAI gpt-4o-mini):
- Input: 50 × 8,200 × $0.003/1K = $1.23
- Output: 50 × 163 × $0.012/1K = $0.10
- Total: $1.33

Conservative: $1.58
```

### 2. Workflow Optimization

**Scenario:** Reduce token costs by optimizing expensive nodes

**Approach:**
1. View per-node statistics in conference detail
2. Identify nodes with highest avg_total_tokens
3. Optimize those nodes first (biggest impact)

**Example:**
```
Node Statistics:
- Section Embeddings: 3,500 tokens (42% of total)
- Code Availability: 2,580 tokens (31% of total)
- Paper Type: 1,250 tokens (15% of total)
- Repo Analysis: 1,033 tokens (12% of total)

Optimization Priority:
1. Section Embeddings (highest usage)
   → Consider caching, reduce sections, or use smaller model
2. Code Availability (high variance ±800)
   → Optimize search query strategy
```

### 3. Anomaly Detection

**Scenario:** Identify papers with unusual token usage

**Approach:**
1. Check conference stddev values
2. Papers outside mean ± 2σ are unusual (95% confidence)
3. Investigate those papers for errors/special cases

**Example:**
```
Conference avg: 8,363 (±1,520)
Threshold: 8,363 ± 2(1,520) = 5,323 to 11,403

Paper using 15,000 tokens → Anomaly!
Investigate: Unusually long paper? Processing error? Different workflow?
```

### 4. A/B Testing Workflows

**Scenario:** Compare two workflow versions

**Approach:**
1. Run subset of papers with Workflow A
2. Run another subset with Workflow B
3. Compare per-node statistics

**Example:**
```
Workflow A:
- Code Availability: 2,500 (±800)

Workflow B (optimized):
- Code Availability: 1,800 (±600)

Result: 28% reduction in tokens, 25% reduction in variance
```

## Query Patterns

### Get Latest Run Statistics for Conference

```python
from webApp.views import compute_conference_token_statistics
from webApp.models import Conference

conference = Conference.objects.get(id=1)
compute_conference_token_statistics([conference])

print(f"Avg input: {conference.avg_input_tokens:.0f}")
print(f"Stddev input: {conference.stddev_input_tokens:.0f}")
print(f"Avg output: {conference.avg_output_tokens:.0f}")
print(f"Stddev output: {conference.stddev_output_tokens:.0f}")
print(f"Avg total: {conference.avg_total_tokens:.0f}")
print(f"Stddev total: {conference.stddev_total_tokens:.0f}")
```

### Get Per-Node Statistics

```python
from webApp.views import compute_node_statistics

stats = compute_node_statistics(conference_id=1)

for node_id, node_stats in stats.items():
    print(f"\n{node_id}:")
    print(f"  Papers: {node_stats['count']}")
    print(f"  Avg input: {node_stats['avg_input_tokens']:.0f}")
    print(f"  Avg output: {node_stats['avg_output_tokens']:.0f}")
    print(f"  Avg total: {node_stats['avg_total_tokens']:.0f}")
```

### Get Latest Run for Paper (Manual)

```python
from workflow_engine.models import WorkflowRun

latest_run = WorkflowRun.objects.filter(
    paper_id=paper_id,
    status='completed'
).order_by('-created_at').first()

if latest_run:
    print(f"Input: {latest_run.input_tokens}")
    print(f"Output: {latest_run.output_tokens}")
    print(f"Total: {latest_run.total_tokens}")
```

## Performance Considerations

### Conference List View

**Queries:**
1. Get conferences with annotations (paper_count, total_tokens)
2. Get latest runs for papers in displayed conferences
3. Fetch token data for those runs

**Total:** 3 queries for 20 conferences

**Pagination Impact:** Statistics computed only for current page (20 conferences), not entire dataset

### Conference Detail View

**Queries:**
1. Get conference
2. Get papers with annotations
3. Get latest runs for papers in conference
4. Get nodes from those runs

**Total:** 4 queries

**Pagination Impact:** Node statistics computed for entire conference (all papers), not just displayed page

**Rationale:** Per-node stats show conference-wide patterns, need all papers for accuracy

### Optimization Tips

1. **Caching:** Cache node statistics (rarely change):
   ```python
   from django.core.cache import cache
   
   cache_key = f'node_stats_{conference_id}'
   stats = cache.get(cache_key)
   if not stats:
       stats = compute_node_statistics(conference_id)
       cache.set(cache_key, stats, 3600)  # 1 hour
   ```

2. **Background Jobs:** Pre-compute statistics with Celery:
   ```python
   @shared_task
   def update_conference_statistics(conference_id):
       stats = compute_node_statistics(conference_id)
       cache.set(f'node_stats_{conference_id}', stats, 86400)  # 24 hours
   ```

3. **Database Views:** Create materialized view for latest runs:
   ```sql
   CREATE MATERIALIZED VIEW latest_workflow_runs AS
   SELECT DISTINCT ON (paper_id)
       paper_id, 
       id as workflow_run_id,
       input_tokens, 
       output_tokens, 
       total_tokens
   FROM workflow_run
   WHERE status = 'completed'
   ORDER BY paper_id, created_at DESC;
   ```

## Comparison: Before vs After

### Before

**Conference List:**
```
📄 15 papers
💰 125,450 tokens
📊 Avg: 8,363 tokens/paper  ← Averaged ALL runs
```

**Problems:**
- If papers re-analyzed 2x, avg was inflated
- No split by input/output
- No standard deviation
- No per-node visibility

### After

**Conference List:**
```
📄 15 papers
💰 125,450 total tokens (all runs)

Latest Run Averages (per paper):
↓ Input: 8,200 (±1,500)
↑ Output: 163 (±50)
= Total: 8,363 (±1,520)
```

**Conference Detail:**
```
┌─ Workflow Node Statistics ────────────────┐
│ Code Availability: 2,580 tokens (±800)    │
│ Section Embeddings: 3,500 tokens (±450)   │
│ ...                                        │
└───────────────────────────────────────────┘
```

**Improvements:**
✅ Latest run per paper (not all runs)
✅ Input/output/total split
✅ Standard deviations
✅ Per-node statistics
✅ Variance analysis possible

## Testing

### 1. Verify Statistics Computation

```bash
python manage.py shell
```

```python
from webApp.views import compute_conference_token_statistics
from webApp.models import Conference

conferences = Conference.objects.all()[:5]
compute_conference_token_statistics(list(conferences))

for conf in conferences:
    print(f"\n{conf.name}:")
    print(f"  Avg input: {conf.avg_input_tokens}")
    print(f"  Stddev input: {conf.stddev_input_tokens}")
    print(f"  Avg total: {conf.avg_total_tokens}")
```

### 2. Verify Per-Node Statistics

```python
from webApp.views import compute_node_statistics

stats = compute_node_statistics(1)  # Conference ID 1
for node_id, data in stats.items():
    print(f"{node_id}: {data['avg_total_tokens']:.0f} tokens")
```

### 3. Check UI Display

1. Navigate to conference list: `https://paper-snitch.online/`
2. Verify each conference shows:
   - Total tokens (sum of all runs)
   - Latest run averages (input, output, total with stddev)

3. Click into conference detail
4. Verify "Workflow Node Statistics" card shows:
   - Table with all nodes
   - Paper counts per node
   - Averages and stddevs for input/output/total

### 4. Validate Latest Run Logic

Create a test scenario:
1. Analyze a paper (Run 1: 5000 tokens)
2. Re-analyze same paper (Run 2: 8000 tokens)
3. Check conference stats show 8000 (not average of 5000 and 8000)

## Troubleshooting

### Statistics Show None

**Symptom:** Conference stats display "Latest Run Averages" but all values are None

**Causes:**
1. No completed workflow runs for conference
2. Token fields are NULL in database

**Solutions:**
```bash
# Check for completed runs
python manage.py shell
>>> from workflow_engine.models import WorkflowRun
>>> WorkflowRun.objects.filter(
...     paper__conference_id=1, 
...     status='completed'
... ).count()

# Check token values
>>> WorkflowRun.objects.filter(
...     paper__conference_id=1,
...     status='completed'
... ).values('input_tokens', 'output_tokens', 'total_tokens')
```

### Node Statistics Empty

**Symptom:** No "Workflow Node Statistics" card appears

**Causes:**
1. No completed runs in conference
2. Nodes don't have token data

**Solutions:**
```python
# Check node data
from workflow_engine.models import WorkflowNode
nodes = WorkflowNode.objects.filter(
    workflow_run__paper__conference_id=1,
    workflow_run__status='completed'
).values('node_id', 'input_tokens', 'output_tokens')
print(list(nodes))
```

### Standard Deviation Shows 0

**Symptom:** Stats show "(±0)" for standard deviation

**Causes:**
1. Only 1 paper in conference (need 2+ for stddev)
2. All papers have exact same token count (unlikely)

**Expected Behavior:** This is normal for single-paper conferences

### Wrong Averages (Too High/Low)

**Symptom:** Averages don't match expected values

**Debug Steps:**
1. Check which runs are being selected:
   ```python
   from django.db.models import Max
   latest = WorkflowRun.objects.filter(
       paper__conference_id=1,
       status='completed'
   ).values('paper_id').annotate(max_created=Max('created_at'))
   print(list(latest))
   ```

2. Verify token values:
   ```python
   from webApp.views import compute_conference_token_statistics
   from webApp.models import Conference
   
   conf = Conference.objects.get(id=1)
   compute_conference_token_statistics([conf])
   
   # Debug: Print intermediate values
   # Add print statements in helper function
   ```

## Related Documentation

- [TOKEN_TRACKING_IMPLEMENTATION.md](TOKEN_TRACKING_IMPLEMENTATION.md) - Backend token tracking system
- [TOKEN_STATISTICS_UI.md](TOKEN_STATISTICS_UI.md) - Original UI implementation
- [workflow_engine/models.py](app/workflow_engine/models.py) - WorkflowNode and WorkflowRun models
- [webApp/views.py](app/webApp/views.py) - View implementations with helper functions

## Summary

✅ **Completed:**
- Latest run per paper (not all runs) for accurate averages
- Split statistics: input, output, total tokens
- Standard deviations for all token types
- Per-node statistics showing token usage by workflow step
- Efficient queries (2-4 queries per page)
- Clean, readable template displays

🎯 **Ready to Use:**
- View conference statistics on homepage
- View per-node breakdown in conference detail
- Use for budget planning, optimization, anomaly detection
- Standard deviations help identify variance/consistency
