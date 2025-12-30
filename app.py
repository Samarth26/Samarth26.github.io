# app.py
import json
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw
import io
import base64
import streamlit.components.v1 as components

# --------- CONFIG ---------
st.set_page_config(page_title="Invoice Viewer", layout="wide")

st.title("Invoice PDF + Parsed JSON Viewer")

# Sidebar: choose a document folder
st.sidebar.header("Select Document")

base_dir = st.sidebar.text_input(
    "Base directory containing documents",
    value="./processed_attachments"
)

# For simplicity: user pastes a specific folder path for one invoice
doc_folder = st.sidebar.text_input(
    "Invoice folder (relative or absolute)",
    value="(WEB)ARRIVAL NOTICE 120FA05778 E006A12 KHSIH KHSIH USLAX USLAX 1.eml"
)

if not doc_folder:
    st.info("Enter an invoice folder in the sidebar to start.")
    st.stop()

doc_folder_path = Path(doc_folder)
if not doc_folder_path.is_absolute():
    doc_folder_path = Path(base_dir) / doc_folder

# Paths we expect – adjust names to your pipeline

# Find an image file in the directory (try png, jpg, jpeg)
img_path = None
for pattern in ("*.png", "*.jpg", "*.jpeg"):
    img_path = next(doc_folder_path.glob(pattern), None)
    if img_path:
        break

# Show files in the selected folder in the Streamlit UI (prints go to server logs; use st to show in browser)
try:
    files_list = sorted([p.name for p in doc_folder_path.iterdir()])
except FileNotFoundError:
    files_list = []

st.sidebar.subheader("Files in folder (for debugging)")
# show total count
st.sidebar.write(f"{len(files_list)} files")

# Provide an expander with the full file listing (avoids UI truncation for long lists)
with st.sidebar.expander("Show full file list"):
    # Use text area to ensure everything is visible and copyable
    st.text_area("Files (one per line)", value="\n".join(files_list), height=200)

# Also provide a selectbox so user can manually choose the file to use (override auto-selection)
chosen_file_from_list = None
if files_list:
    chosen_file_from_list = st.sidebar.selectbox("Pick a file from this folder (manual override)", options=["(none)"] + files_list)
    if chosen_file_from_list == "(none)":
        chosen_file_from_list = None

# Find the state JSON file robustly:
# 1) Prefer filenames containing 'with_full_state'
# 2) Otherwise scan ALL .json files (recursively) and pick the first that contains the expected keys
state_json_file = None

# (A) quick filename-based preference
for candidate in doc_folder_path.rglob('*.json'):
    if 'with_full_state' in candidate.name:
        state_json_file = candidate
        break

json_candidates = list(doc_folder_path.rglob('*.json'))

# (B) if not found by name, inspect JSON contents for the expected keys
if state_json_file is None:
    found = None
    inspected = []
    for candidate in json_candidates:
        try:
            with open(candidate, 'r', encoding='utf-8') as fh:
                obj = json.load(fh)
        except Exception as e:
            inspected.append((candidate.name, False, f'load_error: {e}'))
            continue

        has_parsed = isinstance(obj.get('parsed_json'), (dict, list))
        has_ocr = isinstance(obj.get('parsed_json_ocr'), (dict, list))
        inspected.append((candidate.name, has_parsed and has_ocr, f'parsed_json:{has_parsed}, parsed_json_ocr:{has_ocr}'))
        if has_parsed and has_ocr and found is None:
            found = candidate
    state_json_file = found

# (C) final fallback: if no JSON contained the expected keys, but there's at least one .json file, pick the first one
if state_json_file is None and json_candidates:
    state_json_file = json_candidates[0]

# Allow manual override: if user picked a file from the file list, prefer that when it is a .json
if chosen_file_from_list and chosen_file_from_list.lower().endswith('.json'):
    candidate_path = doc_folder_path / chosen_file_from_list
    if candidate_path.exists():
        state_json_file = candidate_path

