
from pypdf import PdfReader

pdf_path = "data/ct200_manual.pdf"

reader = PdfReader(pdf_path)

print("CT-200 MANUAL INSPECTION")
print("=" * 60)
print("Total pages:", len(reader.pages))

for page_number, page in enumerate(reader.pages, start=1):
    text = page.extract_text() or ""

    print("\n" + "=" * 60)
    print("PAGE", page_number)
    print("=" * 60)
    print(text) 