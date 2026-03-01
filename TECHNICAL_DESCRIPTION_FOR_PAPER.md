# Technical Infrastructure for Automated Paper Reproducibility Assessment

## 1. System Architecture & Technology Stack

### 1.1 Core Framework
The system is implemented as a distributed web application built on **Django 5.2.7** (Python web framework) with asynchronous task processing via **Celery**. The architecture follows a microservices pattern with containerized deployment using **Docker Compose**.

**Technology Stack:**
- **Backend Framework**: Django 5.2.7 with async support (ASGI)
- **Workflow Orchestration**: LangGraph 1.0.6 (graph-based workflow engine)
- **Task Queue**: Celery 5.x with Redis as message broker
- **Database**: MySQL 8.0 with InnoDB engine (ACID compliance, row-level locking)
- **Vector Operations**: NumPy 2.3.4, SciPy 1.16.3
- **LLM Integration**: OpenAI Python SDK 2.7.2 (gpt-5 models via litellm 1.79.3)
- **Embeddings**: OpenAI text-embedding-3-small (1536 dimensions)
- **Document Processing**: PyPDF 6.2.0, GROBID 0.8.0 (TEI-XML extraction)
- **Web Scraping**: Crawl4AI 0.7.6, Beautiful Soup 4.14.2
- **Code Ingestion**: GitIngest 0.3.1

### 1.2 Deployment Architecture
```
┌─────────────────────────────────────────────────────────┐
│                     NGINX (Reverse Proxy)               │
│              Port 80/443 (SSL via Let's Encrypt)        │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴───────────────┐
        │                            │
   ┌────▼──────┐              ┌──────▼─────┐
   │  Django   │              │   Static   │
   │   Web     │◄─────────────┤   Files    │
   │  (ASGI)   │              └────────────┘
   └─────┬─────┘
         │
    ┌────┴─────────────┬──────────────┐
    │                  │              │
┌───▼────┐      ┌──────▼──────┐  ┌───▼────────┐
│ Celery │      │   MySQL     │  │   Redis    │
│Workers │◄────►│  Database   │  │  (Broker)  │
│ (3-5)  │      │   (InnoDB)  │  └────────────┘
└───┬────┘      └─────────────┘
    │
    └──► GROBID Server (PDF → TEI-XML)
    └──► LLM APIs (OpenAI/LiteLLM)
```

**Resource Allocation:**
- Django web server: 4GB RAM, 2 CPU cores
- Celery workers: 3-5 workers, 2GB RAM each
- MySQL: 8GB RAM, InnoDB buffer pool 6GB
- Redis: 2GB RAM (message persistence disabled)

---

## 2. Database Schema

### 2.1 Core Entities

**Paper Entity:**
```python
Paper {
    id: UUID (primary key)
    title: VARCHAR(500)
    doi: VARCHAR(255) UNIQUE
    abstract: TEXT
    text: TEXT  # Full extracted paper text
    sections: JSON  # Structured sections {type: content}
    code_text: TEXT  # Ingested repository code
    file: FileField  # PDF storage path
    conference: FK(Conference)
    metadata: JSON  # Flexible metadata storage
}
```

**Section Embeddings:**
```python
PaperSectionEmbedding {
    id: UUID
    paper: FK(Paper)
    section_type: VARCHAR(50)  # abstract, introduction, methods, etc.
    section_text: TEXT  # Chunked section content (max 2000 chars)
    embedding: JSON  # [float] × 1536 (text-embedding-3-small)
    embedding_model: VARCHAR(50)
    created_at: DateTime
    INDEX: (paper_id, section_type)
}
```

**Code File Embeddings:**
```python
CodeFileEmbedding {
    id: UUID
    paper: FK(Paper)
    code_url: VARCHAR(500)  # Repository URL
    file_path: VARCHAR(500)  # Relative path in repository
    chunk_index: INT  # Chunk number (0 for non-chunked files)
    file_content: TEXT  # Chunk content (max ~20k chars)
    total_chunks: INT  # Total chunks for this file
    content_hash: VARCHAR(64)  # SHA256 of original file
    embedding: JSON  # [float] × 1536 (text-embedding-3-small)
    embedding_model: VARCHAR(50)
    embedding_dimension: INT DEFAULT 1536
    tokens_used: INT  # Tokens consumed for this embedding
    created_at: DateTime
    INDEX: (paper_id, code_url, file_path, chunk_index) UNIQUE
}
```

**Reproducibility Criteria:**
```python
ReproducibilityChecklistCriterion {
    id: AutoIncrement
    criterion_id: VARCHAR(50) UNIQUE  # mathematical_description
    criterion_number: INT  # 1-26 (excluding 12-17 for code)
    criterion_name: VARCHAR(200)  # "Mathematical Description"
    category: VARCHAR(50)  # models, datasets, experiments
    description: TEXT
    criterion_context: TEXT  # Embedding generation context
    embedding: JSON  # [float] × 1536
    embedding_model: VARCHAR(50) DEFAULT 'text-embedding-3-small'
    embedding_dimension: INT DEFAULT 1536
    INDEX: (criterion_id), (category)
}
```

**Dataset Documentation Criteria:**
```python
DatasetDocumentationCriterion {
    id: AutoIncrement
    criterion_id: VARCHAR(50) UNIQUE
    criterion_number: INT  # 1-10
    criterion_name: VARCHAR(200)
    category: VARCHAR(50)  # data_collection, annotation, ethics_availability
    description: TEXT
    criterion_context: TEXT
    embedding: JSON  # [float] × 1536
    embedding_model: VARCHAR(50)
    embedding_dimension: INT
    INDEX: (criterion_id), (category)
}
```

### 2.2 Workflow Engine Schema

**Workflow Definition:**
```python
WorkflowDefinition {
    id: UUID (primary key)
    name: VARCHAR(255)  # "paper_processing_with_reproducibility"
    version: INT  # Workflow version (current: 8)
    dag_structure: JSON  # Complete DAG: {nodes: [], edges: []}
    dag_diagram: ImageField  # Auto-generated visualization
    is_active: BOOL
    UNIQUE: (name, version)
}
```

**Workflow Run:**
```python
WorkflowRun {
    id: UUID
    workflow_definition: FK(WorkflowDefinition) PROTECT
    paper: FK(Paper) CASCADE
    status: ENUM(pending, running, completed, failed, cancelled)
    run_number: INT  # Sequential run counter per paper
    context_data: JSON  # Initial state (paper_id, model, etc.)
    input_tokens_total: INT  # Aggregated from all nodes
    output_tokens_total: INT
    started_at: DateTime NULL
    completed_at: DateTime NULL
    INDEX: (workflow_definition_id, paper_id, run_number)
}
```

