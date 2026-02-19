"""
Conference scraping service for extracting papers from conference websites.
Integrates with Django models for automatic database updates.
"""
import os
import json
import re
import logging
import httpx
from pathlib import Path
from copy import deepcopy
from typing import Dict, List, Optional
from urllib.parse import urljoin
from django.core.files.base import ContentFile
from django.db import transaction

from crawl4ai import (
    AsyncWebCrawler,
    CrawlResult,
    CrawlerRunConfig,
    JsonCssExtractionStrategy,
    LLMConfig,
)
import asyncio
from asgiref.sync import sync_to_async

from webApp.models import Conference, Paper, Dataset
from webApp.functions import get_pdf_content

logger = logging.getLogger(__name__)

MAX_CONCURRENT_CRAWLS = int(os.getenv("MAX_CONCURRENT_CRAWLS", "3"))
MAX_CONCURRENT_GROBID = int(os.getenv("MAX_CONCURRENT_GROBID", "2"))
BATCH_SIZE = int(os.getenv("SCRAPER_BATCH_SIZE", "50"))
BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = BASE_DIR / "fixtures"

# Global semaphore for Grobid processing (shared across all instances)
_grobid_semaphore = None

def get_grobid_semaphore():
    global _grobid_semaphore
    if _grobid_semaphore is None:
        _grobid_semaphore = asyncio.Semaphore(MAX_CONCURRENT_GROBID)
    return _grobid_semaphore