state_json_path = state_json_file

if not img_path.exists():
    st.error(f"Image not found at: {img_path}")
    st.stop()

if not state_json_path.exists():
    st.error(f"state.json not found at: {state_json_path}")
    st.stop()

# Load state-like info from JSON
with open(state_json_path, "r", encoding="utf-8") as f:
    state_data = json.load(f)

parsed_json = state_data.get("parsed_json")
parsed_json_ocr = state_data.get("parsed_json_ocr")
ocr_blocks = state_data.get("ocr_blocks")

if parsed_json is None or parsed_json_ocr is None:
    st.error("state.json must contain 'parsed_json' and 'parsed_json_ocr'.")
    st.stop()


# --------- SIDEBAR: show parsed_json ---------
st.sidebar.subheader("Parsed JSON")
st.sidebar.json(parsed_json)

# Optional: let user filter by label
# Build a pages structure for labels similar to how we handle boxes later
if isinstance(parsed_json_ocr, dict) and "pages" in parsed_json_ocr:
    pages_for_labels = parsed_json_ocr["pages"]
elif isinstance(parsed_json_ocr, list):
    if parsed_json_ocr and isinstance(parsed_json_ocr[0], dict) and "boxes" in parsed_json_ocr[0]:
        pages_for_labels = parsed_json_ocr
    elif parsed_json_ocr and isinstance(parsed_json_ocr[0], dict) and "bbox" in parsed_json_ocr[0]:
        # flat list of boxes -> wrap into a single page
        pages_for_labels = [{"page": 0, "boxes": parsed_json_ocr}]
    else:
        pages_for_labels = []
else:
    pages_for_labels = []

all_labels = sorted({box.get("label", "") for p in pages_for_labels for box in p.get("boxes", []) if isinstance(box, dict) and "label" in box})


# Build pages_for_boxes (used for parsed_json_ocr overlay and static drawing)
if isinstance(parsed_json_ocr, dict) and "pages" in parsed_json_ocr:
    pages_for_boxes = parsed_json_ocr["pages"]
elif isinstance(parsed_json_ocr, list):
    if parsed_json_ocr and isinstance(parsed_json_ocr[0], dict) and "boxes" in parsed_json_ocr[0]:
        pages_for_boxes = parsed_json_ocr
    elif parsed_json_ocr and isinstance(parsed_json_ocr[0], dict) and "bbox" in parsed_json_ocr[0]:
        pages_for_boxes = [{"page": 0, "boxes": parsed_json_ocr}]
    else:
        pages_for_boxes = []
else:
    pages_for_boxes = []

# Normalize ocr_blocks into a list of page dicts called `ocr_pages`
if ocr_blocks is None:
    st.sidebar.info("No 'ocr_blocks' present in JSON — skipping OCR blocks overlay.")
    ocr_pages = []
else:
    if isinstance(ocr_blocks, dict) and "pages" in ocr_blocks:
        ocr_pages = ocr_blocks["pages"]
    elif isinstance(ocr_blocks, list):
        # Distinguish between: (A) list of pages (each page is a dict with 'page'/'blocks')
        # and (B) flat list of blocks (each block has 'bbox'/'text').
        if ocr_blocks and isinstance(ocr_blocks[0], dict) and "bbox" in ocr_blocks[0]:
            # Treat as a single page (page 0) containing these blocks
            ocr_pages = [{"page": 0, "blocks": ocr_blocks}]
        else:
            # Assume it's already a list of page dicts
            ocr_pages = ocr_blocks
    else:
        st.error("Unrecognized structure for 'ocr_blocks'. Expected dict with 'pages', a list of pages, or a flat list of blocks.")
        ocr_pages = []

# Collect blocks for page 0 into overlay_blocks
overlay_blocks = []
for page_obj in ocr_pages:
    if not isinstance(page_obj, dict):
        continue
    if page_obj.get("page") != 0:
        continue
    for block in page_obj.get("blocks", []):
        bbox = block.get("bbox")
        text = block.get("text", "")
        conf = block.get("confidence")
        if not bbox or len(bbox) < 4:
            continue
        overlay_blocks.append({"bbox": bbox[:4], "text": text, "confidence": conf})

