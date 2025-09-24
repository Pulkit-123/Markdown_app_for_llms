"""
Docs to Markdown Converter — Streamlit (with File Size Comparison)
------------------------------------------------------------------
What's new:
- Broader allowed extensions (HTML/HTM, CSV/TXT/MD/RTF, legacy Office, images, audio, ZIP)
- Per-file tabs: "Result" and "File Size Comparison"
- Size table: Original size vs Converted .txt size + "% smaller" metric

Other goodness kept:
- Drag & drop → Markdown via `markitdown`
- 1,000-char preview + rendered markdown in an expander
- Per-file Download (.md), optional .txt export, optional Download-All ZIP
- Large-file warning + chunked save with progress bar
- SHA-256 dedupe & cache
"""

import io
import os
import re
import zipfile
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Optional

import streamlit as st
from markitdown import MarkItDown

# --------------------------
# Config
# --------------------------
# Keep these lowercase (no leading dots) for Streamlit's uploader
ALLOWED_TYPES = [
    # Office & docs
    "pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "rtf",
    # Web & text
    "html", "htm", "md", "txt", "csv", "tsv",
    # Images (OCR-capable if configured)
    "jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp",
    # Audio (if using markitdown[all])
    "mp3", "wav", "m4a", "ogg", "flac",
    # Archives
    "zip",
]

# Internal check with dots
ACCEPTED_EXTS = tuple("." + x for x in ALLOWED_TYPES)

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB
WARN_MB = 50                  # warn users beyond this
HARD_CAP_MB = 200             # block beyond this
PREVIEW_CHARS = 1000

st.set_page_config(
    page_title="Docs to Markdown Converter",
    page_icon="📝",
    layout="centered",
)

st.title("Docs to Markdown Converter")
st.caption("Drag & drop your files. We’ll convert to Markdown, show a preview, and let you download the result.")

# --------------------------
# Session State
# --------------------------
if "results" not in st.session_state:
    # results: dict[sha256] -> {
    #   "name": str,
    #   "md": str,
    #   "txt": Optional[str],
    #   "ts": str,
    #   "original_bytes": int,
    #   "txt_bytes": Optional[int]
    # }
    st.session_state.results = {}

# --------------------------
# Utilities
# --------------------------
def sanitize_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9._-]", "", name) or "file"

def build_output_name(input_name: str, ext: str = ".md") -> str:
    base = sanitize_filename(Path(input_name).stem or "converted")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base}__{stamp}{ext}"