**Workflow Node Execution:**
```python
WorkflowNode {
    id: UUID
    workflow_run: FK(WorkflowRun) CASCADE
    node_id: VARCHAR(100)  # paper_type_classification, code_analysis, etc.
    status: ENUM(pending, running, completed, failed, skipped, cancelled)
    started_at: DateTime NULL
    completed_at: DateTime NULL
    duration_seconds: Float NULL
    
    # Token tracking (LLM cost accounting)
    input_tokens: INT DEFAULT 0
    output_tokens: INT DEFAULT 0
    cached_tokens: INT DEFAULT 0
    
    # Metadata
    output_summary: TEXT NULL  # Human-readable result summary
    error_message: TEXT NULL
    
    INDEX: (workflow_run_id, node_id) UNIQUE
    INDEX: (status, workflow_run_id)
}
```

**Node Artifacts:**
```python
NodeArtifact {
    id: UUID
    node: FK(WorkflowNode) CASCADE
    name: VARCHAR(100)  # "result", "criterion_analyses", "embeddings"
    artifact_type: ENUM(inline, file, external)
    inline_data: JSON NULL  # Structured output (Pydantic models)
    file_path: VARCHAR(500) NULL  # Large artifacts (embeddings, code)
    INDEX: (node_id, name) UNIQUE
}
```

---

## 3. Workflow Orchestration with LangGraph

### 3.1 Workflow Version 8 Architecture

The analysis pipeline is implemented as a **directed acyclic graph (DAG)** with 8 nodes using LangGraph's StateGraph. The workflow implements:
- **Sequential execution** with dependency-based ordering
- **Conditional routing** based on paper type
- **Progressive skipping** for inapplicable nodes
- **Parallel execution** capabilities (fan-out/fan-in pattern)

**Node Topology:**
```
                    ┌─────────────────────────────────┐
                    │ A. Paper Type Classification    │
                    │    (dataset/method/both/        │
                    │     theoretical)                │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │ D. Section Embeddings           │
                    │    (text-embedding-3-small)     │
                    └──────────────┬──────────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
                │                  │                  │
    ┌───────────▼──────────┐  ┌───▼────────────┐  ┌─▼─────────────────┐
    │ G. Reproducibility   │  │ H. Dataset     │  │ B. Code           │
    │    Checklist         │  │    Docs Check  │  │    Availability   │
    │    (20 criteria)     │  │    (10 crit.)  │  │    Check          │
    └───────────┬──────────┘  └───┬────────────┘  └─┬─────────────────┘
                │                  │                  │
                │                  │     ┌────────────▼──────────────┐
                │                  │     │ F. Code Embedding          │
                │                  │     │    (repo ingestion)        │
                │                  │     └────────────┬───────────────┘
                │                  │                  │
                │                  │     ┌────────────▼──────────────┐
                │                  │     │ C. Code Repository         │
                │                  │     │    Analysis               │
                │                  │     └────────────┬───────────────┘
                │                  │                  │
                └──────────────────┴──────────────────┴──────────────┐
                                                                       │
                                        ┌──────────────────────────────▼─┐
                                        │ I. Final Aggregation            │
                                        │    (weighted scoring + LLM)     │
                                        └─────────────────────────────────┘
```

### 3.2 State Management

LangGraph workflows operate on a shared **PaperProcessingState** (TypedDict) that accumulates results from each node:

```python
class PaperProcessingState(TypedDict):
    # Identifiers
    paper_id: int
    workflow_run_id: UUID
    
    # LLM configuration
    client: OpenAI
    model: str  # "gpt-5-2024-11-20"
    
    # Control flags
    force_reprocess: bool  # Bypass cache
    
    # Node outputs (accumulated during execution)
    paper_type_result: Optional[PaperTypeClassification]
    section_embeddings_result: Optional[Dict[str, Any]]
    code_availability_result: Optional[CodeAvailabilityCheck]
    reproducibility_checklist_result: Optional[AggregatedReproducibilityAnalysis]
    dataset_documentation_result: Optional[DatasetDocumentationCheck]
    code_reproducibility_result: Optional[CodeReproducibilityAnalysis]
    final_assessment_result: Optional[FinalReproducibilityAssessment]
```

**Key Design Decisions:**
1. **Immutable accumulation**: Each node reads from state, returns updates as dict
2. **Optional typing**: Downstream nodes check for None before processing
3. **Early returns**: Nodes return empty dict `{}` if dependencies not ready
4. **Progressive skipping**: Nodes auto-skip via status updates when inapplicable

### 3.3 Conditional Routing

**After Section Embeddings (Node D):**
```python
def route_after_embeddings(state: PaperProcessingState) -> List[str]:
    """Route to parallel branches based on paper type."""
    paper_type = state.get("paper_type_result").paper_type
    
    if paper_type == "theoretical":
        # Theoretical papers: only reproducibility checklist
        return ["reproducibility_checklist"]
    else:
        # Dataset/method/both: all three branches
        return [
            "dataset_documentation_check",
            "reproducibility_checklist", 
            "code_availability_check"
        ]
```

**Code Analysis Branch (Progressive Skipping):**
```python
# In code_embedding node:
if not code_availability or not code_availability.code_available:
    # Mark self and downstream as skipped
    await async_ops.update_node_status(node, "skipped")
    
    # Pre-emptively mark code_repository_analysis as skipped
    downstream_node = await async_ops.get_workflow_node(
        state["workflow_run_id"], 
        "code_repository_analysis"
    )
    await async_ops.update_node_status(downstream_node, "skipped")
    
    return {}  # Empty state update
```

---

## 4. Multi-Step RAG (Retrieval-Augmented Generation) Process

### 4.1 Paper Section Embedding (Node D)

**Chunking Strategy:**
```python
def chunk_section_text(section_text: str, max_chars: int = 2000) -> List[str]:
    """
    Split long sections into overlapping chunks for embedding.
    Ensures chunks fit within embedding model context (8191 tokens).
    """
    if len(section_text) <= max_chars:
        return [section_text]
    
    chunks = []
    words = section_text.split()
    current_chunk = []
    current_length = 0
    
    for word in words:
        word_length = len(word) + 1  # +1 for space
        if current_length + word_length > max_chars and current_chunk:
            chunks.append(' '.join(current_chunk))
            # 20% overlap between chunks
            overlap_size = int(len(current_chunk) * 0.2)
            current_chunk = current_chunk[-overlap_size:] if overlap_size > 0 else []
            current_length = sum(len(w) + 1 for w in current_chunk)
        
        current_chunk.append(word)
        current_length += word_length
    
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks
```

