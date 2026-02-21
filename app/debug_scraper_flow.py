"""
Debug script to see exactly what data is being extracted and saved.
"""
import os
import sys
import django
import asyncio
import json

sys.path.insert(0, '/home/administrator/papersnitch/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings')
django.setup()

from webApp.services.conference_scraper import ConferenceScraper
from webApp.models import Conference

async def main():
    # Get conference
    conf = await asyncio.to_thread(
        Conference.objects.filter(name__icontains='MICCAI', year=2021).first
    )
    
    scraper = ConferenceScraper(
        conference_name="MICCAI 2021",
        conference_url="https://miccai2021.org/openaccess/paperlinks/index.html",
        year=2021,
        conference_id=conf.id
    )
    
    # Load schema
    schema = scraper.get_schema()
    
    # Test URL
    test_url = "https://miccai2021.org/openaccess/paperlinks/2021/09/01/001-Paper1891.html"
    
    # Process paper
    paper_data = {
        "title": "2.5D Thermometry Maps for MRI-guided Tumor Ablation",
        "paper_url": test_url
    }
    
    cleaned = await scraper._process_paper(paper_data, schema)
    
    print("=" * 70)
    print("CLEANED DATA FROM _process_paper:")
    print("=" * 70)
    for key, value in cleaned.items():
        if key in ["pdf_content", "supp_materials_content"]:
            print(f"{key}: <binary data {len(value)} bytes>")
        elif isinstance(value, str) and len(value) > 100:
            print(f"{key}: {value[:100]}...")
        else:
            print(f"{key}: {value}")
    
    print("\n" + "=" * 70)
    print("CHECKING EXPECTED FIELDS:")
    print("=" * 70)
    expected = {"title", "doi", "abstract", "paper_url", "pdf_url", "code_url",
                "authors", "meta_review", "reviews", "author_feedback"}
    
    for field in expected:
        has_it = field in cleaned
        value = cleaned.get(field)
        print(f"{field:20s}: {'✓' if has_it and value else '✗'} {type(value).__name__ if has_it else 'missing'}")

if __name__ == "__main__":
    asyncio.run(main())