def strip_markdown(md: str) -> str:
    # Light MD → text
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", md)
    text = re.sub(r"^\s{0,3}(#+|\*|-|\+|>)\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)         # images alt text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)          # link text
    text = re.sub(r"[*_>#~`]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in ACCEPTED_EXTS

def human_mb(num_bytes: int) -> float:
    return num_bytes / (1024 * 1024) if num_bytes is not None else 0.0

def sha256_stream_and_save(uploaded_file, suffix: str) -> Tuple[str, str, int]:
    """Stream an UploadedFile to temp while hashing & tracking size."""
    total_size = getattr(uploaded_file, "size", None)
    if total_size and human_mb(total_size) > HARD_CAP_MB:
        raise ValueError(f"File exceeds hard size cap of {HARD_CAP_MB} MB.")

    h = hashlib.sha256()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = tmp.name

    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    bytes_written = 0
    progress = st.progress(0, text="Saving upload…")
    while True:
        chunk = uploaded_file.read(CHUNK_SIZE)
        if not chunk:
            break
        tmp.write(chunk)
        h.update(chunk)
        bytes_written += len(chunk)
        if total_size:
            progress.progress(min(bytes_written / total_size, 1.0), text="Saving upload…")
        if bytes_written and human_mb(bytes_written) > HARD_CAP_MB:
            tmp.close()
            try: os.remove(tmp_path)
            except OSError: pass
            progress.empty()
            raise ValueError(f"File exceeds hard size cap of {HARD_CAP_MB} MB.")
    tmp.close()
    progress.empty()
    return tmp_path, h.hexdigest(), bytes_written

@st.cache_data(show_spinner=False)
def convert_via_markitdown(temp_path: str) -> str:
    md = MarkItDown()
    res = md.convert(temp_path)
    return (res.text_content or "").strip()

def pct_smaller(orig_bytes: int, txt_bytes: int) -> Optional[float]:
    if orig_bytes and txt_bytes is not None:
        ratio = 1.0 - (txt_bytes / max(orig_bytes, 1))
        return max(min(ratio * 100.0, 100.0), -100.0)
    return None

# --------------------------
# Sidebar (optional toggles)
# --------------------------
with st.sidebar:
    st.subheader("Options")
    also_plain_text = st.checkbox("Also export plain-text (.txt)", value=False)
    allow_zip_all = st.checkbox("Enable 'Download All as ZIP'", value=True)
    st.caption(f"Accepted: {', '.join(ALLOWED_TYPES)}")
    st.caption("Files over 50 MB show a warning; over 200 MB are blocked.")

# --------------------------
# Uploader
# --------------------------
uploads = st.file_uploader(
    "Drop files here (or click to browse)",
    type=ALLOWED_TYPES,
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if not uploads:
    with st.container(border=True):
        st.write("Drag & drop supported files above. We’ll convert them to Markdown and let you download.")
    st.stop()

st.divider()
st.subheader("Results")

# --------------------------
# Process each file
# --------------------------
for upload in uploads:
    with st.container(border=True):
        st.markdown(f"**File:** {upload.name}")

        # Validate extension
        if not is_supported(upload.name):
            st.error("Unsupported file type.")
            continue

        # Size warnings
        size_bytes = getattr(upload, "size", None)
        if size_bytes is not None:
            size_mb = human_mb(size_bytes)
            if WARN_MB < size_mb <= HARD_CAP_MB:
                st.warning(f"This file is **{size_mb:.1f} MB**. Conversion may take longer.")

        # Save + hash
        suffix = Path(upload.name).suffix or ""
        try:
            temp_path, file_hash, saved_bytes = sha256_stream_and_save(upload, suffix)
        except Exception as e:
            st.error(f"Upload failed: {e}")
            continue

        # Dedupe
        if file_hash in st.session_state.results:
            st.info("Already converted in this session. Using cached result.")
            md_text = st.session_state.results[file_hash]["md"]
            txt_text = st.session_state.results[file_hash].get("txt")
            original_bytes = st.session_state.results[file_hash]["original_bytes"]
            txt_bytes = st.session_state.results[file_hash].get("txt_bytes")
        else:
            # Convert
            try:
                with st.spinner("Converting…"):
                    md_text = convert_via_markitdown(temp_path)
            except Exception as e:
                st.error(f"Conversion failed: {e}")
                md_text = ""
            finally:
                try: os.remove(temp_path)
                except OSError: pass

            # Compute TXT (even if we don't export, for size comparison)
            txt_text = strip_markdown(md_text) if md_text else ""
            original_bytes = saved_bytes
            txt_bytes = len(txt_text.encode("utf-8")) if txt_text is not None else 0

            st.session_state.results[file_hash] = {
                "name": upload.name,
                "md": md_text,
                "txt": txt_text if also_plain_text else None,
                "ts": datetime.now().isoformat(timespec="seconds"),
                "original_bytes": original_bytes,
                "txt_bytes": txt_bytes,
            }

        # --------------------------
        # Tabs: Result | File Size Comparison
        # --------------------------
        tab_result, tab_sizes = st.tabs(["Result", "File Size Comparison"])

        with tab_result:
            # Preview
            preview = (md_text or "")[:PREVIEW_CHARS]
            if preview:
                st.markdown("**Preview (first 1,000 characters):**")
                st.code(preview, language="markdown")
            else:
                st.info("No text extracted or the document is empty.")

            # Downloads
            out_md_name = build_output_name(upload.name, ".md")
            st.download_button(
                label=f"⬇️ Download {out_md_name}",
                data=(md_text or "").encode("utf-8"),
                file_name=out_md_name,
                mime="text/markdown",
                use_container_width=True,
            )
            if also_plain_text and st.session_state.results[file_hash].get("txt"):
                out_txt_name = build_output_name(upload.name, ".txt")
                st.download_button(
                    label=f"⬇️ Download {out_txt_name}",
                    data=st.session_state.results[file_hash]["txt"].encode("utf-8"),
                    file_name=out_txt_name,
                    mime="text/plain",
                    use_container_width=True,
                )

            # Rendered Markdown
            with st.expander("Rendered Preview"):
                st.markdown(md_text or "_(Nothing to render)_")

        with tab_sizes:
            # Two-row table + % smaller
            o_mb = human_mb(original_bytes)
            t_mb = human_mb(txt_bytes)
            pct = pct_smaller(original_bytes, txt_bytes)

            # Display a clean table
            st.markdown("**File Size Comparison**")
            st.table({
                "Metric": ["Original file size", "Converted .txt file size"],
                "Value": [f"{o_mb:.2f} MB", f"{t_mb:.2f} MB"]
            })

            # Percentage smaller
            if pct is not None and original_bytes > 0:
                st.success(f"**Text version is {pct:.0f}% smaller.**")
            else:
                st.info("Size comparison unavailable.")

# --------------------------
# Bundle: Download all as ZIP
# --------------------------
if st.session_state.results:
    st.divider()
    if st.checkbox("Enable 'Download All as ZIP' (all converted files)", value=True):
        if st.button("⬇️ Prepare ZIP", use_container_width=True):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for _, item in st.session_state.results.items():
                    base = sanitize_filename(Path(item["name"]).stem)
                    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                    md_name = f"{base}__{ts}.md"
                    zf.writestr(md_name, item["md"] or "")
                    # include txt if we generated/stored it
                    if item.get("txt"):
                        txt_name = f"{base}__{ts}.txt"
                        zf.writestr(txt_name, item["txt"] or "")
            buf.seek(0)
            st.download_button(
                label="⬇️ Save ZIP",
                data=buf,
                file_name=f"converted_markdown_{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip",
                mime="application/zip",
                use_container_width=True,
            )