**Embedding Generation:**
```python
async def embed_paper_sections(paper: Paper, client: OpenAI) -> Dict[str, int]:
    """
    Generate embeddings for all paper sections asynchronously.
    
    Returns:
        Dict mapping section_type -> number of chunks embedded
    """
    embedding_counts = {}
    
    for section_type, section_text in paper.sections.items():
        if not section_text or len(section_text.strip()) < 50:
            continue  # Skip empty/trivial sections
        
        # Chunk section if too long
        chunks = chunk_section_text(section_text, max_chars=2000)
        
        for i, chunk in enumerate(chunks):
            # Generate embedding via OpenAI API
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=chunk,
                encoding_format="float"
            )
            
            embedding_vector = response.data[0].embedding  # [float] × 1536
            
            # Store in database
            await sync_to_async(PaperSectionEmbedding.objects.create)(
                paper=paper,
                section_type=section_type,
                section_text=chunk,
                embedding=embedding_vector,
                embedding_model="text-embedding-3-small"
            )
        
        embedding_counts[section_type] = len(chunks)
    
    return embedding_counts
```

### 4.2 Criterion-Based Retrieval (Nodes G & H)

**Reproducibility Checklist (20 criteria)** and **Dataset Documentation (10 criteria)** use identical multi-step RAG:

**Step 1: Criterion Embedding (Pre-computed)**
```python
# Management command: initialize_criteria_embeddings
for criterion in REPRODUCIBILITY_CRITERIA.values():
    context = criterion.get_embedding_context()  # Name + description
    
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=context
    )
    
    ReproducibilityChecklistCriterion.objects.create(
        criterion_id=criterion.criterion_id,
        criterion_number=criterion.criterion_number,
        criterion_name=criterion.criterion_name,
        category=criterion.category,
        description=criterion.description,
        criterion_context=context,
        embedding=response.data[0].embedding,
        embedding_model="text-embedding-3-small",
        embedding_dimension=1536
    )
```

**Step 2: Per-Criterion Section Retrieval (Runtime)**
```python
async def retrieve_sections_for_criterion(
    paper_id: int,
    criterion_embedding: List[float],
    top_k: int = 3,
    max_chars_per_section: int = 1500
) -> List[Tuple[float, str, str]]:
    """
    Retrieve most relevant paper sections for a criterion using cosine similarity.
    
    Algorithm:
    1. Load all section embeddings for the paper (batch query)
    2. Compute cosine similarity: dot(criterion_emb, section_emb) / (||a|| * ||b||)
    3. Rank sections by similarity score
    4. Return top-k sections with similarity > threshold (0.3)
    
    Returns:
        List of (similarity_score, section_type, section_text)
    """
    # Batch load all section embeddings
    sections = await sync_to_async(
        lambda: list(PaperSectionEmbedding.objects.filter(paper_id=paper_id))
    )()
    
    if not sections:
        return []
    
    # Normalize criterion embedding once
    criterion_norm = np.linalg.norm(criterion_embedding)
    
    # Compute similarities
    results = []
    for section in sections:
        section_emb = np.array(section.embedding)
        section_norm = np.linalg.norm(section_emb)
        
        # Cosine similarity
        similarity = np.dot(criterion_embedding, section_emb) / (
            criterion_norm * section_norm
        )
        
        if similarity > 0.3:  # Relevance threshold
            # Truncate long sections
            text = section.section_text[:max_chars_per_section]
            results.append((similarity, section.section_type, text))
    
    # Sort by similarity (descending) and take top-k
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:top_k]
```

**Step 3: Single-Criterion LLM Analysis**
```python
async def analyze_single_criterion(
    paper_id: int,
    paper_title: str,
    paper_type: str,
    criterion: ReproducibilityChecklistCriterion,
    relevant_sections: List[Tuple[float, str, str]],
    client: OpenAI,
    model: str
) -> SingleCriterionAnalysis:
    """
    Analyze one criterion with LLM using retrieved sections.
    
    Uses structured output (Pydantic schema) for deterministic parsing.
    """
    # Format retrieved sections
    sections_text = "\n\n".join([
        f"=== {section_type.upper()} (similarity: {similarity:.3f}) ===\n{text}"
        for similarity, section_type, text in relevant_sections
    ])
    
    system_prompt = f"""You are evaluating criterion #{criterion.criterion_number} for a {paper_type} paper.

CRITERION: {criterion.criterion_name}
DESCRIPTION: {criterion.description}

Analyze whether this criterion is satisfied based on the provided paper sections.
Consider paper type when assessing importance: {paper_type} papers have different reproducibility requirements.

Output a structured analysis with present/absent, confidence, evidence, and importance."""
    
    user_prompt = f"""Paper: {paper_title}

RELEVANT SECTIONS:
{sections_text}

Evaluate criterion: {criterion.criterion_name}"""
    
    # Structured output via Pydantic (beta.chat.completions.parse)
    response = await client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format=SingleCriterionAnalysis,
        temperature=0.0  # Deterministic
    )
    
    return response.choices[0].message.parsed
```

### 4.3 Programmatic Aggregation

**Reproducibility Checklist Scoring:**
```python
def compute_category_scores(
    criterion_analyses: List[SingleCriterionAnalysis],
    paper_type: str
) -> Dict[str, float]:
    """
    Compute category scores (0-100) from individual criterion analyses.
    
    Algorithm:
    1. Group criteria by category (models, datasets, experiments)
    2. For each category:
       - Count present criteria (weighted by confidence)
       - Count total criteria in category
       - Score = (present_count / total_count) * 100
    3. Apply paper-type weights for overall score
    
    Returns:
        {
            "models_score": 0-100,
            "datasets_score": 0-100,
            "experiments_score": 0-100,
            "overall_score": 0-100,
            "weighted_score": 0-100
        }
    """
    category_groups = {
        "models": [],
        "datasets": [],
        "experiments": []
    }
    
    # Group by category
    for analysis in criterion_analyses:
        category_groups[analysis.category].append(analysis)
    
    # Score each category
    category_scores = {}
    for category, analyses in category_groups.items():
        if not analyses:
            category_scores[category] = 0.0
            continue
        
        # Weighted count of present criteria
        present_sum = sum(
            analysis.confidence if analysis.present else 0.0
            for analysis in analyses
        )
        
        total_count = len(analyses)
        category_scores[category] = (present_sum / total_count) * 100.0
    
    # Unweighted overall (simple average)
    overall_score = np.mean(list(category_scores.values()))
    
    # Paper-type weighted score
    weights = CRITERIA_WEIGHTS.get(paper_type, CRITERIA_WEIGHTS["unknown"])
    weighted_score = (
        category_scores["models"] * weights["models"] +
        category_scores["datasets"] * weights["datasets"] +
        category_scores["experiments"] * weights["experiments"]
    )
    
    return {
        "models_score": round(category_scores["models"], 1),
        "datasets_score": round(category_scores["datasets"], 1),
        "experiments_score": round(category_scores["experiments"], 1),
        "overall_score": round(overall_score, 1),
        "weighted_score": round(weighted_score, 1)
    }
```