# Interactive overlay UI
interactive = st.sidebar.checkbox("Use interactive OCR overlay (hover to enlarge)", value=True)

# Option to include parsed_json_ocr overlay (labels / boxes)
include_parsed_overlay = st.sidebar.checkbox("Include parsed_json_ocr overlay (labels)", value=True)

if interactive and overlay_blocks:
    # Prepare base64 image for HTML overlay
    img_for_overlay = Image.open(img_path).convert("RGB")
    buffered = io.BytesIO()
    img_for_overlay.save(buffered, format="PNG")
    img_b64 = base64.b64encode(buffered.getvalue()).decode()
    img_w, img_h = img_for_overlay.size

    boxes_html = []
    boxes_html_parsed = []
    # Add OCR blocks first (with zoom thumbnails)
    for idx, b in enumerate(overlay_blocks):
        x1, y1, x2, y2 = b["bbox"]
        left = (x1 / img_w) * 100
        top = (y1 / img_h) * 100
        width = ((x2 - x1) / img_w) * 100
        height = ((y2 - y1) / img_h) * 100
        conf = b.get("confidence")
        try:
            conff = float(conf)
        except Exception:
            conff = None
        if conff is None:
            color = 'blue'
        else:
            if conff >= 0.99:
                color = 'green'
            elif conff >= 0.98:
                color = 'lime'
            elif conff >= 0.95:
                color = 'orange'
            else:
                color = 'red'

        label = (b.get("text") or "").replace('\n', ' ').replace('"', '&quot;')
        label_display = f"{label} ({conff:.2f})" if conff is not None else label

        # create zoom thumbnail for this bbox
        crop = img_for_overlay.crop((int(x1), int(y1), int(x2), int(y2)))
        # resize thumbnail to width 240px while keeping aspect
        try:
            w, h = crop.size
            if w > 0 and h > 0:
                thumb_w = 240
                thumb_h = int((thumb_w / w) * h)
                crop_thumb = crop.resize((thumb_w, max(1, thumb_h)))
                buf = io.BytesIO()
                crop_thumb.save(buf, format="PNG")
                thumb_b64 = base64.b64encode(buf.getvalue()).decode()
                thumb_img_tag = f'<img class="zoom" src="data:image/png;base64,{thumb_b64}" />'
            else:
                thumb_img_tag = ''
        except Exception:
            thumb_img_tag = ''

        box_div = f'''<div class="box" style="left:{left:.4f}%; top:{top:.4f}%; width:{width:.4f}%; height:{height:.4f}%; border-color:{color};" data-label="{label_display}">{thumb_img_tag}</div>'''
        boxes_html.append(box_div)

        
    # Optionally add parsed_json_ocr boxes (labels) with zooms into boxes as well
    if include_parsed_overlay and pages_for_boxes:
        for pidx, p in enumerate(pages_for_boxes):
            if not isinstance(p, dict):
                continue
            if p.get("page") != 0:
                continue
            for box in p.get("boxes", []):
                bb = box.get("bbox")
                if not bb or len(bb) < 4:
                    continue
                x1, y1, x2, y2 = bb[:4]
                left = (x1 / img_w) * 100
                top = (y1 / img_h) * 100
                width = ((x2 - x1) / img_w) * 100
                height = ((y2 - y1) / img_h) * 100
                label = (box.get("label") or "").replace('\n', ' ').replace('"', '&quot;')
                label_display = label
                color = 'purple'

                # create zoom thumbnail for parsed box
                try:
                    crop = img_for_overlay.crop((int(x1), int(y1), int(x2), int(y2)))
                    w, h = crop.size
                    if w > 0 and h > 0:
                        thumb_w = 240
                        thumb_h = int((thumb_w / w) * h)
                        crop_thumb = crop.resize((thumb_w, max(1, thumb_h)))
                        buf = io.BytesIO()
                        crop_thumb.save(buf, format="PNG")
                        thumb_b64 = base64.b64encode(buf.getvalue()).decode()
                        thumb_img_tag = f'<img class="zoom" src="data:image/png;base64,{thumb_b64}" />'
                    else:
                        thumb_img_tag = ''
                except Exception:
                    thumb_img_tag = ''

                box_div = f'''<div class="box parsed" style="left:{left:.4f}%; top:{top:.4f}%; width:{width:.4f}%; height:{height:.4f}%; border-color:{color};" data-label="{label_display}">{thumb_img_tag}</div>'''
                boxes_html_parsed.append(box_div)

    # Build two separate HTML overlays: one for OCR blocks, one for parsed labels
    css = """
    <style>
    .overlay-container { position: relative; display: inline-block; max-width: 100%; }
    .overlay-container img { display:block; max-width: 100%; height: auto; }
    /* default stacking: keep boxes below hovered content */
    .box { position: absolute; box-sizing: border-box; border: 2px solid blue; pointer-events: auto; z-index: 5; }
    .box.parsed { border-style: dashed; }
    /* label pseudo-element (slightly above box by default) */
    .box::after { content: attr(data-label); position: absolute; left: 0; top: -1.9em; white-space: nowrap; background: rgba(255,255,255,0.9); padding: 2px 6px; font-size: 12px; color: #000; transform-origin: left top; transition: transform 0.12s ease, background 0.12s ease; backdrop-filter: blur(0px); -webkit-backdrop-filter: blur(0px); z-index: 10; }
    /* thumbnail image that appears on hover; positioned to the right of the box by default */
    .box .zoom { display:none; position: absolute; left: 000%; top: 100%; margin-left: 8px; border: 2px solid #333; box-shadow: 0 4px 12px rgba(0,0,0,0.35); max-width: 320px; z-index: 20; }
    /* When hovered, raise the whole .box stacking context so its children (label + zoom) appear above other boxes */
    .box:hover { z-index: 2000; }
    .box:hover::after { transform: scale(1.8); z-index: 2010; background: rgba(255,255,255,1.00); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(6px); font-weight: 700; font-size: 16px; padding: 4px 8px; }
    .box:hover .zoom { display: block; z-index: 2020; }
    </style>
    """

    html_ocr = f"""
    {css}
    <div class="overlay-container">
        <img src="data:image/png;base64,{img_b64}" />
        {''.join(boxes_html)}
    </div>
    """

    html_parsed = f"""
    {css}
    <div class="overlay-container">
        <img src="data:image/png;base64,{img_b64}" />
        {''.join(boxes_html_parsed)}
    </div>
    """

    # Render stacked (one below the other) so the original image remains easy to view
    st.markdown("**OCR blocks (text + confidence)**")
    components.html(html_ocr, height=img_h * 1.12)
    st.markdown("---")
    st.markdown("**Parsed labels (parsed_json_ocr)**")
    components.html(html_parsed, height=img_h * 1.12)
else:
    # Fallback: draw boxes on the PIL image and show it
    img_fallback = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img_fallback)
    for b in overlay_blocks:
        x1, y1, x2, y2 = b["bbox"]
        conf = b.get("confidence")
        try:
            conff = float(conf)
        except Exception:
            conff = None
        if conff is None:
            color = "blue"
        else:
            if conff >= 0.99:
                color = "green"
            elif conff >= 0.98:
                color = "lime"
            elif conff >= 0.95:
                color = "orange"
            else:
                color = "red"
        text = b.get("text", "")
        label_text = text if conff is None else f"{text} ({conff:.2f})"
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        draw.text((x1 + 2, y1 + 2), label_text[:120], fill=color)
    st.image(img_fallback, caption="Page 0 with OCR blocks", use_container_width=True)

