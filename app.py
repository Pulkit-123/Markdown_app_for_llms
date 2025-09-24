"""
Universal File → Markdown Converter (Drag, Drop, Download)
----------------------------------------------------------
A super-simple Streamlit app that:
  [1] takes file uploads as user input
  [2] converts them to Markdown via `markitdown`
  [3] shows a 1,000-char preview
  [4] provides a download button for the full .md file

UI: Drag, drop, download. Nothing more.

How it works (structure):
- save_upload(): writes an in-memory upload to a temporary path
- convert_with_markitdown(): returns Markdown text from a file path
- build_output_name(): generates a clean output filename (original + timestamp)
- Streamlit layout: uploader → per-file preview → per-file download
"""

import io
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Tuple

import streamlit as st
from markitdown import MarkItDown


# --------------------------
# Helpers
# --------------------------
def save_upload(upload) -> str:
    """
    Persist the uploaded file-like object to a temporary path.
    Returns:
        str: Absolute file path on disk suitable for markitdown.
    """
    suffix = Path(upload.name).suffix or ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.read())
        return tmp.name  # caller responsible for cleanup


def convert_with_markitdown(src_path: str) -> str:
    """
    Convert a file at `src_path` to Markdown using markitdown.
    Returns:
        str: Markdown content (empty string if none).
    """
    md = MarkItDown()
    result = md.convert(src_path)
    return (result.text_content or "").strip()


def build_output_name(input_name: str) -> str:
    """
    Create a deterministic output filename for the Markdown export.
    Example: 'report.docx' -> 'report__20250101-120000.md'
    """
    base = Path(input_name).stem or "converted"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base}__{stamp}.md"


# --------------------------
# Streamlit App
# --------------------------
st.set_page_config(page_title="File → Markdown", page_icon="📝", layout="centered")

st.markdown("## 📝 File → Markdown (Drag, Drop, Download)")
st.caption("Drop DOCX, PPTX, XLSX, PDF, HTML, ZIP, etc. We'll convert them to Markdown and let you download.")

uploads = st.file_uploader(
    "Drop files here (or click to browse)",
    type=None,               # accept any; markitdown routes by extension
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploads:
    st.divider()
    st.markdown("### Results")

    for upload in uploads:
        with st.container(border=True):
            st.markdown(f"**File:** {upload.name}")

            # 1) Save to temp file
            temp_path = save_upload(upload)

            # 2) Convert with markitdown
            try:
                md_text = convert_with_markitdown(temp_path)
            except Exception as e:
                st.error(f"Conversion failed: {e}")
                md_text = ""
            finally:
                # Cleanup temp file
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            # 3) Preview (first 1000 chars)
            preview = md_text[:1000]
            if preview:
                st.markdown("**Preview (first 1000 characters):**")
                st.code(preview, language="markdown")
            else:
                st.info("No text extracted or empty document.")

            # 4) Download button for full Markdown
            out_name = build_output_name(upload.name)
            st.download_button(
                label=f"⬇️ Download {out_name}",
                data=md_text.encode("utf-8"),
                file_name=out_name,
                mime="text/markdown",
                use_container_width=True,
            )

else:
    # Simple, distraction-free landing state
    with st.container(border=True):
        st.write("Drag & drop files above to convert them to Markdown. That’s it. 🙂")
