# Conference Scraping System

Automated scraping of conference papers with Celery-based async processing and Django model integration.

## Features

- ✅ **Async Processing**: Non-blocking Celery tasks for large conferences
- ✅ **Smart Caching**: Schema caching to avoid LLM regeneration
- ✅ **Progress Tracking**: Real-time progress updates during scraping
- ✅ **Database Integration**: Automatic Paper, Conference, and Dataset creation/updates
- ✅ **Concurrent Crawling**: Configurable parallel requests (default: 5)
- ✅ **Error Handling**: Robust error recovery and reporting

## Quick Start

### 1. Basic Usage (Async via Celery)

```bash
# Scrape entire conference
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025"

# With year
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025" --year 2025

# Test with limited papers
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025" --limit 10
```

### 2. Background Mode

Start task and return immediately:

```bash
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025" --no-wait
# Returns: Task ID: abc-123-def

# Check status later
python manage.py check_task_status abc-123-def
```

### 3. Synchronous Mode (Testing Only)

For small conferences or testing:

```bash
python manage.py scrape_conference "Small Conference" "https://example.com" --sync
```

## Configuration

### Environment Variables

```bash
# .env.llm or .env.local
MAX_CONCURRENT_CRAWLS=5  # Number of parallel crawl requests
GEMINI_API_KEY=your_key   # For schema generation (first run only)
```

### Schema Caching

Schemas are automatically cached in `media/scraper_schemas/`:
- Generated once per conference using Gemini LLM
- Reused on subsequent runs
- Delete cached schema to regenerate

## Architecture

```
scrape_conference command
    ↓
scrape_conference_task (Celery)
    ↓
ConferenceScraper service
    ↓
[crawl4ai] → [clean data] → [save to DB]
```

### Files Created

```
app/webApp/
├── services/
│   └── conference_scraper.py      # Core scraping logic
├── tasks.py                        # Celery task (scrape_conference_task)
└── management/commands/
    ├── scrape_conference.py        # CLI command
    └── check_task_status.py        # Status checker
```

## Database Updates

The scraper automatically:

1. **Creates/Updates Conference**:
   - Uses `name` + `year` for lookup
   - Updates `url` if changed

2. **Creates/Updates Papers**:
   - Uses `paper_url` as unique identifier
   - Updates all fields on re-scrape
   - Links to conference

3. **Creates/Links Datasets**:
   - Extracts from paper metadata
   - Creates Dataset records
   - Links via ManyToMany

## Progress Tracking

During execution, you'll see:

```
🚀 Starting conference scrape: MICCAI 2025
   URL: https://papers.miccai.org/miccai-2025

📤 Dispatching to Celery worker...
✅ Task started: 12345-abcd-67890

⏳ Waiting for completion (Ctrl+C to stop monitoring)...

   [0/150 - 0.0%] Initializing scraper...
   [1/150 - 0.7%] Processing: Paper Title 1
   [2/150 - 1.3%] Processing: Paper Title 2
   ...
   [150/150 - 100.0%] Processing: Paper Title 150

✅ Scraping completed!

📊 Results for MICCAI 2025:
   Papers found:     150
   Papers processed: 148
   Created:          120
   Updated:          28
   Failed:           2
```

## Error Handling

- **Failed papers**: Logged and reported in results
- **Network errors**: Automatic retries at crawl4ai level
- **Task failures**: Celery state preserved, error details available

## Integration with Workflows

To trigger paper processing after scraping:

```python
# In a custom workflow or task
from webApp.tasks import scrape_conference_task
from workflow_engine.management.commands.start_workflow_batch import Command as BatchCommand

# Scrape
result = scrape_conference_task.delay("MICCAI 2025", "https://...")
conference_data = result.get()

# Then process with batch workflow
batch_cmd = BatchCommand()
batch_cmd.handle(
    workflow_name="pdf_analysis",
    conference=conference_data['conference']
)
```

## Troubleshooting

### Schema Generation Fails

```
ERROR: Schema generation failed
```

**Solution**: Check `GEMINI_API_KEY` in `.env.llm`

### Celery Worker Not Processing

```bash
# Check worker status
celery -A web inspect active

# Restart workers
sudo docker restart celery-worker-dev-bolelli celery-beat-dev-bolelli
```

### Papers Not Saving

Check logs for database errors:
```bash
sudo docker logs django-web-dev-bolelli | grep ERROR
```

## Performance

- **Small conference** (50 papers): ~2-3 minutes
- **Medium conference** (200 papers): ~8-12 minutes  
- **Large conference** (500+ papers): ~20-30 minutes

Adjust `MAX_CONCURRENT_CRAWLS` based on:
- Target website rate limits
- Server resources
- Network bandwidth

## API Keys Required

- **Gemini API**: For schema generation (first run only)
- Optional: Set up schema manually to avoid LLM dependency

## Next Steps

1. **Run first scrape** with --limit 5 to test
2. **Verify data** in Django admin
3. **Trigger workflows** on scraped papers
4. **Schedule periodic updates** via Celery Beat (coming soon)