**Paper Type Weighting Matrix:**
```python
CRITERIA_WEIGHTS = {
    "dataset": {
        "models": 0.15,      # Low importance
        "datasets": 0.60,    # Critical
        "experiments": 0.25  # Baseline validation
    },
    "method": {
        "models": 0.45,      # Critical
        "datasets": 0.20,    # Existing datasets OK
        "experiments": 0.35  # Experimental validation
    },
    "both": {
        "models": 0.35,      # High importance
        "datasets": 0.35,    # High importance
        "experiments": 0.30
    },
    "theoretical": {
        "models": 0.55,      # Mathematical rigor
        "datasets": 0.05,    # Not applicable
        "experiments": 0.40  # Theoretical validation
    },
    "unknown": {
        "models": 0.35,      # Neutral weights
        "datasets": 0.30,
        "experiments": 0.35
    }
}
```

---

## 5. Code Repository Embedding (Node F)

### 5.1 LLM-Guided File Selection

When code is available, Node F performs intelligent file selection and mandatory embedding:

**Step 1: Initial Repository Ingestion**
```python
# Clone repository and extract README + tree structure
summary, tree, content, clone_path = await ingest_with_steroids(
    source,
    max_file_size=100000,
    include_patterns=["/README*"],  # README only
    cleanup=False,  # Keep clone for later
    get_tree=True,  # Get full file tree with token counts
)
```

**Step 2: LLM-Based File Selection**
```python
# Provide LLM with documentation and repository structure
prompt = f"""Documentation:
{content}

Repository Structure:
{tree}

Select files essential for reproducibility. Generate include_patterns for gitingest.
- Prioritize: README, requirements, main implementation files
- Exclude: comparison models, benchmarks, visualization scripts  
- Use "/" prefix for root-level files only (e.g., "/README.md")
- Token budget: Maximum 100,000 tokens across all files
- Order: documentation first, then code files
"""

# LLM returns structured file patterns
response = client.responses.parse(
    model=model,
    input=[{"role": "user", "content": prompt}],
    text_format=PatternExtraction,
)
# Example: ["/README.md", "/requirements.txt", "src/model.py", "train.py"]
selected_patterns = response.output_parsed.included_patterns
```

**Step 3: Re-Ingestion with Selected Files**
```python
# Clone and extract only selected files
_, _, selected_content, _ = await ingest_with_steroids(
    source,
    max_file_size=100000,
    include_patterns=selected_patterns,
    cleanup=False,
    get_tree=False,
)
```

### 5.2 Mandatory File Chunking and Embedding

**ALL selected files are chunked and embedded** (not optional):

**Parsing Individual Files:**
```python
# Parse ingest_with_steroids output format:
# ================================================================================
# File: path/to/file.py
# ================================================================================
# <content>

files = {}  # {file_path: file_content}
for line in selected_content.split('\n'):
    if line.strip() == '=' * 80:
        # Start/end of file header
    elif in_header and line.startswith('File: '):
        current_file = line[6:].strip()
    elif not in_header:
        # Accumulate file content
```

**Chunking Strategy:**
```python
def chunk_text(text: str, max_chars: int = 20000) -> List[str]:
    """
    Split large files into ~20k character chunks with word boundaries.
    
    - Files ≤ 20k chars: Single chunk
    - Files > 20k chars: Multiple chunks at word boundaries
    - No overlap between chunks (unlike paper section chunking)
    """
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    words = text.split()
    current_chunk = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 > max_chars:
            chunks.append(' '.join(current_chunk))
            current_chunk = [word]
            current_length = len(word) + 1
        else:
            current_chunk.append(word)
            current_length += len(word) + 1
    
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks
```

**Embedding Computation (Mandatory):**
```python
embedded_files = []
total_tokens = 0

for file_path, file_content in files.items():
    # Compute SHA256 hash
    content_hash = hashlib.sha256(file_content.encode()).hexdigest()
    
    # Chunk file
    chunks = chunk_text(file_content, max_chars=20000)
    
    for chunk_index, chunk_content in enumerate(chunks):
        # Compute embedding via OpenAI API
        embedding, tokens_used = await compute_embedding(
            client, chunk_content, model="text-embedding-3-small"
        )
        total_tokens += tokens_used
        
        # Store in database (CodeFileEmbedding model)
        await CodeFileEmbedding.objects.update_or_create(
            paper=paper,
            code_url=code_url,
            file_path=file_path,
            chunk_index=chunk_index,
            embedding_model="text-embedding-3-small",
            defaults={
                'file_content': chunk_content,
                'total_chunks': len(chunks),
                'content_hash': content_hash,
                'embedding': embedding,  # 1536-dim vector
                'embedding_dimension': 1536,
                'tokens_used': tokens_used,
            }
        )
        
        embedded_files.append(CodeFileEmbeddingInfo(
            file_path=file_path,
            file_content=chunk_content,
            chunk_index=chunk_index,
            total_chunks=len(chunks),
            content_hash=content_hash,
            embedding=embedding,
            tokens_used=tokens_used
        ))
```

**Key Design Decisions:**
1. **Mandatory embeddings**: Every selected file is chunked and embedded (no opt-out)
2. **No overlap**: Unlike paper sections, code chunks don't overlap (simpler search)
3. **20k character chunks**: Balances context preservation with API limits (8191 tokens)
4. **Per-chunk metadata**: Each chunk stores its position (chunk_index) and total count
5. **Content integrity**: SHA256 hash detects code changes across runs
6. **Reusable clone**: Repository clone preserved for Node C (Code Analysis)

### 5.3 Result Artifact

**CodeEmbeddingResult Schema:**
```python
class CodeEmbeddingResult(BaseModel):
    code_url: str  # Repository URL
    clone_path: Optional[str]  # Local clone path (for Node C reuse)
    summary: str  # Repository summary from README
    tree_structure: str  # Full repository tree
    selected_patterns: List[str]  # LLM-selected file patterns
    embedded_files: List[CodeFileEmbeddingInfo]  # ALL file chunks
    total_files: int  # Number of distinct files
    total_chunks: int  # Total chunks across all files
    total_tokens: int  # Embedding tokens consumed
    embedding_model: str  # "text-embedding-3-small"
    embedding_dimension: int  # 1536
```

