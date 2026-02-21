"""
Debug script for aspect-based retrieval issues.
Run this to diagnose why no sections are being retrieved.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, '/home/administrator/papersnitch/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'webApp.settings')
django.setup()

import numpy as np
from webApp.models import Paper, PaperSectionEmbedding, ReproducibilityAspectEmbedding


def compute_cosine_similarity(embedding1, embedding2):
    """Compute cosine similarity between two embeddings."""
    if not embedding1 or not embedding2:
        return 0.0
    
    if len(embedding1) != len(embedding2):
        print(f"  ⚠️  Dimension mismatch: {len(embedding1)} vs {len(embedding2)}")
        return 0.0
    
    a = np.array(embedding1)
    b = np.array(embedding2)
    
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    
    return float(dot_product / (norm_a * norm_b))


def debug_aspect_retrieval(paper_id, aspect_id="methodology"):
    """
    Debug aspect-based retrieval for a specific paper.
    
    Args:
        paper_id: ID of the paper to check
        aspect_id: Aspect to test (default: methodology)
    """
    print(f"\n{'='*80}")
    print(f"ASPECT RETRIEVAL DEBUG - Paper ID: {paper_id}, Aspect: {aspect_id}")
    print(f"{'='*80}\n")
    
    # 1. Check if paper exists
    print("1️⃣  Checking if paper exists...")
    try:
        paper = Paper.objects.get(id=paper_id)
        print(f"  ✅ Paper found: {paper.title[:60]}...")
    except Paper.DoesNotExist:
        print(f"  ❌ Paper {paper_id} not found in database!")
        return
    
    # 2. Check section embeddings
    print(f"\n2️⃣  Checking section embeddings...")
    section_embeddings = PaperSectionEmbedding.objects.filter(paper_id=paper_id)
    
    if not section_embeddings.exists():
        print(f"  ❌ No section embeddings found for paper {paper_id}!")
        print(f"     → Run the section_embeddings node first")
        return
    
    print(f"  ✅ Found {section_embeddings.count()} section embeddings:")
    for section_emb in section_embeddings:
        print(f"     - {section_emb.section_type}: "
              f"{len(section_emb.section_text)} chars, "
              f"model={section_emb.embedding_model}, "
              f"dim={section_emb.embedding_dimension}")
    
    # 3. Check aspect embedding
    print(f"\n3️⃣  Checking aspect embedding...")
    aspect_embeddings = ReproducibilityAspectEmbedding.objects.filter(aspect_id=aspect_id)
    
    if not aspect_embeddings.exists():
        print(f"  ⚠️  No aspect embedding found for '{aspect_id}'")
        print(f"     → Will be created on first use")
        print(f"     → Using model: text-embedding-3-small")
        aspect_emb = None
    else:
        aspect_emb = aspect_embeddings.first()
        print(f"  ✅ Aspect embedding found:")
        print(f"     - Name: {aspect_emb.aspect_name}")
        print(f"     - Model: {aspect_emb.embedding_model}")
        print(f"     - Dimension: {aspect_emb.embedding_dimension}")
    
    # 4. Check model consistency
    print(f"\n4️⃣  Checking model consistency...")
    section_models = set(section_embeddings.values_list('embedding_model', flat=True))
    print(f"  Section embedding models: {section_models}")
    
    if aspect_emb:
        print(f"  Aspect embedding model: {aspect_emb.embedding_model}")
        
        if aspect_emb.embedding_model not in section_models:
            print(f"  ❌ MODEL MISMATCH!")
            print(f"     → Aspect uses '{aspect_emb.embedding_model}'")
            print(f"     → Sections use {section_models}")
            print(f"     → This will cause the query to return 0 results!")
            return
        else:
            print(f"  ✅ Models match: {aspect_emb.embedding_model}")
    
    # 5. Compute similarity scores
    if aspect_emb:
        print(f"\n5️⃣  Computing similarity scores...")
        min_similarity_threshold = 0.4
        
        matching_sections = section_embeddings.filter(
            embedding_model=aspect_emb.embedding_model
        )
        
        print(f"  Testing against {matching_sections.count()} sections with matching model...")
        print(f"  Minimum similarity threshold: {min_similarity_threshold}")
        print()
        
        above_threshold = 0
        below_threshold = 0
        
        for section_emb in matching_sections:
            similarity = compute_cosine_similarity(
                aspect_emb.embedding,
                section_emb.embedding
            )
            
            status = "✅" if similarity >= min_similarity_threshold else "❌"
            above_threshold += (similarity >= min_similarity_threshold)
            below_threshold += (similarity < min_similarity_threshold)
            
            print(f"  {status} {section_emb.section_type:20s} similarity: {similarity:.4f}")
        
        print()
        print(f"  Summary:")
        print(f"    Above threshold (≥{min_similarity_threshold}): {above_threshold}")
        print(f"    Below threshold (<{min_similarity_threshold}): {below_threshold}")
        
        if above_threshold == 0:
            print()
            print(f"  ⚠️  ALL SECTIONS BELOW THRESHOLD!")
            print(f"     → Possible causes:")
            print(f"        1. The aspect '{aspect_id}' is not well-aligned with paper content")
            print(f"        2. The threshold {min_similarity_threshold} is too high")
            print(f"        3. Embeddings are incorrect or corrupted")
            print()
            print(f"     → Suggestions:")
            print(f"        - Try lowering min_similarity_threshold (e.g., 0.2 or 0.3)")
            print(f"        - Regenerate aspect embeddings")
            print(f"        - Check if embeddings are normalized")
        else:
            print(f"  ✅ {above_threshold} sections will be retrieved!")
    
    print(f"\n{'='*80}\n")


def list_all_aspects():
    """List all aspect embeddings in database."""
    print("\n📊 All Aspect Embeddings:")
    aspects = ReproducibilityAspectEmbedding.objects.all()
    
    if not aspects.exists():
        print("  No aspect embeddings found in database")
        return
    
    for aspect in aspects:
        print(f"  - {aspect.aspect_id:20s} | {aspect.aspect_name:40s} | "
              f"model={aspect.embedding_model} | dim={aspect.embedding_dimension}")


def check_papers_with_embeddings():
    """List papers that have section embeddings."""
    print("\n📄 Papers with Section Embeddings:")
    
    # Get distinct paper IDs that have embeddings
    paper_ids = PaperSectionEmbedding.objects.values_list('paper_id', flat=True).distinct()
    
    if not paper_ids:
        print("  No papers have section embeddings yet")
        return
    
    for paper_id in paper_ids:
        paper = Paper.objects.get(id=paper_id)
        count = PaperSectionEmbedding.objects.filter(paper_id=paper_id).count()
        print(f"  - Paper {paper_id}: {paper.title[:50]}... ({count} sections)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Debug aspect-based retrieval')
    parser.add_argument('--paper-id', type=int, help='Paper ID to debug')
    parser.add_argument('--aspect', type=str, default='methodology', 
                       help='Aspect ID to test (default: methodology)')
    parser.add_argument('--list-aspects', action='store_true', 
                       help='List all aspect embeddings')
    parser.add_argument('--list-papers', action='store_true',
                       help='List papers with embeddings')
    
    args = parser.parse_args()
    
    if args.list_aspects:
        list_all_aspects()
    elif args.list_papers:
        check_papers_with_embeddings()
    elif args.paper_id:
        debug_aspect_retrieval(args.paper_id, args.aspect)
    else:
        print("Usage:")
        print("  python debug_aspect_retrieval.py --paper-id 123 --aspect methodology")
        print("  python debug_aspect_retrieval.py --list-aspects")
        print("  python debug_aspect_retrieval.py --list-papers")
        print("\nAvailable aspects: methodology, structure, components, artifacts,")
        print("                   dataset_splits, documentation, overall")
