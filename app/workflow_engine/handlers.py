"""
Example workflow node handlers for the PDF analysis pipeline.

These are placeholder implementations showing the structure.
Replace with your actual implementation logic.
"""
import logging
from typing import Dict, Any
from workflow_engine.models import NodeArtifact

logger = logging.getLogger(__name__)


def ingest_pdf_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingest and store PDF file.
    
    Args:
        context: Execution context with paper reference
        
    Returns:
        Output data with PDF file reference
    """
    paper = context['paper']
    node = context['node']
    
    logger.info(f"Ingesting PDF for paper {paper.id}")
    
    # Check if paper already has a PDF file
    if paper.file:
        pdf_path = paper.file.path if hasattr(paper.file, 'path') else str(paper.file)
        
        # Create artifact reference
        NodeArtifact.objects.create(
            node=node,
            artifact_type='file',
            name='pdf_file',
            file_path=pdf_path,
            mime_type='application/pdf'
        )
        
        return {
            'pdf_path': pdf_path,
            'status': 'ingested',
            'source': 'existing'
        }
    
    # If no file, might need to download from URL
    if paper.pdf_url:
        # Placeholder: In production, download and save
        logger.info(f"Would download PDF from {paper.pdf_url}")
        
        return {
            'pdf_url': paper.pdf_url,
            'status': 'ingested',
            'source': 'downloaded'
        }
    
    raise ValueError("No PDF file or URL available for paper")


def extract_text_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract text from PDF (with OCR if needed).
    
    Args:
        context: Execution context
        
    Returns:
        Extracted text data
    """
    paper = context['paper']
    node = context['node']
    upstream = context.get('upstream_outputs', {})
    
    logger.info(f"Extracting text from PDF for paper {paper.id}")
    
    # Check if paper already has text
    if paper.text:
        text = paper.text
        source = 'existing'
    else:
        # Placeholder: In production, use PDF extraction library
        # e.g., PyPDF2, pdfminer, or OCR with tesseract
        text = "Extracted text would go here..."
        source = 'extracted'
        
        # Save to paper
        paper.text = text
        paper.save(update_fields=['text'])
    
    # Create artifact
    NodeArtifact.objects.create(
        node=node,
        artifact_type='inline',
        name='extracted_text',
        inline_data={'text': text[:1000]},  # Store preview
        metadata={
            'full_length': len(text),
            'source': source
        }
    )
    
    return {
        'text': text,
        'text_length': len(text),
        'source': source,
        'has_text': bool(text)
    }


def extract_evidence_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract evidence and links from paper text.
    
    Args:
        context: Execution context
        
    Returns:
        Extracted evidence and links
    """
    paper = context['paper']
    node = context['node']
    upstream = context.get('upstream_outputs', {})
    
    # Get text from upstream
    text = upstream.get('extract_text', {}).get('text') or paper.text or ''
    
    logger.info(f"Extracting evidence and links for paper {paper.id}")
    
    # Placeholder: In production, use regex, NLP, or LLM to extract
    # - GitHub/GitLab URLs
    # - Dataset links
    # - Artifact URLs
    # - Key claims and evidence
    
    import re
    
    # Simple regex for URLs
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    
    # Filter for code repositories
    repo_urls = [url for url in urls if any(domain in url.lower() 
                 for domain in ['github.com', 'gitlab.com', 'bitbucket.org'])]
    
    result = {
        'all_urls': urls[:50],  # Limit to first 50
        'repo_urls': repo_urls,
        'dataset_urls': [],  # Placeholder
        'evidence_snippets': [],  # Placeholder
    }
    
    # Create artifact
    NodeArtifact.objects.create(
        node=node,
        artifact_type='inline',
        name='extracted_evidence',
        inline_data=result
    )
    
    return result


def validate_links_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate extracted links and find repository URLs.
    
    Args:
        context: Execution context
        
    Returns:
        Validated links and repository information
    """
    paper = context['paper']
    node = context['node']
    upstream = context.get('upstream_outputs', {})
    
    evidence = upstream.get('extract_evidence', {})
    repo_urls = evidence.get('repo_urls', [])
    
    logger.info(f"Validating links for paper {paper.id}")
    
    # Placeholder: In production, check if URLs are accessible
    # Use requests library with timeout
    
    validated_repos = []
    
    for url in repo_urls[:5]:  # Limit to first 5
        validated_repos.append({
            'url': url,
            'accessible': True,  # Placeholder
            'type': 'github' if 'github.com' in url else 'other'
        })
    
    return {
        'validated_repos': validated_repos,
        'total_repos': len(validated_repos)
    }