**Usage in Node C:**
Node C (Code Repository Analysis) retrieves embeddings to support evidence-based evaluation:
```python
# Retrieve relevant code snippets via cosine similarity
relevant_chunks = await retrieve_code_for_component(
    paper_id=paper_id,
    query_embedding=component_embedding,
    top_k=3
)
# Use relevant_chunks in LLM prompts for component analysis
```

---

## 6. Code Repository Analysis (Node C)

### 6.1 Repository Access

**Reusing Node F Clone:**
```python
# Node C receives CodeEmbeddingResult from Node F
code_embedding_result = state.get("code_embedding_result")

if code_embedding_result and code_embedding_result.clone_path:
    # Reuse existing clone (no re-cloning)
    clone_path = code_embedding_result.clone_path
    summary = code_embedding_result.summary
    tree = code_embedding_result.tree_structure
else:
    # Fallback: fresh ingest (if Node F was skipped)
    summary, tree, content, clone_path = await ingest_with_steroids(
        code_url,
        max_file_size=100000,
        include_patterns=['*.py', '*.ipynb', '*.yaml', '*.json', 'README*'],
        cleanup=True,
    )
```

### 6.2 Structured Code Analysis

**Research Methodology Detection:**
```python
class ResearchMethodologyAnalysis(BaseModel):
    """Structured output: What type of research is this code for?"""
    methodology_type: Literal[
        "deep_learning",
        "machine_learning", 
        "algorithm",
        "simulation",
        "data_analysis",
        "theoretical"
    ]
    requires_training: bool  # Does method need training phase?
    requires_datasets: bool  # Does method use external datasets?
    requires_splits: bool    # Does method need train/val/test splits?
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
```

**Component-Based Analysis (6 components):**
1. **Research Methodology** (methodology_type, training requirements)
2. **Repository Structure** (has_requirements, requirements_match_imports)
3. **Code Components** (has_training_code, has_evaluation_code, has_documented_commands)
4. **Artifacts** (has_checkpoints, has_dataset_links, dataset_coverage)
5. **Dataset Splits** (splits_specified, splits_provided, random_seeds_documented)
6. **Documentation** (has_readme, has_results_table, has_reproduction_commands)

Each component analyzed via separate LLM call with targeted prompts and structured output.

### 6.3 Code Reproducibility Scoring

**Two-Level Normalization Algorithm:**
```python
def compute_reproducibility_score(
    methodology: ResearchMethodologyAnalysis,
    structure: RepositoryStructureAnalysis,
    components: CodeAvailabilityAnalysis,
    artifacts: ArtifactsAnalysis,
    dataset_splits: DatasetSplitsAnalysis,
    documentation: ReproducibilityDocumentation
) -> Tuple[float, Dict[str, float], List[str]]:
    """
    Programmatic scoring with adaptive weights based on methodology.
    
    Component Max Scores (adaptive):
    - Code Completeness: 2.5-3.0 points (3.0 if requires_training, else 2.5)
    - Dependencies: 1.0 points (always)
    - Artifacts: 0-2.5 points (2.5 if requires_datasets/training, else 2.0)
    - Dataset Splits: 0-2.0 points (2.0 if requires_splits, else 1.5)
    - Documentation: 2.0 points (always)
    
    Returns:
        (overall_score: 0-100, breakdown: {component: 0-100}, recommendations: [str])
    """
    breakdown = {
        "code_completeness": 0.0,
        "dependencies": 0.0,
        "artifacts": 0.0,
        "dataset_splits": 0.0,
        "documentation": 0.0
    }
    
    component_max = {
        "code_completeness": 3.0 if methodology.requires_training else 2.5,
        "dependencies": 1.0,
        "artifacts": 2.5 if methodology.requires_datasets else 2.0,
        "dataset_splits": 2.0 if methodology.requires_splits else 1.5,
        "documentation": 2.0
    }
    
    recommendations = []
    
    # 1. Code Completeness (adaptive scoring)
    max_code = component_max["code_completeness"]
    if methodology.requires_training:
        # ML/DL: needs training + evaluation
        if components.has_training_code and components.has_evaluation_code:
            breakdown["code_completeness"] = 2.5
        elif components.has_evaluation_code or components.has_training_code:
            breakdown["code_completeness"] = 1.5
            recommendations.append("Add training code" if not components.has_training_code 
                                   else "Add evaluation code")
        else:
            breakdown["code_completeness"] = 0.5
            recommendations.append("Provide both training and evaluation code")
        
        # Bonus for documented commands
        if components.has_documented_commands:
            breakdown["code_completeness"] = min(
                breakdown["code_completeness"] + 0.5, 
                max_code
            )
    else:
        # Non-ML: implementation code sufficient
        if components.has_evaluation_code or components.has_training_code:
            breakdown["code_completeness"] = 2.0
        else:
            breakdown["code_completeness"] = 0.5
            recommendations.append(f"Provide implementation for {methodology.methodology_type}")
        
        if components.has_documented_commands:
            breakdown["code_completeness"] = min(
                breakdown["code_completeness"] + 0.5,
                max_code
            )
    
    # 2. Dependencies (1.0 point)
    if structure and structure.has_requirements:
        if structure.requirements_match_imports is True:
            breakdown["dependencies"] = 1.0
        elif structure.requirements_match_imports is False:
            breakdown["dependencies"] = 0.5
            recommendations.append("Fix dependencies file - imports missing")
        else:
            breakdown["dependencies"] = 0.7
    else:
        recommendations.append("Add requirements file with versions")
    
    # 3. Artifacts (adaptive: 0-2.5 or 0-2.0)
    if methodology.requires_datasets or methodology.requires_training:
        if artifacts:
            # Checkpoints: 0-1.0 (only for training)
            if methodology.requires_training:
                if artifacts.has_checkpoints:
                    breakdown["artifacts"] += 1.0
                else:
                    recommendations.append("Release model checkpoints")
            
            # Dataset links: 0-1.5 (weighted by coverage)
            if methodology.requires_datasets:
                if artifacts.has_dataset_links:
                    coverage_scores = {"full": 1.5, "partial": 0.8, "none": 0.3}
                    breakdown["artifacts"] += coverage_scores.get(
                        artifacts.dataset_coverage, 
                        0.3
                    )
                    if artifacts.dataset_coverage != "full":
                        recommendations.append("Provide ALL dataset download links")
                else:
                    recommendations.append("Provide dataset download links")
        else:
            if methodology.requires_training:
                recommendations.append("Release checkpoints and dataset links")
            elif methodology.requires_datasets:
                recommendations.append("Provide dataset download links")
    else:
        # Non-data research: full credit if code complete
        if components and (components.has_evaluation_code or components.has_training_code):
            breakdown["artifacts"] = 2.0
    
    # 4. Dataset Splits (adaptive: 0-2.0 or 0-1.5)
    if methodology.requires_splits:
        if dataset_splits:
            score = 0.0
            if dataset_splits.splits_specified:
                score += 0.7
            else:
                recommendations.append("Specify train/val/test splits used")
            
            if dataset_splits.splits_provided:
                score += 0.7
            else:
                recommendations.append("Provide split files or logic")
            
            if dataset_splits.random_seeds_documented:
                score += 0.6
            else:
                recommendations.append("Document random seeds")
            
            breakdown["dataset_splits"] = score
        else:
            recommendations.append("Document splits and random seeds")
    else:
        # Non-split research: reward documented seeds
        if dataset_splits and dataset_splits.random_seeds_documented:
            breakdown["dataset_splits"] = 1.5
        else:
            breakdown["dataset_splits"] = 0.5
            if methodology.methodology_type in ["simulation", "algorithm"]:
                recommendations.append("Document random seeds and parameters")
    
    # 5. Documentation (2.0 points - always critical)
    if documentation:
        if documentation.has_readme:
            breakdown["documentation"] += 0.5
        else:
            recommendations.append("Create comprehensive README")
        
        if documentation.has_results_table:
            breakdown["documentation"] += 0.75
        else:
            recommendations.append("Include results table in README")
        
        if documentation.has_reproduction_commands:
            breakdown["documentation"] += 0.75
        else:
            recommendations.append("Document step-by-step reproduction commands")
    else:
        recommendations.append("Add documentation with results and repro steps")
    
    # Calculate max possible score for this methodology
    max_possible = sum(component_max.values())
    
    # Raw total score
    raw_score = sum(breakdown.values())
    
    # Normalize to 0-100 scale
    total_score = (raw_score / max_possible) * 100.0 if max_possible > 0 else 0.0
    total_score = round(total_score, 1)
    
    # Normalize each breakdown component to 0-100 based on its own max
    breakdown_normalized = {}
    for component, raw_value in breakdown.items():
        max_for_component = component_max[component]
        normalized = round((raw_value / max_for_component) * 100.0, 1) if max_for_component > 0 else 0.0
        breakdown_normalized[component] = normalized
    
    return total_score, breakdown_normalized, recommendations
```