class ConferenceScraper:
    """Service for scraping conference papers and saving to database."""

    def __init__(self, conference_name: str, conference_url: str, year: Optional[int] = None, conference_id: Optional[int] = None):
        self.conference_name = conference_name
        self.conference_url = conference_url
        self.year = year
        self.conference_id = conference_id
        self.base_url = self._extract_base_url(conference_url)
        self.schema_cache_dir = FIXTURES_DIR / "scraper_schemas"
        self.schema_cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _extract_base_url(url: str) -> str:
        """Extract base URL from full URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def get_schema(self, html_sample: Optional[str] = None) -> dict:
        """
        Get or generate extraction schema for the conference website.
        Caches schema to avoid regenerating on every run.
        """
        schema_file = self.schema_cache_dir / f"{self.conference_name.lower().replace(' ', '_')}_schema.json"

        try:
            with open(schema_file, "r") as f:
                schema = json.load(f)
                logger.info(f"Loaded schema from {schema_file}")
                return schema
        except FileNotFoundError:
            logger.info("Schema not found, generating with LLM...")
            schema = JsonCssExtractionStrategy.generate_schema(
                html=html_sample,
                llm_config=LLMConfig(
                    provider="openai/gpt-4o",
                    api_token=os.getenv("OPENAI_API_KEY"),
                ),
                query=f"From {self.conference_url}, extract paper listings with: title, authors list, and link to paper details/reviews",
            )
            logger.info("Schema generated successfully")

            with open(schema_file, "w") as f:
                json.dump(schema, f, indent=2)

            return schema

    async def crawl_paper_list(self, schema: dict) -> List[dict]:
        """Crawl the main conference page to get list of papers."""
        extraction_strategy = JsonCssExtractionStrategy(schema)
        config = CrawlerRunConfig(extraction_strategy=extraction_strategy)

        async with AsyncWebCrawler() as crawler:
            logger.info(f"Crawling paper list from {self.conference_url}")
            result: CrawlResult = await crawler.arun(
                url=self.conference_url,
                config=config,
            )

            if result.success:
                data = json.loads(result.extracted_content)
                logger.info(f"Found {len(data)} papers")
                return data
            else:
                raise Exception(f"Crawling failed for {self.conference_url}")

    async def crawl_paper_details(self, url: str, schema: dict) -> dict:
        """Crawl individual paper page for detailed information."""
        extraction_strategy = JsonCssExtractionStrategy(schema)
        config = CrawlerRunConfig(extraction_strategy=extraction_strategy)

        async with AsyncWebCrawler() as crawler:
            result: CrawlResult = await crawler.arun(
                url=url,
                config=config,
            )

            paper_md = result.markdown
            return self._extract_sections(paper_md)

    @staticmethod
    def _extract_sections(markdown_text: str) -> dict:
        """Extract all H1 sections from markdown text."""
        sections = {}
        h1_pattern = r"^# (.+)$"
        matches = list(re.finditer(h1_pattern, markdown_text, re.MULTILINE))

        for i, match in enumerate(matches):
            section_name = match.group(1).strip()
            start_pos = match.end()

            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(markdown_text)

            content = markdown_text[start_pos:end_pos].strip()
            key = section_name.lower().replace(" ", "_")
            sections[key] = content

        return sections

    def _clean_paper_data(self, paper: dict) -> dict:
        """Clean and normalize paper data from scraped content."""
        cleaned = deepcopy(paper)

        # Clean authors
        if cleaned.get("authors"):
            if isinstance(cleaned["authors"], list):
                cleaned["authors"] = ", ".join(
                    [item.get("author", "").replace(",", "") for item in cleaned["authors"]]
                )

        # Extract datasets
        if "link_to_the_dataset(s)" in cleaned:
            dataset_pattern = r"([^:]+):\s*<([^>]+)>"
            matches = re.findall(dataset_pattern, cleaned["link_to_the_dataset(s)"])
            cleaned["datasets"] = (
                {name.strip(): url.strip() for name, url in matches} if matches else None
            )

        # Extract code URL
        if "link_to_the_code_repository" in cleaned:
            code_pattern = r"<([^>]+)>"
            match = re.search(code_pattern, cleaned["link_to_the_code_repository"])
            cleaned["code_url"] = match.group(1).strip() if match else None

        # Extract paper materials (handle both MICCAI 2022 and newer formats)
        paper_section = None
        if "links_to_paper_and_supplementary_materials" in cleaned:
            paper_section = cleaned["links_to_paper_and_supplementary_materials"]
        elif "link_to_paper" in cleaned:
            # MICCAI 2022 format
            paper_section = cleaned["link_to_paper"]
        
        if paper_section:
            # DOI - try multiple patterns
            # Pattern 1: SpringerLink (DOI): <url> (newer format)
            doi_pattern = r"SpringerLink \(DOI\):\s*(.+?)(?:\n|$)"
            doi_match = re.search(doi_pattern, paper_section)
            if doi_match:
                doi_value = doi_match.group(1).strip()
                # Remove angular brackets if present
                doi_value = re.sub(r'^<(.+)>$', r'\1', doi_value)
                cleaned["doi"] = None if doi_value.lower().startswith("not") else doi_value
            else:
                # Pattern 2: DOI: <url> (MICCAI 2022 format)
                doi_pattern_2 = r"DOI:\s*<([^>]+)>"
                doi_match_2 = re.search(doi_pattern_2, paper_section)
                if doi_match_2:
                    doi_value = doi_match_2.group(1).strip()
                    cleaned["doi"] = None if doi_value.lower().startswith("not") else doi_value
                else:
                    cleaned["doi"] = None

            # PDF URL
            pdf_pattern = r"Main Paper \(Open Access Version\):\s*<([^>]+)>"
            pdf_match = re.search(pdf_pattern, paper_section)
            if pdf_match:
                pdf_value = pdf_match.group(1).strip()
                cleaned["pdf_url"] = None if pdf_value.lower().startswith("not") else pdf_value
            else:
                # Fallback to pdf_url if already extracted from schema
                pass
            
            # Supplementary materials PDF
            supp_pattern = r"Supplementary Material:\s*<([^>]+)>"
            supp_match = re.search(supp_pattern, paper_section)
            if supp_match:
                supp_value = supp_match.group(1).strip()
                cleaned["supp_materials_url"] = None if supp_value.lower().startswith("not") else supp_value
            else:
                cleaned["supp_materials_url"] = None

        # Clean meta-review
        if "meta-review" in cleaned:
            back_to_top_pattern = r"\[\*\*back to top\*\*\].*"
            cleaned["meta_review"] = re.sub(
                back_to_top_pattern, "", cleaned["meta-review"], flags=re.DOTALL
            ).strip()

        return cleaned

    @staticmethod
    async def download_pdf(url: str) -> Optional[bytes]:
        """Download PDF file from URL."""
        if not url:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200 and response.headers.get('content-type', '').startswith('application/pdf'):
                    logger.info(f"Downloaded PDF from {url} ({len(response.content)} bytes)")
                    return response.content
                else:
                    logger.warning(f"Failed to download PDF from {url}: status {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Error downloading PDF from {url}: {e}")
            return None

    async def _process_paper(self, paper_data: dict, schema: dict) -> Optional[dict]:
        """Process a single paper: crawl details and clean data."""
        paper = deepcopy(paper_data)

        # Clean initial data
        if paper.get("authors"):
            if isinstance(paper["authors"], list):
                paper["authors"] = ", ".join(
                    [item.get("author_name", "").replace(",", "") for item in paper["authors"]]
                )

        paper_url = paper.get("paper_url")
        if not paper_url:
            logger.warning("Paper missing URL, skipping")
            return None

        if not paper_url.startswith("https://"):
            paper_url = urljoin(self.base_url + "/", paper_url)
            paper["paper_url"] = paper_url

        try:
            # Crawl detailed information
            crawled_sections = await self.crawl_paper_details(paper_url, schema)

            # Merge crawled data with initial data
            paper.update(crawled_sections)

            # Clean and normalize
            cleaned = self._clean_paper_data(paper)

            # Download PDFs
            if cleaned.get("pdf_url"):
                pdf_content = await self.download_pdf(cleaned["pdf_url"])
                if pdf_content:
                    cleaned["pdf_content"] = pdf_content
            
            if cleaned.get("supp_materials_url"):
                supp_content = await self.download_pdf(cleaned["supp_materials_url"])
                if supp_content:
                    cleaned["supp_materials_content"] = supp_content

            logger.info(f"Processed paper: {cleaned.get('title', 'Unknown')}")
            return cleaned

        except Exception as e:
            logger.error(f"Error processing paper {paper_url}: {e}")
            return None

    @sync_to_async
    @transaction.atomic
    def save_paper_to_db(self, paper_data: dict, conference: Conference) -> Paper:
        """Save or update a paper in the database."""
        # Define expected fields (Paper model fields and special processing fields)
        expected_fields = {
            "title", "doi", "abstract", "paper_url", "pdf_url", "code_url",
            "authors", "meta_review", "reviews", "author_feedback",
            "datasets", "pdf_content", "supp_materials_content", "supp_materials_url"
        }
        
        # Store unexpected fields in metadata instead of discarding them
        unexpected_fields = set(paper_data.keys()) - expected_fields
        metadata = {}
        if unexpected_fields:
            logger.info(f"Storing unexpected fields in metadata: {unexpected_fields}")
            for field in unexpected_fields:
                metadata[field] = paper_data.pop(field)
        
        paper_data['metadata'] = metadata if metadata else None
        
        # Prepare paper fields
        paper_fields = {
            "title": (paper_data.get("title") or "")[:500],
            "doi": (paper_data.get("doi") or "")[:255] if paper_data.get("doi") else None,
            "abstract": paper_data.get("abstract"),
            "paper_url": (paper_data.get("paper_url") or "")[:500],
            "pdf_url": (paper_data.get("pdf_url") or "")[:500],
            "code_url": (paper_data.get("code_url") or "")[:500],
            "authors": (paper_data.get("authors") or "")[:255] if paper_data.get("authors") else None,
            "meta_review": paper_data.get("meta_review"),
            "reviews": paper_data.get("reviews"),
            "author_feedback": paper_data.get("author_feedback"),
            "metadata": paper_data.get("metadata"),
            "conference": conference,
        }

        # Create or update paper
        paper, created = Paper.objects.update_or_create(
            paper_url=paper_fields["paper_url"],
            defaults=paper_fields,
        )

        # Download and save PDF files
        pdf_content = paper_data.get("pdf_content")
        if pdf_content and (created or not paper.file):
            # Generate filename from title or DOI
            filename = re.sub(r'[^a-zA-Z0-9_-]', '_', paper.title[:50]) + ".pdf"
            paper.file.save(filename, ContentFile(pdf_content), save=False)
            logger.info(f"Saved PDF file for: {paper.title}")
        
        supp_content = paper_data.get("supp_materials_content")
        if supp_content and (created or not paper.supp_materials):
            filename = re.sub(r'[^a-zA-Z0-9_-]', '_', paper.title[:50]) + "_supp.pdf"
            paper.supp_materials.save(filename, ContentFile(supp_content), save=False)
            logger.info(f"Saved supplementary materials for: {paper.title}")
        
        # Save if files were added
        if pdf_content or supp_content:
            paper.save()

        # Handle datasets
        datasets = paper_data.get("datasets")
        if datasets and isinstance(datasets, dict):
            for dataset_name, dataset_url in datasets.items():
                dataset, _ = Dataset.objects.get_or_create(
                    url=dataset_url,
                    defaults={
                        "name": dataset_name[:300],
                        "from_pdf": False,
                    },
                )
                paper.datasets.add(dataset)
        
        action = "Created" if created else "Updated"
        logger.info(f"{action} paper: {paper.title}")
        
        # Note: Text extraction will be done separately after PDF is saved
        # to avoid blocking the database transaction
        return paper, created

    async def extract_text_from_pdf(self, paper) -> bool:
        """
        Extract text from a paper's PDF file using Grobid.
        Uses semaphore to limit concurrent Grobid calls.
        
        Returns:
            True if successful, False otherwise
        """
        if not paper.file:
            return False
            
        grobid_sem = get_grobid_semaphore()
        async with grobid_sem:
            try:
                # Run Grobid extraction in thread pool
                pdf_path = paper.file.path
                
                @sync_to_async
                def extract():
                    title, text, sections = get_pdf_content(pdf_path)
                    return text, sections
                
                text, sections = await extract()
                
                # Save text and sections to database
                @sync_to_async
                def save_text():
                    paper.text = text
                    paper.sections = sections
                    paper.save(update_fields=['text', 'sections'])
                
                await save_text()
                logger.info(f"Extracted text from PDF for: {paper.title} ({len(text)} characters)")
                return True
                
            except Exception as e:
                logger.error(f"Failed to extract text from PDF for {paper.title}: {e}")
                return False

    async def scrape_conference(
        self,
        limit: Optional[int] = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, any]:
        """
        Main method to scrape entire conference.

        Args:
            limit: Maximum number of papers to scrape (for testing)
            progress_callback: Optional callback function(current, total, message)

        Returns:
            Dictionary with scraping results and statistics
        """
        logger.info(f"Starting scrape for {self.conference_name}")

        # Get or create conference (wrapped for async)
        @sync_to_async
        def get_or_create_conference():
            # If conference_id is provided, use the existing conference
            if self.conference_id:
                try:
                    conference = Conference.objects.get(id=self.conference_id)
                    # Update papers_url if it's different
                    if conference.papers_url != self.conference_url:
                        conference.papers_url = self.conference_url
                        conference.save()
                    return conference
                except Conference.DoesNotExist:
                    logger.warning(f"Conference with ID {self.conference_id} not found, creating new one")
            
            # Otherwise, get or create by name and year
            conference, created = Conference.objects.get_or_create(
                name=self.conference_name,
                year=self.year,
                defaults={"papers_url": self.conference_url},
            )
            if not created:
                conference.papers_url = self.conference_url
                conference.save()
            return conference
        
        conference = await get_or_create_conference()
        logger.info(f"Conference: {conference}")

        # Priority: Database schema > File schema > LLM generation
        if conference.scraping_schema:
            logger.info("Using schema from database")
            schema = conference.scraping_schema
        else:
            # Fetch HTML sample for schema generation if needed
            schema_file = self.schema_cache_dir / f"{self.conference_name.lower().replace(' ', '_')}_schema.json"
            if not schema_file.exists():
                logger.info("Fetching HTML sample for schema generation...")
                async with AsyncWebCrawler() as crawler:
                    result = await crawler.arun(url=self.conference_url)
                    if result.success:
                        # Take only first 50KB of HTML to avoid token limits
                        html_sample = result.html[:50000] if result.html else None
                    else:
                        html_sample = None
                schema = self.get_schema(html_sample=html_sample)
            else:
                schema = self.get_schema()
        
        # Crawl paper list using the schema
        paper_list = await self.crawl_paper_list(schema)

        # Apply limit if specified
        if limit:
            paper_list = paper_list[:limit]
            logger.info(f"Limited to {limit} papers for testing")

        total_papers = len(paper_list)
        processed_papers = []
        failed_papers = []
        created_count = 0
        updated_count = 0

        # Create semaphore for concurrent crawling
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)

        async def limited_process(idx, p):
            async with semaphore:
                if progress_callback:
                    progress_callback(idx + 1, total_papers, f"Processing: {p.get('title', 'Unknown')}")
                return await self._process_paper(p, schema)

        # Process papers in batches to avoid memory overload
        logger.info(f"Processing {total_papers} papers in batches of {BATCH_SIZE}")
        
        for batch_start in range(0, total_papers, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_papers)
            batch = paper_list[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//BATCH_SIZE + 1}/{(total_papers + BATCH_SIZE - 1)//BATCH_SIZE} (papers {batch_start+1}-{batch_end})")
            
            # Process current batch concurrently
            tasks = [
                asyncio.create_task(limited_process(batch_start + idx, paper))
                for idx, paper in enumerate(batch)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Save batch results to database
            batch_papers = []
            for i, paper_data in enumerate(results):
                if isinstance(paper_data, Exception):
                    logger.error(f"Error processing paper: {paper_data}")
                    failed_papers.append(batch[i].get("title", "Unknown"))
                    continue
                    
                if paper_data:
                    try:
                        paper, was_created = await self.save_paper_to_db(paper_data, conference)
                        if was_created:
                            created_count += 1
                        else:
                            updated_count += 1
                        batch_papers.append(paper)
                        processed_papers.append(paper)
                    except Exception as e:
                        import traceback
                        logger.error(f"Error saving paper: {e}")
                        logger.error(f"Traceback: {traceback.format_exc()}")
                        logger.error(f"Paper data: {paper_data}")
                        failed_papers.append(paper_data.get("title", "Unknown"))
                else:
                    failed_papers.append("Unknown (processing failed)")
            
            # Extract text from PDFs in this batch (with Grobid rate limiting)
            if batch_papers:
                logger.info(f"Extracting text from {len(batch_papers)} PDFs in batch...")
                text_tasks = [
                    asyncio.create_task(self.extract_text_from_pdf(paper))
                    for paper in batch_papers
                ]
                await asyncio.gather(*text_tasks, return_exceptions=True)
            
            logger.info(f"Batch complete: {len(batch_papers)} papers processed, {created_count} created, {updated_count} updated")

        result = {
            "conference": conference.name,
            "total_found": total_papers,
            "processed": len(processed_papers),
            "created": created_count,
            "updated": len(processed_papers) - created_count,
            "failed": len(failed_papers),
            "failed_papers": failed_papers,
        }

        logger.info(f"Scraping complete: {result}")
        return result
