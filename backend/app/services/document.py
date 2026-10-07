import io, re

def extract_text(filename: str, data: bytes) -> tuple[str, int]:
    ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if ext in {'txt','md','csv','json','py','java','js','ts','html','css'}:
        return data.decode('utf-8', errors='ignore'), 1
    if ext == 'pdf':
        try:
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(data))
            return '\n\n'.join((p.extract_text() or '') for p in r.pages), len(r.pages)
        except Exception as e: return f'[PDF extraction unavailable: {e}]', 0
    if ext == 'docx':
        try:
            from docx import Document
            d = Document(io.BytesIO(data)); return '\n'.join(p.text for p in d.paragraphs), 1
        except Exception as e: return f'[DOCX extraction unavailable: {e}]', 0
    if ext == 'pptx':
        try:
            from pptx import Presentation
            p = Presentation(io.BytesIO(data)); text=[]
            for i, slide in enumerate(p.slides, 1):
                text.append(f'\n[Slide {i}]'); text.extend(s.text for s in slide.shapes if hasattr(s,'text') and s.text)
            return '\n'.join(text), len(p.slides)
        except Exception as e: return f'[PPTX extraction unavailable: {e}]', 0
    return '[Unsupported document format]', 0

def normalize_text(text:str)->str:
    return re.sub(r'\n{3,}','\n\n',re.sub(r'[ \t]+',' ',text)).strip()
def chunk_text(text:str,size:int=1200,overlap:int=180)->list[str]:
    text=normalize_text(text)
    if not text:return []
    chunks=[]; start=0
    while start<len(text):
        end=min(len(text),start+size)
        if end<len(text):
            cut=text.rfind(' ',start,end)
            if cut>start+size//2:end=cut
        chunks.append(text[start:end].strip())
        if end>=len(text):break
        start=max(end-overlap,start+1)
    return chunks
