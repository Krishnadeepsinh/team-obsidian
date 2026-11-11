import csv
import hashlib
import io
import json
import re
from typing import Any, Dict, List, Optional


def _strip_nul(text: Optional[str]) -> str:
    return (text or "").replace("\x00", "")


def _clean_json_val(val: Any) -> Any:
    if isinstance(val, str):
        return _strip_nul(val)
    if isinstance(val, dict):
        return {str(k).replace("\x00", ""): _clean_json_val(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_clean_json_val(v) for v in val]
    return val


def _decode_text_bytes(file_bytes: bytes) -> str:
    if file_bytes.startswith(b"\xff\xfe") or file_bytes.startswith(b"\xfe\xff"):
        return _strip_nul(file_bytes.decode("utf-16", errors="replace"))
    if file_bytes.startswith(b"\xef\xbb\xbf"):
        return _strip_nul(file_bytes.decode("utf-8-sig", errors="replace"))
    try:
        return _strip_nul(file_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        return _strip_nul(file_bytes.decode("latin-1", errors="replace"))


class DocumentParser:
    """Multi-format document extraction preserving page numbers, sheet names, headings, and paragraph metadata."""

    def calculate_sha256(self, content_bytes: bytes) -> str:
        return hashlib.sha256(content_bytes).hexdigest()

    def parse_pdf(self, file_bytes: bytes) -> Dict[str, Any]:
        import pymupdf

        try:
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"Invalid or unreadable PDF file: {exc}")

        try:
            if getattr(doc, "needs_pass", False):
                raise ValueError("Encrypted or password-protected PDF files cannot be indexed. Remove password protection and retry.")

            sections: List[Dict[str, Any]] = []
            text_pages: List[str] = []
            total_images = 0
            page_count = len(doc)

            for i, page in enumerate(doc):
                text = _strip_nul(page.get_text() or "").strip()
                try:
                    total_images += len(page.get_images(full=False))
                except Exception:
                    pass
                if text:
                    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)
                    sections.append({
                        "page_number": i + 1,
                        "sheet_name": None,
                        "heading": (first_line[:180] if first_line else f"Page {i + 1}"),
                        "paragraph_ref": f"page:{i + 1}",
                        "text": text,
                    })
                    text_pages.append(f"--- [Page {i + 1}] ---\n{text}")

            metadata = _clean_json_val(doc.metadata or {})
            if not sections:
                meta_parts = [
                    f"PDF document contains {page_count} page(s) with no selectable embedded text layer (scanned/image-only PDF)."
                ]
                if total_images:
                    meta_parts.append(f"Detected {total_images} embedded page image(s).")
                if isinstance(metadata, dict):
                    for k in ("title", "subject", "author"):
                        v = (metadata.get(k) or "").strip()
                        if v:
                            meta_parts.append(f"PDF {k}: {v}")
                fallback_note = " ".join(meta_parts)
                sections.append({
                    "page_number": 1 if page_count else None,
                    "sheet_name": None,
                    "heading": "PDF Visual / Scanned Notice",
                    "paragraph_ref": "page:1",
                    "text": fallback_note,
                })
                text_pages.append(fallback_note)
                metadata["is_scanned"] = True

            return {
                "text": "\n\n".join(text_pages),
                "page_count": page_count,
                "sheet_names": [],
                "metadata": metadata,
                "sections": sections,
            }
        finally:
            doc.close()

    def parse_docx(self, file_bytes: bytes) -> Dict[str, Any]:
        head = file_bytes.lstrip()[:32].lower()
        if head.startswith(b"<html") or head.startswith(b"<!doctype") or head.startswith(b"<?xml"):
            return self.parse_html(_decode_text_bytes(file_bytes))
        if head.startswith(b"{\\rtf"):
            raw = _decode_text_bytes(file_bytes)
            plain = re.sub(r"\\'[0-9a-fA-F]{2}|\\[a-zA-Z]+-?\d* ?|[{}]", " ", raw)
            plain = re.sub(r"[ \t]{2,}", " ", plain).strip()
            return self.parse_markdown_or_text(plain or "RTF document uploaded (no extractable text body).")
        if file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
            raise ValueError("Legacy binary .doc (Word 97-2003) format is not supported directly. Please save/export as .docx or .pdf and re-upload.")
        if not file_bytes.startswith(b"PK"):
            # Plain text saved with .doc extension
            if b"\x00" not in file_bytes[:512]:
                return self.parse_markdown_or_text(_decode_text_bytes(file_bytes))
            raise ValueError("Invalid Word document container. Please upload a valid .docx or .pdf file.")

        import docx

        try:
            doc = docx.Document(io.BytesIO(file_bytes))
        except Exception as exc:
            raise ValueError(f"Corrupt or unreadable DOCX archive: {exc}")

        sections: List[Dict[str, Any]] = []
        paragraphs_text: List[str] = []
        current_heading: Optional[str] = None

        for idx, p in enumerate(doc.paragraphs, 1):
            txt = _strip_nul(p.text or "").strip()
            if not txt:
                continue
            style_name = (p.style.name if p.style else "") or ""
            if "heading" in style_name.lower():
                current_heading = txt[:180]
            paragraphs_text.append(txt)
            sections.append({
                "page_number": None,
                "sheet_name": None,
                "heading": current_heading,
                "paragraph_ref": f"paragraph:{idx}",
                "text": txt,
            })

        # Also extract DOCX tables
        for t_idx, table in enumerate(doc.tables, 1):
            table_rows = []
            for row in table.rows:
                vals = [_strip_nul(c.text).strip() for c in row.cells if _strip_nul(c.text).strip()]
                if vals:
                    table_rows.append(" | ".join(vals))
            if table_rows:
                t_text = "\n".join(table_rows)
                paragraphs_text.append(t_text)
                sections.append({
                    "page_number": None,
                    "sheet_name": None,
                    "heading": current_heading or f"Table {t_idx}",
                    "paragraph_ref": f"table:{t_idx}",
                    "text": t_text,
                })

        if not sections:
            note = "DOCX archive parsed successfully with no visible paragraph or table text."
            paragraphs_text.append(note)
            sections.append({
                "page_number": None,
                "sheet_name": None,
                "heading": "Empty DOCX Body",
                "paragraph_ref": "paragraph:1",
                "text": note,
            })

        return {
            "text": "\n\n".join(paragraphs_text),
            "page_count": None,
            "sheet_names": [],
            "paragraph_count": len(paragraphs_text),
            "sections": sections,
        }

    def parse_xlsx(self, file_bytes: bytes) -> Dict[str, Any]:
        head = file_bytes.lstrip()[:32].lower()
        if head.startswith(b"<html") or head.startswith(b"<table") or head.startswith(b"<!doctype"):
            return self.parse_html(_decode_text_bytes(file_bytes))
        if file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
            raise ValueError("Legacy binary .xls (Excel 97-2003) format is not supported directly. Please save/export as .xlsx or .csv and re-upload.")
        if not file_bytes.startswith(b"PK"):
            if b"\x00" not in file_bytes[:512]:
                return self.parse_csv(_decode_text_bytes(file_bytes))
            raise ValueError("Invalid Excel workbook container. Please upload a valid .xlsx or .csv file.")

        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        except Exception as exc:
            raise ValueError(f"Corrupt or unreadable XLSX workbook: {exc}")

        try:
            sheets_text: List[str] = []
            sections: List[Dict[str, Any]] = []
            sheet_names = [_strip_nul(str(name))[:250] for name in wb.sheetnames]

            for sheet_name in wb.sheetnames:
                clean_sheet = _strip_nul(str(sheet_name))[:250]
                sheet = wb[sheet_name]
                rows = []
                for row in sheet.iter_rows(values_only=True):
                    non_empty = [_strip_nul(str(cell)).strip() for cell in row if cell is not None and _strip_nul(str(cell)).strip()]
                    if non_empty:
                        rows.append(" | ".join(non_empty))
                if rows:
                    sheet_body = "\n".join(rows)
                    sheets_text.append(f"--- [Sheet: {clean_sheet}] ---\n{sheet_body}")
                    sections.append({
                        "page_number": None,
                        "sheet_name": clean_sheet,
                        "heading": clean_sheet[:180],
                        "paragraph_ref": f"sheet:{clean_sheet}"[:250],
                        "text": sheet_body,
                    })

            if not sections:
                note = f"XLSX workbook contains sheet(s) [{', '.join(sheet_names) or 'none'}] with no populated cell values."
                sheets_text.append(note)
                sections.append({
                    "page_number": None,
                    "sheet_name": sheet_names[0] if sheet_names else None,
                    "heading": "Empty Workbook",
                    "paragraph_ref": "sheet:1",
                    "text": note,
                })

            return {
                "text": "\n\n".join(sheets_text),
                "page_count": None,
                "sheet_names": sheet_names,
                "sheet_count": len(sheet_names),
                "sections": sections,
            }
        finally:
            wb.close()

    def parse_csv(self, text_str: str) -> Dict[str, Any]:
        reader = csv.reader(io.StringIO(text_str))
        rows = [" | ".join(cell.strip() for cell in row if cell is not None) for row in reader]
        rows = [r for r in rows if r.strip()]
        body = "\n".join(rows)
        return {
            "text": body,
            "page_count": None,
            "sheet_names": ["csv"],
            "sections": [{"page_number": None, "sheet_name": "csv", "heading": "CSV Data", "paragraph_ref": "rows:1+", "text": body}] if body else [],
        }

    def parse_markdown_or_text(self, text_str: str) -> Dict[str, Any]:
        lines = text_str.splitlines()
        sections: List[Dict[str, Any]] = []
        current_heading: Optional[str] = None
        buf: List[str] = []
        p_idx = 1

        def flush_buf():
            nonlocal p_idx
            if buf:
                chunk = "\n".join(buf).strip()
                if chunk:
                    sections.append({
                        "page_number": None,
                        "sheet_name": None,
                        "heading": current_heading,
                        "paragraph_ref": f"section:{p_idx}",
                        "text": chunk,
                    })
                    p_idx += 1
                buf.clear()

        for ln in lines:
            m = re.match(r"^(#{1,4})\s+(.+)$", ln.strip())
            if m:
                flush_buf()
                current_heading = m.group(2).strip()[:180]
                buf.append(ln.strip())
            else:
                buf.append(ln)
        flush_buf()

        clean_text = text_str.strip()
        if not sections and clean_text:
            sections.append({
                "page_number": None,
                "sheet_name": None,
                "heading": None,
                "paragraph_ref": "section:1",
                "text": clean_text,
            })

        return {
            "text": clean_text,
            "page_count": None,
            "sheet_names": [],
            "sections": sections,
        }

    def parse_html(self, text_str: str) -> Dict[str, Any]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text_str, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        sections: List[Dict[str, Any]] = []
        current_heading: Optional[str] = None
        p_idx = 1
        for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "table"]):
            txt = el.get_text(" ", strip=True)
            if not txt:
                continue
            if el.name in ("h1", "h2", "h3", "h4"):
                current_heading = txt[:180]
            sections.append({
                "page_number": None,
                "sheet_name": None,
                "heading": current_heading,
                "paragraph_ref": f"{el.name}:{p_idx}",
                "text": txt,
            })
            p_idx += 1

        full_text = soup.get_text(separator="\n").strip()
        return {
            "text": full_text,
            "page_count": None,
            "sheet_names": [],
            "sections": sections or [{"page_number": None, "sheet_name": None, "heading": None, "paragraph_ref": "html:1", "text": full_text}],
        }

    def parse_file(self, filename: str, file_bytes: bytes) -> Dict[str, Any]:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
        if ext == "pdf":
            return self.parse_pdf(file_bytes)
        if ext in ("docx", "doc"):
            return self.parse_docx(file_bytes)
        if ext in ("xlsx", "xls"):
            return self.parse_xlsx(file_bytes)
        text_str = _decode_text_bytes(file_bytes)
        if ext == "csv":
            return self.parse_csv(text_str)
        if ext in ("html", "htm", "xml"):
            return self.parse_html(text_str)
        if ext == "json":
            try:
                formatted = json.dumps(_clean_json_val(json.loads(text_str)), indent=2)
                return self.parse_markdown_or_text(formatted)
            except Exception:
                return self.parse_markdown_or_text(text_str)
        return self.parse_markdown_or_text(text_str)

    def chunk_sections(
        self,
        sections: List[Dict[str, Any]],
        fallback_text: str = "",
        chunk_size: int = 1000,
        overlap: int = 150,
    ) -> List[Dict[str, Any]]:
        """Chunk parsed sections into overlapping segments while preserving page, sheet, heading, and paragraph refs."""
        if not sections and fallback_text:
            sections = [{"page_number": None, "sheet_name": None, "heading": None, "paragraph_ref": "section:1", "text": fallback_text}]

        chunks: List[Dict[str, Any]] = []
        chunk_idx = 0
        global_offset = 0

        # Merge small adjacent sections with the same page/sheet/heading before chunking
        grouped: List[Dict[str, Any]] = []
        for sec in sections:
            sec_txt = (sec.get("text") or "").strip()
            if not sec_txt:
                continue
            if (
                grouped
                and grouped[-1].get("page_number") == sec.get("page_number")
                and grouped[-1].get("sheet_name") == sec.get("sheet_name")
                and grouped[-1].get("heading") == sec.get("heading")
                and len(grouped[-1]["text"]) + len(sec_txt) + 2 <= chunk_size
            ):
                grouped[-1]["text"] += "\n\n" + sec_txt
            else:
                grouped.append({
                    "page_number": sec.get("page_number"),
                    "sheet_name": sec.get("sheet_name"),
                    "heading": sec.get("heading"),
                    "paragraph_ref": sec.get("paragraph_ref"),
                    "text": sec_txt,
                })

        for sec in grouped:
            text = sec["text"]
            start = 0
            text_len = len(text)
            while start < text_len:
                end = min(start + chunk_size, text_len)
                content = text[start:end].strip()
                if content:
                    chunks.append({
                        "chunk_index": chunk_idx,
                        "page_number": sec.get("page_number"),
                        "sheet_name": sec.get("sheet_name"),
                        "heading": sec.get("heading"),
                        "paragraph_ref": sec.get("paragraph_ref"),
                        "start_char": global_offset + start,
                        "end_char": global_offset + end,
                        "content": content,
                        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    })
                    chunk_idx += 1
                if end == text_len:
                    break
                start += max(1, chunk_size - overlap)
            global_offset += text_len + 2

        return chunks

    def chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 150) -> List[Dict[str, Any]]:
        return self.chunk_sections([], fallback_text=text, chunk_size=chunk_size, overlap=overlap)


document_parser = DocumentParser()