**Key Properties:**
- **Adaptive weighting**: Score scale adjusts to research type (ML ≠ theory)
- **Component independence**: Each component normalized to 0-100 independently
- **Methodology-aware**: Deep learning requires checkpoints; simulations require seeds
- **Programmatic recommendations**: Generated from boolean flags, not LLM

---

## 7. Final Aggregation (Node I)

### 7.1 Multi-Component Integration

**Input Sources:**
1. **Reproducibility Checklist** (always present): weighted_score (0-100)
2. **Code Analysis** (conditional): reproducibility_score (0-100)
3. **Dataset Documentation** (conditional): overall_score (0-100)

**Weighted Scoring Strategy:**
```python
def compute_final_score(
    checklist_score: float,
    code_score: Optional[float],
    dataset_score: Optional[float]
) -> Tuple[float, List[float], List[float]]:
    """
    Compute final reproducibility score with adaptive weights.
    
    Weighting Rules:
    - Checklist only: 100% checklist
    - Checklist + Code: 60% checklist, 40% code
    - Checklist + Dataset: 60% checklist, 40% dataset
    - All three: 50% checklist, 30% code, 20% dataset
    
    Returns:
        (final_score, component_scores, component_weights)
    """
    components = [checklist_score]
    weights = []
    
    if code_score is not None and dataset_score is not None:
        # All three components
        components.extend([code_score, dataset_score])
        weights = [0.5, 0.3, 0.2]  # Sums to 1.0
    elif code_score is not None:
        # Checklist + Code
        components.append(code_score)
        weights = [0.6, 0.4]
    elif dataset_score is not None:
        # Checklist + Dataset
        components.append(dataset_score)
        weights = [0.6, 0.4]
    else:
        # Only checklist
        weights = [1.0]
    
    # Compute weighted average
    final_score = sum(s * w for s, w in zip(components, weights))
    return round(final_score, 1), components, weights
```

### 7.2 Evaluation Details Artifact

**Comprehensive Criterion-Level Data:**
```python
def build_evaluation_details(
    checklist: AggregatedReproducibilityAnalysis,
    code_analysis: Optional[CodeReproducibilityAnalysis],
    dataset_docs: Optional[DatasetDocumentationCheck],
    workflow_run_id: UUID
) -> Dict[str, Any]:
    """
    Merge all detailed criterion analyses into structured artifact.
    
    This artifact contains ALL individual criterion evaluations for
    comparison with human evaluation / ground truth.
    
    Structure:
    {
        "paper_checklist": {
            "criteria": [
                {
                    "criterion_id": "mathematical_description",
                    "criterion_number": 1,
                    "criterion_name": "Mathematical Description",
                    "category": "models",
                    "present": True,
                    "confidence": 0.95,
                    "evidence_text": "Section 2.1 provides...",
                    "page_reference": "Methods section",
                    "notes": "Complete formulation with...",
                    "importance": "critical"
                },
                ... (20 total)
            ],
            "category_scores": {
                "models": 85.0,
                "datasets": 40.0,
                "experiments": 60.0
            },
            "overall_score": 61.7,
            "weighted_score": 68.5,
            "paper_type_context": "method"
        },
        "code_analysis": {
            "research_methodology": {...},
            "repository_structure": {...},
            "code_components": {...},
            "artifacts": {...},
            "dataset_splits": {...},
            "documentation": {...},
            "reproducibility_score": 72.5,
            "score_breakdown": {
                "code_completeness": 83.3,
                "dependencies": 100.0,
                "artifacts": 60.0,
                "dataset_splits": 50.0,
                "documentation": 87.5
            }
        },
        "dataset_documentation": {
            "criteria": [
                {
                    "criterion_id": "data_collection_protocol",
                    "criterion_number": 1,
                    "present": True,
                    "confidence": 0.90,
                    ...
                },
                ... (10 total)
            ],
            "category_scores": {...},
            "overall_score": 75.0
        }
    }
    """
    evaluation_details = {}
    
    # 1. Paper Checklist (retrieve individual criterion analyses from artifact)
    checklist_node = get_workflow_node(workflow_run_id, "reproducibility_checklist")
    criterion_analyses_artifact = get_node_artifact(checklist_node, "criterion_analyses")
    
    evaluation_details["paper_checklist"] = {
        "criteria": criterion_analyses_artifact.inline_data,  # List[SingleCriterionAnalysis]
        "category_scores": {
            "models": checklist.models_score,
            "datasets": checklist.datasets_score,
            "experiments": checklist.experiments_score
        },
        "overall_score": checklist.overall_score,
        "weighted_score": checklist.weighted_score,
        "paper_type_context": checklist.paper_type_context
    }
    
    # 2. Code Analysis (if available)
    if code_analysis:
        evaluation_details["code_analysis"] = {
            "research_methodology": code_analysis.research_methodology.model_dump(),
            "repository_structure": code_analysis.repository_structure.model_dump(),
            "code_components": code_analysis.code_components.model_dump(),
            "artifacts": code_analysis.artifacts.model_dump(),
            "dataset_splits": code_analysis.dataset_splits.model_dump(),
            "documentation": code_analysis.documentation.model_dump(),
            "reproducibility_score": code_analysis.reproducibility_score,
            "score_breakdown": code_analysis.score_breakdown
        }
    else:
        evaluation_details["code_analysis"] = None
    
    # 3. Dataset Documentation (if available)
    if dataset_docs:
        dataset_docs_node = get_workflow_node(workflow_run_id, "dataset_documentation_check")
        dataset_criteria_artifact = get_node_artifact(dataset_docs_node, "criterion_analyses")
        
        evaluation_details["dataset_documentation"] = {
            "criteria": dataset_criteria_artifact.inline_data,  # List[SingleDatasetCriterionAnalysis]
            "category_scores": dataset_docs.category_scores,
            "overall_score": dataset_docs.overall_score
        }
    else:
        evaluation_details["dataset_documentation"] = None
    
    return evaluation_details
```

