from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd
import streamlit as st
from pypdf import PdfReader

FIELDS = [
    "delivery_note_no",
    "delivery_weight",
    "unit_name",
    "address_1",
    "address_2",
    "city",
    "postcode",
    "attn",
    "parcels",
    "booking_in_tel",
    "email_address",
]

MAX_LEN = 35
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}|GIR\s?0AA)\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
TEL_RE = re.compile(r"(?:Booking in Tel\s*:?\s*)([0-9][0-9\s()+-]{6,}[0-9])", re.IGNORECASE)
PARCELS_RE = re.compile(r"\bParcels\s*:?\s*(\d+)\b", re.IGNORECASE)
NOTE_RE = re.compile(r"\bDelivery Note No\s*:?\s*([A-Z0-9]+)\b", re.IGNORECASE)
WEIGHT_LABEL_RE = re.compile(r"\b(?:Delivery Weight|Weight)\s*:?\s*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)


@dataclass
class DeliveryRecord:
    delivery_note_no: str = ""
    delivery_weight: str = ""
    unit_name: str = ""
    address_1: str = ""
    address_2: str = ""
    city: str = ""
    postcode: str = ""
    attn: str = ""
    parcels: str = ""
    booking_in_tel: str = ""
    email_address: str = ""
    source_file: str = ""
    parse_error: str = ""


def clean_text(value: str | None, default: str = "") -> str:
    text = (value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        text = default
    return text[:MAX_LEN]


def clean_lines(text: str) -> List[str]:
    lines: List[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def extract_pdf_text(uploaded_file) -> str:
    reader = PdfReader(uploaded_file)
    parts: List[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts)


def find_value_after_label(lines: List[str], label: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:?(.*)$", re.IGNORECASE)
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        inline = m.group(1).strip()
        if inline:
            return inline
        if i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""


def extract_delivery_weight(lines: List[str], text: str) -> str:
    m = WEIGHT_LABEL_RE.search(text)
    if m:
        return m.group(1).strip()

    for i, line in enumerate(lines):
        if line.lower().startswith("parcels") and i > 0:
            candidate = lines[i - 1].strip()
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", candidate):
                return candidate

    m = re.search(r"\n\s*([0-9]+(?:\.[0-9]+)?)\s*\n\s*Parcels\s*:", text, re.IGNORECASE)
    if m:
        return m.group(1)

    return ""


def extract_delivery_address_block(lines: List[str]) -> tuple[str, List[str]]:
    start_idx = None
    for i, line in enumerate(lines):
        if line.lower().startswith("delivery address"):
            start_idx = i
            break
    if start_idx is None:
        return "", []

    skip_label_prefixes = (
        "delivery note no",
        "delivery date",
        "sales order no",
        "customer order no",
        "account no",
    )
    stop_prefixes = (
        "attn:",
        "carrier:",
        "parcels:",
        "booking in tel",
        "email address",
        "special instructions",
        "description",
    )

    block: List[str] = []
    i = start_idx + 1
    while i < len(lines):
        line = lines[i]
        lower = line.lower()
        if lower.startswith(stop_prefixes):
            break
        if lower.startswith(skip_label_prefixes):
            i += 2 if i + 1 < len(lines) else 1
            continue
        block.append(line)
        i += 1

    if not block:
        return "", []

    unit_name = block[0].strip()
    return unit_name, block[1:]


def split_address_lines(address_lines: List[str]) -> tuple[str, str, str, str]:
    if not address_lines:
        return "", "", "", ""

    postcode = ""
    postcode_idx = None
    for idx in range(len(address_lines) - 1, -1, -1):
        match = POSTCODE_RE.search(address_lines[idx])
        if match:
            postcode = match.group(1).upper().replace("  ", " ")
            postcode_idx = idx
            break

    usable = address_lines[:] if postcode_idx is None else address_lines[:postcode_idx]
    usable = [x for x in usable if x]
    if not usable:
        return "", "", "", postcode

    if len(usable) == 1:
        return usable[0], "", "", postcode
    if len(usable) == 2:
        return usable[0], usable[1], "", postcode

    address_1 = usable[0]
    city = usable[-1]
    middle = usable[1:-1]
    address_2 = ", ".join(middle)
    return address_1, address_2, city, postcode


def parse_delivery_note_from_uploaded_file(uploaded_file) -> DeliveryRecord:
    record = DeliveryRecord(source_file=uploaded_file.name)
    try:
        text = extract_pdf_text(uploaded_file)
        lines = clean_lines(text)

        note_match = NOTE_RE.search(text)
        if note_match:
            record.delivery_note_no = note_match.group(1).strip()
        else:
            record.delivery_note_no = find_value_after_label(lines, "Delivery Note No")

        record.delivery_weight = extract_delivery_weight(lines, text)
        record.attn = find_value_after_label(lines, "Attn")
        record.parcels = find_value_after_label(lines, "Parcels")
        if not record.parcels:
            m = PARCELS_RE.search(text)
            if m:
                record.parcels = m.group(1).strip()

        email = EMAIL_RE.search(text)
        if email:
            record.email_address = email.group(0).strip()

        tel = TEL_RE.search(text)
        if tel:
            record.booking_in_tel = re.sub(r"\s+", " ", tel.group(1).strip())

        unit_name, address_lines = extract_delivery_address_block(lines)
        record.unit_name = unit_name
        record.address_1, record.address_2, record.city, record.postcode = split_address_lines(address_lines)

        record.delivery_note_no = clean_text(record.delivery_note_no)
        record.delivery_weight = clean_text(record.delivery_weight)
        record.unit_name = clean_text(record.unit_name)
        record.address_1 = clean_text(record.address_1)
        record.address_2 = clean_text(record.address_2)
        record.city = clean_text(record.city)
        record.postcode = clean_text(record.postcode)
        record.attn = clean_text(record.attn, default="Goods In")
        record.parcels = clean_text(record.parcels)
        record.booking_in_tel = clean_text(record.booking_in_tel)
        record.email_address = clean_text(record.email_address)

        return record
    except Exception as exc:
        record.parse_error = f"{type(exc).__name__}: {exc}"
        return record


def to_dataframe(records: List[DeliveryRecord]) -> pd.DataFrame:
    return pd.DataFrame([{field: getattr(r, field, "") for field in FIELDS} for r in records], columns=FIELDS)


st.set_page_config(page_title="DPD Delivery Note Extractor", layout="wide")

st.title("DPD Delivery Note Extractor")
st.caption("Upload one or more delivery note PDFs, preview the extracted data, and download one CSV file.")

uploaded_files = st.file_uploader(
    "Choose PDF delivery notes",
    type=["pdf"],
    accept_multiple_files=True,
)

col1, col2 = st.columns([1, 1])
with col1:
    output_name = st.text_input("Output CSV filename", value="dpd_delivery_notes.csv")
with col2:
    st.write("")
    st.write("")
    process_button = st.button("Extract and build CSV", type="primary", use_container_width=True)

if "records" not in st.session_state:
    st.session_state.records = []

if process_button:
    if not uploaded_files:
        st.warning("Please upload at least one PDF.")
    else:
        records = [parse_delivery_note_from_uploaded_file(f) for f in uploaded_files]
        st.session_state.records = records

        errors = [r for r in records if r.parse_error]
        if errors:
            st.warning(
                "Some files were processed with warnings. The CSV still downloads, but check the rows below."
            )

        df = to_dataframe(records)
        st.success(f"Processed {len(df)} file(s).")
        st.dataframe(df, use_container_width=True)

        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_bytes = csv_buffer.getvalue().encode("utf-8-sig")

        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name=output_name if output_name.lower().endswith(".csv") else f"{output_name}.csv",
            mime="text/csv",
            use_container_width=True,
        )

if st.session_state.records:
    st.subheader("Latest preview")
    st.dataframe(to_dataframe(st.session_state.records), use_container_width=True)
