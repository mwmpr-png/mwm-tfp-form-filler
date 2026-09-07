from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from . import extractor as base_extractor
from .compliance_rules import enrich_case


def _clean(value: Any) -> str:
    return base_extractor.clean(value)


def _human_name(value: str) -> str:
    value = _clean(value)
    value = re.sub(r"\s+", " ", value).strip(" -:,.|/")
    return value.title() if value.isupper() else value


def extract_hsbc_policy_illustration(text: str) -> dict[str, str]:
    """Extract HSBC Policy Illustration facts using the actual HSBC page layout.

    HSBC Policy Illustrations use a different text order from the other insurer
    BIs.  Generic ``Plan:`` / ``Currency:`` patterns can therefore capture
    punctuation or nearby labels instead of the real values.  These patterns are
    deliberately anchored to the HSBC Policyholder and Plan Details block.
    """
    txt = _clean(text)
    if not txt or not re.search(r"\bHSBC Life\b", txt, flags=re.I):
        return {}

    out: dict[str, str] = {}

    # Typical HSBC text extraction order:
    # Prepared for / Applicant / <client> / <representative> / Representative
    m = re.search(
        r"Prepared\s+for\s*\n\s*Applicant\s*\n\s*([^\n]{2,90})\s*\n\s*([^\n]{2,90})\s*\n\s*Representative\b",
        txt,
        flags=re.I,
    )
    if m:
        out["client_name"] = _human_name(m.group(1))
        out["adviser_name_from_bi"] = _human_name(m.group(2))

    # Policyholder and Plan Details block. This is the strongest source for
    # proposed life, age, sex, plan and policy currency.
    m = re.search(
        r"Policyholder and Plan Details[\s\S]{0,700}?"
        r"Proposed Life Insured[\s\S]{0,220}?"
        r"Age Last Birthday[\s\S]{0,100}?Sex[\s\S]{0,100}?Plan"
        r"[\s\S]{0,220}?\n\s*([A-Za-z][A-Za-z .,'()/-]{2,90})\s*"
        r"\n\s*(\d{1,3})\s*"
        r"\n\s*(Male|Female)\s*"
        r"\n\s*(HSBC Life[^\n]{2,120})\s*"
        r"\n\s*([A-Z]{3})\b",
        txt,
        flags=re.I,
    )
    if m:
        out["client_name"] = _human_name(m.group(1))
        out["age_last_birthday"] = m.group(2)
        out["gender"] = m.group(3).title()
        out["plan_name"] = _clean(m.group(4))
        out["currency"] = m.group(5).upper()

    # Exact current product variant supplied in the HSBC BI.
    if re.search(r"HSBC Life Indexed Flexi Income", txt, flags=re.I):
        out["plan_name"] = "HSBC Life Indexed Flexi Income"
        out["product_structure"] = "Universal Life Plan"
        out["insurer_name"] = "HSBC Life"
        out.setdefault("currency", "USD")

    # Single premium appears directly above the Basic Plan headers in this BI.
    m = re.search(
        r"\b([0-9]{1,3}(?:,[0-9]{3})+(?:\.\d+)?)\s*\n\s*Single Premium\s*\n\s*Basic Plan\b",
        txt,
        flags=re.I,
    )
    if m:
        out["premium"] = m.group(1)
        out["premium_frequency"] = "Single Premium"
        out["premium_mode"] = "single"

    m = re.search(r"Smoker/Non-smoker[\s:\n]*(Non-Smoker|Smoker)\b", txt, flags=re.I)
    if m:
        out["smoker"] = "No" if "non" in m.group(1).lower() else "Yes"

    m = re.search(
        r"Sum Insured\s*\(US\$\)[\s\S]{0,100}?\n\s*(Not Applicable|[0-9,]+(?:\.\d+)?)",
        txt,
        flags=re.I,
    )
    if m:
        out["sum_assured"] = _clean(m.group(1))

    if (
        re.search(r"\bPremium\s*\(US\$\)\s*\n\s*Whole Life\b", txt, flags=re.I)
        or re.search(r"whole life non-participating universal life", txt, flags=re.I)
    ):
        out["policy_term"] = "Whole Life"

    # Repeated footer fallback if the top-of-page representative extraction ever
    # changes in a later HSBC BI template.
    if not out.get("adviser_name_from_bi"):
        m = re.search(
            r"Presented\s+by\s*\n(?:Date\s*\n)?\s*:?\s*\n?\s*([A-Za-z][A-Za-z .,'()/-]{2,90})\s*\n\s*\d{1,2}/\d{1,2}/\d{4}",
            txt,
            flags=re.I,
        )
        if m:
            out["adviser_name_from_bi"] = _human_name(m.group(1))

    return {k: _clean(v) for k, v in out.items() if _clean(v)}


