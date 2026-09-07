from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .extractor import build_case as _original_build_case
from . import extractor as base_extractor
from .compliance_rules import enrich_case
from .hsbc_support import (
    _clean,
    _clear_suspicious_hsbc_address,
    _extract_id_robust,
    _hsbc_page13_overrides,
    extract_hsbc_policy_illustration,
)


def build_case(
    paths: list[Path],
    adviser_email: str,
    product_type: str,
    expected_retirement_income: str = "",
) -> dict[str, Any]:
    """Use the existing production extractor, then safely correct HSBC cases.

    Non-HSBC cases return the existing production result unchanged. The original
    build_case function is captured at import time so package-level wiring cannot
    recurse back into this wrapper.
    """
    data = _original_build_case(paths, adviser_email, product_type, expected_retirement_income)
    if _clean(product_type).lower() != "hsbc":
        return data

    # Remove only clearly contaminated insurer/glossary address matches. The
    # client ID is then given authority over personal particulars below.
    _clear_suspicious_hsbc_address(data)

    # Current UI order is NRIC/ID first, BI second. If a later UI changes the
    # ordering, fall back to the first subsequent HSBC PDF.
    bi_text = ""
    if len(paths) > 1 and paths[1] and paths[1].suffix.lower() == ".pdf":
        bi_text = base_extractor.pdf_text(paths[1])
    if not re.search(r"\bHSBC Life\b", bi_text, flags=re.I):
        for path in paths[1:]:
            if path and path.suffix.lower() == ".pdf":
                candidate = base_extractor.pdf_text(path)
                if re.search(r"\bHSBC Life\b", candidate, flags=re.I):
                    bi_text = candidate
                    break

    # HSBC BI is authoritative for adviser/product/premium/policy facts.
    hsbc = extract_hsbc_policy_illustration(bi_text)
    for key, value in hsbc.items():
        if not value:
            continue
        if key == "adviser_name_from_bi":
            data["adviser_name_from_bi"] = value
            data["adviser_name"] = value
        else:
            data[key] = value

    # Client ID is authoritative for personal particulars. Do not allow policy
    # wording, insurer office addresses or glossary text to overwrite these.
    id_data = _extract_id_robust(paths[0] if paths else None)
    for key, value in id_data.items():
        if not value:
            continue
        if key in {
            "nric", "dob", "gender", "nationality", "birthplace",
            "residential_address", "postal",
        }:
            data[key] = value
        elif key == "client_name" and not _clean(data.get("client_name")):
            data[key] = value

    if data.get("dob"):
        data["dob"] = base_extractor.parse_date_ddmmyyyy(data["dob"])
    if data.get("age_last_birthday"):
        try:
            data["age_next"] = str(int(data["age_last_birthday"]) + 1)
        except Exception:
            pass
    elif data.get("dob"):
        data["age_next"] = base_extractor.age_next_birthday(data["dob"])

    if data.get("residential_address"):
        address, postal = base_extractor.normalise_address_and_postal(
            data.get("residential_address"), data.get("postal")
        )
        data["residential_address"] = address
        if postal:
            data["postal"] = postal

    # Re-run deterministic compliance enrichment only after the correct HSBC BI
    # premium/product facts are present. Missing client facts remain missing.
    source_text, fields = base_extractor.all_text_and_fields(paths)
    data["product_type"] = product_type
    data["expected_retirement_income"] = expected_retirement_income
    data = enrich_case(data, product_type, source_text=source_text, fields=fields)
    data["raw_field_count"] = len(fields)

    # Use only product wording supported by the uploaded HSBC BI/Product Summary.
    _hsbc_page13_overrides(data)
    return data