### 7.3 LLM-Generated Qualitative Assessment

**Final node uses LLM ONLY for qualitative text:**
```python
async def generate_qualitative_assessment(
    checklist: AggregatedReproducibilityAnalysis,
    code_analysis: Optional[CodeReproducibilityAnalysis],
    dataset_docs: Optional[DatasetDocumentationCheck],
    paper_type: str,
    client: OpenAI,
    model: str
) -> QualitativeAssessment:
    """
    Generate executive summary, strengths, weaknesses via LLM.
    
    SCORES ARE NOT GENERATED - only descriptive text.
    """
    system_prompt = f"""You are writing qualitative text for a {paper_type} paper reproducibility assessment.

You will receive COMPUTED SCORES from multiple analyses. Your task is to:
1. Write an executive summary (2-4 sentences)
2. Identify 3-5 key strengths
3. Identify 3-5 key weaknesses

DO NOT generate scores - they are already computed programmatically.
Focus on interpreting the analyses and providing actionable insights."""
    
    # Build analysis summary
    analyses_text = f"""**REPRODUCIBILITY CHECKLIST**
- Models: {checklist.models_score:.1f}/100
- Datasets: {checklist.datasets_score:.1f}/100
- Experiments: {checklist.experiments_score:.1f}/100
- Overall: {checklist.overall_score:.1f}/100
- Weighted ({paper_type}): {checklist.weighted_score:.1f}/100
- Summary: {checklist.summary}
- Strengths: {'; '.join(checklist.strengths)}
- Weaknesses: {'; '.join(checklist.weaknesses)}"""
    
    if code_analysis:
        analyses_text += f"""

**CODE ANALYSIS**
- Score: {code_analysis.reproducibility_score:.1f}/100
- Breakdown: {', '.join(f'{k}: {v:.1f}' for k, v in code_analysis.score_breakdown.items())}
- Assessment: {code_analysis.overall_assessment[:300]}
- Recommendations: {'; '.join(code_analysis.recommendations[:3])}"""
    
    if dataset_docs:
        analyses_text += f"""

**DATASET DOCUMENTATION**
- Score: {dataset_docs.overall_score:.1f}/100
- Summary: {dataset_docs.summary}"""
    
    user_prompt = f"""Paper Type: {paper_type}

ANALYSIS RESULTS:
{analyses_text}

Generate qualitative assessment:
1. Executive summary (2-4 sentences synthesizing all analyses)
2. Key strengths (3-5 items)
3. Key weaknesses (3-5 items)"""
    
    response = await client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format=QualitativeAssessment,
        temperature=0.3  # Slight creativity for text generation
    )
    
    return response.choices[0].message.parsed
```

**Final Result Schema:**
```python
class FinalReproducibilityAssessment(BaseModel):
    """Complete reproducibility assessment combining all analyses."""
    
    # Component scores (0-100 each, pre-computed)
    paper_checklist_score: float
    code_analysis_score: Optional[float]
    dataset_documentation_score: Optional[float]
    
    # Overall score (0-100, weighted combination)
    overall_score: float
    
    # LLM-generated qualitative text
    executive_summary: str
    key_strengths: List[str]  # 3-5 items
    key_weaknesses: List[str]  # 3-5 items
    recommendations: List[str]  # 5-10 items (programmatic)
    
    # Detailed evaluation data (for comparison with human evaluation)
    evaluation_details: Dict[str, Any]
```

---

## 8. Token Accounting & Cost Tracking

### 8.1 Per-Node Token Tracking

Every LLM call is metered and stored:
```python
async def update_node_tokens(
    node: WorkflowNode,
    input_tokens: int,
    output_tokens: int,
    was_cached: bool
):
    """Update token usage for a workflow node."""
    node.input_tokens = (node.input_tokens or 0) + input_tokens
    node.output_tokens = (node.output_tokens or 0) + output_tokens
    
    if was_cached:
        node.cached_tokens = (node.cached_tokens or 0) + input_tokens + output_tokens
    
    await sync_to_async(node.save)(update_fields=[
        'input_tokens', 
        'output_tokens', 
        'cached_tokens'
    ])
```

### 8.2 Workflow-Level Aggregation

Total tokens computed from all completed nodes:
```python
def compute_workflow_tokens(workflow_run: WorkflowRun) -> Dict[str, int]:
    """Aggregate token usage across all workflow nodes."""
    nodes = WorkflowNode.objects.filter(
        workflow_run=workflow_run,
        status='completed'
    )
    
    total_input = sum(n.input_tokens or 0 for n in nodes)
    total_output = sum(n.output_tokens or 0 for n in nodes)
    total_cached = sum(n.cached_tokens or 0 for n in nodes)
    
    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cached_tokens": total_cached,
        "total_tokens": total_input + total_output
    }
```

