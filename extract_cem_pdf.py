from pathlib import Path
import PyPDF2

pdf_path = Path(r"c:\Users\shqqq\Downloads\cem.pdf")
print(f"exists={pdf_path.exists()}")
print(f"size={pdf_path.stat().st_size if pdf_path.exists() else 'missing'}")
reader = PyPDF2.PdfReader(str(pdf_path))
print(f"pages={len(reader.pages)}")
text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
print(text[:20000])
