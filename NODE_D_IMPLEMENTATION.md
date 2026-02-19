# Paper Section Embeddings - Node D Implementation

## Overview

This document describes the implementation of **Node D (Section Embeddings)** in the paper processing workflow.

## Workflow Architecture

### New Workflow Structure (Version 3)

```
Start (S)
    ↓
Node A: Paper Type Classification
    ↓
Node D: Section Embeddings ← NEW
    ↓
Node B: Code Availability Check
    ↓
Node C: Code Repository Analysis (conditional)
    ↓
End
```

### Sequential Flow
1. **Node A** (`paper_type_classification`): Classifies paper type (method/dataset/both/theoretical/unknown)
2. **Node D** (`section_embeddings`): NEW - Computes and stores vector embeddings for paper sections
3. **Node B** (`code_availability_check`): Checks for code repository availability
4. **Node C** (`code_repository_analysis`): Analyzes code quality and reproducibility (conditional)

## Database Schema

### New Model: `PaperSectionEmbedding`

Stores vector embeddings for individual paper sections to enable semantic similarity search.

```python
class PaperSectionEmbedding(models.Model):
    paper = ForeignKey(Paper)  # Parent paper
    section_type = CharField(max_length=50)  # 'abstract', 'introduction', 'methods', etc.
    section_text = TextField()  # Raw section text
    embedding = JSONField()  # Vector embedding as JSON array
    embedding_model = CharField(default='text-embedding-3-small')
    embedding_dimension = IntegerField(default=1536)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

**Table**: `paper_section_embeddings`

**Indexes**:
- `idx_paper_section` on (`paper_id`, `section_type`)
- `idx_section_type` on (`section_type`)

**Constraints**:
- Unique constraint on (`paper`, `section_type`, `embedding_model`)

### Why Separate Table?

**Advantages**:
1. **Multiple sections per paper**: Papers have multiple sections (abstract, intro, methods, results, discussion, conclusion)
2. **Clean separation**: Embeddings are computed artifacts, not core metadata
3. **Efficient queries**: Easy to query by section type or perform vector similarity searches
4. **Versioning**: Can store multiple embedding versions (different models)
5. **No table bloat**: Paper table remains clean and focused

## Node D Implementation

### File: `app/webApp/services/nodes/section_embeddings.py`

**Functionality**:
1. **Section Retrieval**: Reads pre-extracted sections from `Paper.sections` JSONField (fallback to regex extraction if not available)
2. **Embedding Computation**: Calls OpenAI `text-embedding-3-small` API for each section
3. **Database Storage**: Stores embeddings in `PaperSectionEmbedding` table
4. **Caching**: Skips recomputation if embeddings exist (unless forced)

**Section Source Priority**:
1. **Primary**: `Paper.sections` JSONField (pre-extracted during scraping)
2. **Fallback**: Regex extraction from `Paper.text` (if sections field is empty)

**Supported Section Types** (normalized to lowercase with underscores):
- abstract
- introduction
- related_work (or background)
- methods (or methodology/approach)
- experiments (or evaluation)
- results
- discussion
- conclusion

### Key Functions

```python
def extract_paper_sections(paper_text: str) -> List[Tuple[str, str]]
    # FALLBACK: Extracts sections using regex patterns (only if Paper.sections is empty)
    
async def compute_embedding(client, text: str, model: str) -> List[float]
    # Calls OpenAI API to compute embedding
    
async def section_embeddings_node(state: PaperProcessingState) -> Dict[str, Any]
    # Main node function - retrieves sections from database and computes embeddings
```

**Why Use Database Sections?**
- **Already extracted**: Sections are parsed during initial paper scraping/ingestion
- **More accurate**: Scraper uses proper PDF/XML parsing instead of regex
- **Consistent format**: Standardized section names and structure
- **Performance**: No need to re-parse large text documents

### Output Structure

```python
{
    "sections_processed": 5,
    "section_types": ["abstract", "introduction", "methods", "results", "conclusion"],
    "embedding_model": "text-embedding-3-small",
    "embedding_dimension": 1536,
    "estimated_tokens": 4500
}
```

## Usage of Embeddings (Future)

### Planned Use in Node B (Code Availability Check)

The embeddings will be used to compute semantic similarity between:
1. Paper sections (especially methods/results)
2. Code repository documentation (README, comments)

This will help verify if:
- The repository actually corresponds to the paper
- The implementation matches the described methodology

### Cosine Similarity

The model includes a helper method:

```python
paper_embedding.compute_cosine_similarity(other_embedding: list) -> float
    # Returns similarity score (0 to 1)