### 8.3 Cost Estimation

**gpt-5 Pricing (as of February 2026):**
- Input: $2.50 per 1M tokens
- Output: $10.00 per 1M tokens
- Cached input: $1.25 per 1M tokens (50% discount)

**Typical Token Usage per Paper:**
- Paper Type Classification (Node A): ~2K tokens (LLM)
- Section Embeddings (Node D): 0 LLM tokens (OpenAI embeddings API only)
- Code Availability Check (Node B): ~5K tokens (LLM)
- Code Embedding (Node F): ~3-5K tokens (LLM for file selection) + ~20-80K tokens (embeddings API)
- Reproducibility Checklist (Node G, 20 criteria): ~40K-60K tokens (LLM)
- Dataset Documentation (Node H, 10 criteria): ~20K-30K tokens (LLM)
- Code Repository Analysis (Node C): ~50K-80K tokens (LLM)
- Final Aggregation (Node I): ~8K-12K tokens (LLM)

**Total per complete workflow: ~150K-260K tokens (~$2.50-$4.50 per paper)**

Note: Embedding API costs are included in input token counts.

---

## 9. Performance Optimizations

### 9.1 Database Optimizations

**Indexes:**
```sql
-- Section embeddings retrieval (most frequent query)
CREATE INDEX idx_paper_section_type ON paper_section_embeddings (paper_id, section_type);

-- Criterion lookups
CREATE INDEX idx_criterion_id ON reproducibility_checklist_criteria (criterion_id);
CREATE INDEX idx_criterion_category ON reproducibility_checklist_criteria (category);

-- Workflow status queries
CREATE INDEX idx_workflow_run_status ON workflow_runs (workflow_definition_id, status);
CREATE INDEX idx_node_status_run ON workflow_nodes (status, workflow_run_id);

-- Composite index for node retrieval
CREATE UNIQUE INDEX idx_workflow_node_unique ON workflow_nodes (workflow_run_id, node_id);
```

**Query Batching:**
```python
# Load all section embeddings in one query
sections = await sync_to_async(
    lambda: list(PaperSectionEmbedding.objects.filter(paper_id=paper_id))
)()

# Preload criteria with embeddings
criteria = await sync_to_async(
    lambda: list(ReproducibilityChecklistCriterion.objects.all())
)()
```

### 9.2 Parallel Execution

**Celery Worker Pool:**
- 3-5 concurrent workers
- Each worker can process different papers simultaneously
- Within-workflow parallelism via LangGraph fan-out (dataset_docs, checklist, code_availability execute concurrently)

**Async I/O:**
- All LLM calls use `await` for non-blocking execution
- Database queries wrapped in `sync_to_async` for Django ORM
- Multiple criterion analyses can overlap (limited by Celery worker count)

### 9.3 Caching Strategy

**Result Caching:**
```python
if not force_reprocess:
    # Check for previous analysis of same paper on same node
    previous = await check_previous_analysis(paper_id, node_id)
    if previous:
        # Return cached result (no LLM calls)
        return previous["result"]
```

**Embedding Caching:**
- Section embeddings computed once, reused across workflow runs
- Criterion embeddings pre-computed, stored in database permanently
- Repository code embeddings cached in NodeArtifact (file storage)

---

## 10. Error Handling & Reliability

### 10.1 Node-Level Error Isolation

Each node executes in try-except with status tracking:
```python
try:
    # Node execution logic
    result = await analyze_criteria(...)
    
    await async_ops.update_node_status(
        node, 
        "completed", 
        completed_at=timezone.now(),
        output_summary="Success: 20/20 criteria analyzed"
    )
    
    return {"reproducibility_checklist_result": result}
    
except Exception as e:
    logger.error(f"Node failed: {e}", exc_info=True)
    
    await async_ops.create_node_log(node, "ERROR", str(e))
    await async_ops.update_node_status(
        node, 
        "failed", 
        completed_at=timezone.now(),
        error_message=str(e)
    )
    
    raise  # Propagate to workflow engine
```

### 10.2 Workflow-Level Fault Tolerance

**Partial Results:**
- Final aggregation gracefully handles missing components
- If code analysis fails, checklist + dataset results still aggregated
- Workflow can complete with subset of nodes

**Retry Logic:**
- Celery automatic retries on transient failures (HTTP timeouts, rate limits)
- Exponential backoff: 60s, 300s, 900s
- Max 3 retries before marking workflow as failed

### 10.3 Validation & Monitoring

**Structured Output Validation:**
- Pydantic schemas enforce type safety
- LLM responses parsed via `response_format` (OpenAI structured outputs)
- Invalid responses logged and re-attempted

**Monitoring:**
- Node status dashboard (pending/running/completed/failed/skipped)
- Token usage tracking per node and per workflow
- Average execution time metrics
- Error rate by node type

---

## 11. Summary of Key Innovations

1. **Adaptive Scoring**: Methodology-aware scoring (DL ≠ simulation ≠ theory)
2. **Multi-Step RAG**: Criterion-level retrieval with cosine similarity ranking
3. **LLM-Guided Code Selection**: LLM analyzes README + tree structure to select reproducibility-critical files within 100k token budget
4. **Mandatory Code Embeddings**: All selected files chunked and embedded for evidence-based code evaluation
5. **Two-Level Normalization**: Component scores (0-component_max) → (0-100)
6. **Programmatic Architecture**: Scores computed deterministically; LLM only for text
7. **Comprehensive Artifact Storage**: Every criterion evaluation preserved for validation
8. **Progressive Skipping**: Nodes auto-deactivate when inapplicable (theoretical papers skip code)
9. **Distributed Execution**: Celery + LangGraph enable parallel paper processing
10. **Token Accountability**: Fine-grained cost tracking per node and per paper
11. **Database-Backed Workflows**: MySQL persistence enables fault tolerance and auditing
12. **Criterion Embedding Database**: Pre-computed permanent embeddings for reproducible retrieval

---

## 12. References

**Core Technologies:**
- Django: https://www.djangoproject.com/
- LangGraph: https://langchain-ai.github.io/langgraph/
- Celery: https://docs.celeryproject.org/
- OpenAI API: https://platform.openai.com/docs/
- GROBID: https://grobid.readthedocs.io/

**Key Algorithms:**
- Cosine Similarity: Jurafsky & Martin, "Speech and Language Processing" (3rd ed.), 2023
- Retrieval-Augmented Generation: Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", NeurIPS 2020
- Directed Acyclic Graphs: Cormen et al., "Introduction to Algorithms" (4th ed.), 2022
