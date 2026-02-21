"""
Quick script to check MICCAI 2021 data quality after scraping.
"""
import os
import sys
import django

sys.path.insert(0, '/home/administrator/papersnitch/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings')
django.setup()

from webApp.models import Paper, Conference
from django.db.models import Q

# Get MICCAI 2021 conference
conf = Conference.objects.filter(name__icontains='MICCAI', year=2021).first()

if not conf:
    print('❌ MICCAI 2021 conference not found!')
    sys.exit(1)

print(f'📊 MICCAI 2021 Data Quality Report')
print(f'=' * 60)
print(f'Conference: {conf.name} {conf.year}')
print()

papers = Paper.objects.filter(conference=conf)
total = papers.count()

# Count papers with different data
with_doi = papers.exclude(Q(doi__isnull=True) | Q(doi='')).count()
with_abstract = papers.exclude(Q(abstract__isnull=True) | Q(abstract='')).count()
with_code_url = papers.exclude(Q(code_url__isnull=True) | Q(code_url='')).count()
with_pdf = papers.exclude(file='').count()

print(f'Total papers: {total}')
print()
print(f'Papers with DOI:      {with_doi:4d} / {total} ({with_doi/total*100:.1f}%)')
print(f'Papers with abstract: {with_abstract:4d} / {total} ({with_abstract/total*100:.1f}%)')
print(f'Papers with code URL: {with_code_url:4d} / {total} ({with_code_url/total*100:.1f}%)')
print(f'Papers with PDF file: {with_pdf:4d} / {total} ({with_pdf/total*100:.1f}%)')
print()

# Show a sample of papers
print('Sample papers:')
print('-' * 60)
for p in papers[:3]:
    print(f'\n📄 {p.title[:60]}...')
    print(f'   DOI: {p.doi[:50] if p.doi else "❌ MISSING"}')
    print(f'   Abstract: {"✓" if p.abstract else "❌ MISSING"} ({len(p.abstract) if p.abstract else 0} chars)')
    print(f'   Code: {p.code_url[:50] if p.code_url else "-"}')

print()
print('=' * 60)

if with_doi < total * 0.8 or with_abstract < total * 0.8:
    print('⚠️  Data quality needs improvement - consider re-scraping')
else:
    print('✅ Data quality looks good!')