def fetch_repo_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clone/fetch repository and index files.
    
    Args:
        context: Execution context
        
    Returns:
        Repository metadata and file inventory
    """
    paper = context['paper']
    node = context['node']
    upstream = context.get('upstream_outputs', {})
    
    repos = upstream.get('validate_links', {}).get('validated_repos', [])
    
    if not repos:
        return {
            'status': 'no_repos',
            'repos_fetched': 0
        }
    
    logger.info(f"Fetching repositories for paper {paper.id}")
    
    # Placeholder: In production, use gitpython or subprocess to clone
    # Then index files, compute embeddings if needed
    
    # For now, just return metadata
    repo_data = []
    
    for repo in repos[:1]:  # Just first repo for now
        repo_data.append({
            'url': repo['url'],
            'cloned': False,  # Placeholder
            'file_count': 0,
            'languages': [],
            'has_readme': False,
            'has_requirements': False
        })
    
    return {
        'repos_fetched': len(repo_data),
        'repos': repo_data
    }


def aggregate_findings_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aggregate findings from PDF and repository checks.
    
    Args:
        context: Execution context
        
    Returns:
        Aggregated findings
    """
    paper = context['paper']
    node = context['node']
    upstream = context.get('upstream_outputs', {})
    
    logger.info(f"Aggregating findings for paper {paper.id}")
    
    # Collect results from upstream nodes
    pdf_checks = upstream.get('ai_checks_pdf', {})
    repo_checks = upstream.get('ai_checks_repo', {})
    
    # Aggregate scores
    aggregated = {
        'pdf_analysis': pdf_checks.get('findings', {}),
        'repo_analysis': repo_checks.get('findings', {}),
        'combined_issues': (
            pdf_checks.get('issues_found', []) +
            repo_checks.get('issues_found', [])
        ),
        'evidence_count': len(pdf_checks.get('evidence_extracted', []))
    }
    
    return aggregated


def compute_score_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute final reproducibility score.
    
    Args:
        context: Execution context
        
    Returns:
        Final score and breakdown
    """
    paper = context['paper']
    node = context['node']
    upstream = context.get('upstream_outputs', {})
    
    logger.info(f"Computing score for paper {paper.id}")
    
    findings = upstream.get('aggregate_findings', {})
    pdf_analysis = findings.get('pdf_analysis', {})
    repo_analysis = findings.get('repo_analysis', {})
    
    # Simple weighted scoring
    weights = {
        'methodology': 0.25,
        'reproducibility': 0.30,
        'code_quality': 0.25,
        'documentation': 0.20
    }
    
    scores = {
        'methodology': pdf_analysis.get('methodology_score', 0.5),
        'reproducibility': pdf_analysis.get('reproducibility_score', 0.5),
        'code_quality': repo_analysis.get('code_quality_score', 0.5),
        'documentation': repo_analysis.get('documentation_score', 0.5)
    }
    
    final_score = sum(scores[k] * weights[k] for k in weights.keys())
    
    return {
        'final_score': round(final_score, 3),
        'component_scores': scores,
        'weights': weights,
        'score_out_of_100': round(final_score * 100, 1)
    }


def generate_report_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate final report artifact.
    
    Args:
        context: Execution context
        
    Returns:
        Report metadata
    """
    paper = context['paper']
    node = context['node']
    upstream = context.get('upstream_outputs', {})
    
    logger.info(f"Generating report for paper {paper.id}")
    
    score_data = upstream.get('compute_score', {})
    findings = upstream.get('aggregate_findings', {})
    
    # Create report structure
    report = {
        'paper_id': paper.id,
        'paper_title': paper.title,
        'analysis_date': node.created_at.isoformat(),
        'final_score': score_data.get('final_score'),
        'score_breakdown': score_data.get('component_scores'),
        'findings': findings,
        'recommendations': [
            'Add comprehensive test cases',
            'Improve documentation',
            'Provide dataset access instructions'
        ]
    }
    
    # Save as artifact
    NodeArtifact.objects.create(
        node=node,
        artifact_type='inline',
        name='final_report',
        inline_data=report,
        metadata={
            'format': 'json',
            'version': '1.0'
        }
    )
    
    return {
        'report_generated': True,
        'final_score': score_data.get('final_score')
    }