def _parse_vision_json(content: str) -> dict[str, str]:
    try:
        m = re.search(r"\{.*\}", content or "", flags=re.S)
        obj = json.loads(m.group(0) if m else content)
    except Exception:
        return {}
    out = {k: _clean(v) for k, v in obj.items() if _clean(v)}
    if out.get("nric"):
        out["nric"] = base_extractor.normalise_nric_from_text(out["nric"])
    if out.get("dob"):
        out["dob"] = base_extractor.parse_date_ddmmyyyy(out["dob"])
    if out.get("nationality"):
        out["nationality"] = base_extractor.normalise_nationality(out["nationality"], out.get("nric", ""))
    return {k: v for k, v in out.items() if v}


def _vision_extract_id_fallback(path: Path) -> dict[str, str]:
    """Retry ID vision with a dedicated vision model instead of OPENAI_MODEL.

    ``OPENAI_MODEL`` may be configured for a text/extraction task and is not a
    safe assumption for image input.  ``OPENAI_VISION_MODEL`` remains the
    explicit override; known multimodal models are tried as fallbacks.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not path:
        return {}

    mime, b64 = base_extractor.render_first_page_image(path)
    if not b64:
        return {}

    try:
        from openai import OpenAI
    except Exception:
        return {}

    configured = _clean(os.getenv("OPENAI_VISION_MODEL"))
    candidates = [configured] if configured else []
    candidates.extend(["gpt-4o-mini", "gpt-4.1-mini"])
    candidates = list(dict.fromkeys(model for model in candidates if model))

    prompt = (
        "Extract the visible details from this Singapore NRIC/ID/passport image. "
        "Return only JSON with these keys when visible: client_name, nric, dob, gender, "
        "nationality, birthplace, residential_address, postal. Use exact document text. "
        "For dob use DD/MM/YYYY. Do not guess unreadable details."
    )

    client = OpenAI(api_key=api_key)
    for model in candidates:
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=600,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        ],
                    }
                ],
            )
            parsed = _parse_vision_json(resp.choices[0].message.content or "{}")
            if parsed:
                return parsed
        except Exception:
            continue
    return {}


def _extract_id_robust(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    parsed = base_extractor.extract_id_document(path)
    required = {"nric", "dob", "residential_address", "postal", "nationality"}
    if not required.issubset({k for k, v in parsed.items() if _clean(v)}):
        retry = _vision_extract_id_fallback(path)
        for key, value in retry.items():
            if value and not _clean(parsed.get(key)):
                parsed[key] = value
    return {k: _clean(v) for k, v in parsed.items() if _clean(v)}


def _clear_suspicious_hsbc_address(data: dict[str, Any]) -> None:
    address = _clean(data.get("residential_address"))
    postal = _clean(data.get("postal"))
    blob = address.lower()
    suspicious = (
        len(address) > 180
        or "guaranteed interest rate lock" in blob
        or "holding segment" in blob
        or "index segment" in blob
        or "10 marina boulevard" in blob
        or (postal == "018983" and "marina" in blob)
    )
    if suspicious:
        data.pop("residential_address", None)
        data.pop("postal", None)


def _hsbc_page13_overrides(data: dict[str, Any]) -> None:
    if _clean(data.get("plan_name")).lower() != "hsbc life indexed flexi income":
        return

    page13 = dict(data.get("page13") or {})
    page13["features"] = (
        "A whole-life non-participating universal life insurance plan denominated in USD, with death, "
        "accidental death and terminal illness coverage. Policy value is allocated between the General "
        "Account and Index Account. Refer to the HSBC Benefit Illustration/Product Summary for exact benefits and terms."
    )
    page13["limitations"] = (
        "Crediting rates and index-account returns may be non-guaranteed subject to stated minimum/floor rates. "
        "Policy value can be affected by charges, withdrawals and index performance. Early surrender may return "
        "less than total premiums paid."
    )
    page13["investment_risk"] = (
        "Crediting-rate / index-performance risk, insurance/expense risk, liquidity/early-surrender risk and USD currency risk."
    )
    page13["other_limitations"] = (
        "The policy may lapse if policy value is insufficient to meet charges, and additional premiums may be required "
        "to keep it in force. Actual benefits depend on applicable crediting rates, charges, withdrawals and other policy transactions."
    )
    data["page13"] = page13

    age = _clean(data.get("age_next") or data.get("age_last_birthday"))
    objective = _clean(page13.get("objective"))
    premium = base_extractor.money_number(data.get("premium"))
    amount = base_extractor.fmt_money(premium) if premium else ""

    paragraphs: list[str] = []
    if objective:
        paragraphs.append(f"Client{' (ANB ' + age + ')' if age else ''} stated the following objective: {objective.rstrip(' .;:')}.")
    intro = "HSBC Life Indexed Flexi Income is recommended"
    if objective:
        intro += " for the stated objective."
    else:
        intro = "Client is considering HSBC Life Indexed Flexi Income."
    if amount:
        intro += f" The proposed single premium is ${amount}."
    intro += (
        " This is a whole-life non-participating universal life insurance plan denominated in USD. "
        "Policy value is allocated between the General Account and Index Account, and benefits include death, "
        "accidental death and terminal illness coverage subject to the policy terms."
    )
    paragraphs.append(intro)
    paragraphs.append(
        "Crediting rates and index-account returns may be non-guaranteed subject to stated minimum/floor rates. "
        "Policy value may be affected by charges, withdrawals and index performance. Early surrender may result "
        "in a value lower than total premiums paid."
    )
    paragraphs.append(
        "Refer to the HSBC Product Summary and Policy Illustration for the exact fees, charges, surrender terms, "
        "benefits and non-guaranteed elements."
    )
    if objective:
        strategy = "retirement strategy" if "retirement" in objective.lower() else "overall financial strategy"
        paragraphs.append(f"This recommendation forms part of the client's {strategy}.")
    data["recommendation_text"] = "\n\n".join(paragraphs)


def build_case(
    paths: list[Path],
    adviser_email: str,
    product_type: str,
    expected_retirement_income: str = "",
) -> dict[str, Any]:
    """Run the existing extractor, then apply HSBC-specific source-safe fixes."""
    data = base_extractor.build_case(paths, adviser_email, product_type, expected_retirement_income)
    if _clean(product_type).lower() != "hsbc":
        return data

    # Never retain a long insurer/glossary match as the client's home address.
    _clear_suspicious_hsbc_address(data)

    # BI is the second compulsory upload in the current UI.  Fall back to the
    # first HSBC-looking PDF if ordering changes later.
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

    hsbc = extract_hsbc_policy_illustration(bi_text)
    for key, value in hsbc.items():
        if not value:
            continue
        if key == "adviser_name_from_bi":
            data["adviser_name_from_bi"] = value
            data["adviser_name"] = value
        else:
            data[key] = value

    # The compulsory first upload is the client's ID. Personal particulars from
    # that document outrank any similarly named text elsewhere in the BI bundle.
    id_data = _extract_id_robust(paths[0] if paths else None)
    for key, value in id_data.items():
        if not value:
            continue
        if key in {"nric", "dob", "gender", "nationality", "birthplace", "residential_address", "postal"}:
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

    # Re-run deterministic compliance enrichment now that the correct HSBC BI
    # facts (including the single premium) are available.
    source_text, fields = base_extractor.all_text_and_fields(paths)
    data["product_type"] = product_type
    data["expected_retirement_income"] = expected_retirement_income
    data = enrich_case(data, product_type, source_text=source_text, fields=fields)
    data["raw_field_count"] = len(fields)

    # The HSBC Product Illustration supports richer Page-13/Page-14 wording than
    # the generic HSBC fallback without inventing client-specific suitability facts.
    _hsbc_page13_overrides(data)
    return data