```

## Migration Steps

### 1. Create Migration

```bash
docker exec django-web-dev-bolelli python manage.py makemigrations webApp
```

Rename the generated file from `0XXX_paper_section_embeddings.py` to the correct number.

### 2. Apply Migration

```bash
docker exec django-web-dev-bolelli python manage.py migrate
```

### 3. Restart Services

```bash
docker restart django-web-dev-bolelli celery-worker-dev-bolelli
```

## Testing

### 1. Test Single Paper

```python
from webApp.tasks import process_paper_workflow_task

# Enqueue workflow for paper ID 28
result = process_paper_workflow_task.delay(paper_id=28, force_reprocess=True)
print(f"Task ID: {result.id}")
```

### 2. Check Embeddings

```python
from webApp.models import PaperSectionEmbedding

# Check embeddings for a paper
embeddings = PaperSectionEmbedding.objects.filter(paper_id=28)
for emb in embeddings:
    print(f"{emb.section_type}: {emb.embedding_dimension} dimensions")
```

### 3. Test Similarity

```python
# Get two section embeddings
abstract = PaperSectionEmbedding.objects.get(paper_id=28, section_type='abstract')
intro = PaperSectionEmbedding.objects.get(paper_id=28, section_type='introduction')

# Compute similarity
similarity = abstract.compute_cosine_similarity(intro.embedding)
print(f"Similarity: {similarity:.4f}")
```

## Files Modified

1. **Models**
   - `app/webApp/models.py` - Added `PaperSectionEmbedding` model
   - `app/webApp/migrations/0XXX_paper_section_embeddings.py` - Database migration

2. **Workflow**
   - `app/webApp/services/nodes/section_embeddings.py` - NEW Node D implementation
   - `app/webApp/services/graphs_state.py` - Added `section_embeddings_result` to state
   - `app/webApp/services/graphs/paper_processing_workflow.py` - Updated workflow graph

3. **Admin**
   - `app/webApp/admin.py` - Registered `PaperSectionEmbedding` for Django admin

## Token Usage

**Per paper** (estimated):
- Average 4-6 sections per paper
- ~1000-2000 chars per section
- ~250-500 tokens per section
- **Total: ~1500-3000 tokens per paper**

At OpenAI's embedding pricing (text-embedding-3-small):
- $0.020 per 1M tokens
- ~$0.00003-$0.00006 per paper

## Future Enhancements

1. **Paragraph-level embeddings**: Break sections into paragraphs for finer granularity
2. **Vector database**: Use specialized vector DB (ChromaDB, Pinecone) for large-scale similarity search
3. **Embedding updates**: Periodic recomputation with newer models
4. **Cross-paper similarity**: Find related papers based on section similarity
5. **Semantic search**: Search papers by semantic content rather than keywords

## Next Steps

1. ✅ Create database migration
2. ✅ Implement Node D
3. ✅ Update workflow graph
4. ✅ Register in Django admin
5. ⏳ Run migration
6. ⏳ Test with sample papers
7. ⏳ Integrate similarity scoring in Node B

## Questions?

- **Q**: Why not use MariaDB's native vector type?
  - **A**: JSONField is sufficient for now and more portable. Can migrate to native vectors later if needed.

- **Q**: Can we make Node A and D concurrent?
  - **A**: Yes, technically possible using LangGraph's parallel routing, but sequential is simpler and avoids race conditions.

- **Q**: What if paper has no sections?
  - **A**: Node D logs warning and skips gracefully. Workflow continues.

- **Q**: Memory usage with large papers?
  - **A**: Each section limited to 8000 chars. Embeddings are ~6KB each (1536 floats).
