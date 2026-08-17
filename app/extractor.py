from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import fitz
from pypdf import PdfReader


def clean(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).replace("\x00", " ").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def norm_money(s: Any) -> str:
    s = clean(s)
    if not s:
        return ""
    s = s.replace("S$", "").replace("$", "").replace(" ", "")
    if re.fullmatch(r"\d+(?:\.\d+)?[kK]", s):
        return str(int(float(s[:-1]) * 1000))
    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:mil|million)", s, flags=re.I):
        return str(int(float(re.sub(r"(?i)(mil|million)", "", s)) * 1_000_000))
    return s


def money_number(s: Any) -> float:
    s = clean(s).lower().replace("s$", "").replace("$", "").replace(",", "").strip()
    if not s:
        return 0.0
    if s.endswith("k"):
        try: return float(s[:-1]) * 1000
        except: return 0.0
    if s.endswith("mil"):
        try: return float(s[:-3]) * 1_000_000
        except: return 0.0
    if "million" in s:
        try: return float(s.replace("million", "")) * 1_000_000
        except: return 0.0
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else 0.0


def fmt_money(n: float, compact: bool = False) -> str:
    try:
        n = float(n)
    except Exception:
        return ""
    if compact:
        if n >= 1_000_000 and n % 1_000_000 == 0:
            return f"{int(n/1_000_000)}MIL"
        if n >= 1000 and n % 1000 == 0:
            return f"{int(n/1000)}K"
    return f"{n:,.0f}"


def pdf_text(path: Path, max_pages: int | None = None) -> str:
    parts: list[str] = []
    try:
        doc = fitz.open(str(path))
        n = len(doc) if max_pages is None else min(max_pages, len(doc))
        for i in range(n):
            parts.append(doc[i].get_text("text"))
        doc.close()
    except Exception:
        pass
    return clean("\n".join(parts))


def pdf_fields(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        reader = PdfReader(str(path))
        for k, v in (reader.get_fields() or {}).items():
            val = v.get("/V")
            if val is not None and clean(val) not in ("", "/Off", "Off"):
                out[k] = clean(val).lstrip("/")
    except Exception:
        pass
    return out


def all_text_and_fields(paths: list[Path]) -> tuple[str, dict[str, str]]:
    texts = []
    merged_fields: dict[str, str] = {}
    for p in paths:
        fields = pdf_fields(p) if p.suffix.lower() == ".pdf" else {}
        if fields:
            merged_fields.update(fields)
            texts.append("\n".join(f"[FIELD] {k}: {v}" for k, v in fields.items()))
        if p.suffix.lower() == ".pdf":
            texts.append(pdf_text(p))
    return clean("\n\n".join(texts)), merged_fields


def find(pattern: str, text: str, flags: int = re.I | re.S, default: str = "") -> str:
    m = re.search(pattern, text, flags)
    return clean(m.group(1)) if m else default


def first_field(fields: dict[str, str], *names: str) -> str:
    for n in names:
        if n in fields and clean(fields[n]):
            return clean(fields[n])
    return ""


def title_name_from_email(email: str) -> str:
    name = email.split("@")[0].replace(".", " ").replace("_", " ").strip()
    return name.upper() if name else ""


def parse_date_ddmmyyyy(raw: str) -> str:
    raw = clean(raw)
    if not raw:
        return ""
    months = {"jan":"01","january":"01","feb":"02","february":"02","mar":"03","march":"03","apr":"04","april":"04","may":"05","jun":"06","june":"06","jul":"07","july":"07","aug":"08","august":"08","sep":"09","sept":"09","september":"09","oct":"10","october":"10","nov":"11","november":"11","dec":"12","december":"12"}
    m = re.search(r"(\d{1,2})[\-/\. ]+(\d{1,2})[\-/\. ]+(\d{2,4})", raw)
    if m:
        d, mo, y = m.groups(); y = ("20" + y) if len(y) == 2 and int(y) < 40 else (("19" + y) if len(y)==2 else y)
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw)
    if m:
        d, mo, y = m.groups(); mo = months.get(mo.lower(), mo)
        if mo.isdigit():
            return f"{int(d):02d}/{int(mo):02d}/{y}"
    return raw


def age_next_birthday(dob: str, ref: date | None = None) -> str:
    dob = parse_date_ddmmyyyy(dob)
    ref = ref or date.today()
    try:
        d, m, y = [int(x) for x in dob.split("/")]
        age = ref.year - y
        if (ref.month, ref.day) >= (m, d):
            age += 1
        return str(age)
    except Exception:
        return ""



def first_match(patterns: list[str], text: str, flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        value = find(pattern, text, flags=flags)
        if value:
            return value
    return ""


def compact_spaces(s: Any) -> str:
    return re.sub(r"\s+", " ", clean(s)).strip()


def tokio_fund_display_name(name: str) -> str:
    """Shorten Tokio Marine fund names for the relatively narrow TFP table cells."""
    name = compact_spaces(name)
    name = re.sub(r"\s*\([A-Z0-9]+\)\s*$", "", name)
    name = re.sub(r"\bFund\s+Dis\b", "", name, flags=re.I)
    name = re.sub(r"\bEq\s+Dis\b", "Equity", name, flags=re.I)
    name = re.sub(r"\bEquity\s+Dis\b", "Equity", name, flags=re.I)
    return compact_spaces(name)


def infer_asset_class(fund_name: str) -> str:
    s = compact_spaces(fund_name).lower()
    if any(k in s for k in ("equity", " equities", " eq ")):
        return "Equity"
    if any(k in s for k in ("bond", "fixed income", "income fund", "money market")):
        return "Fixed Income"
    if any(k in s for k in ("balanced", "multi-asset", "multi asset", "allocation")):
        return "Mixed"
    return ""


def _tokio_residential_address(text: str) -> tuple[str, str]:
    block = first_match([
        r"PERSONAL PARTICULARS OF PROPOSER[^\n]*.*?Residential Address\s*Address\s*(.+?)\s*Mailing Address",
        r"Residential Address\s*Address\s*(.+?)\s*Mailing Address",
    ], text)
    block = clean(block)
    postal = find(r"Singapore\s+(\d{6})", block or text)
    if block:
        block = re.sub(r"\bSingapore\s+\d{6}\b", "", block, flags=re.I)
        block = re.sub(r"\bSingapore\b", "", block, flags=re.I)
        block = compact_spaces(block)
        # Tokio's MyInfo output commonly omits the # before the unit number.
        block = re.sub(r"(?<!#)\b(\d{2}-\d{2,4})\b", r"#\1", block)
    return block, postal


def extract_tokio_marine(text: str, fields: dict[str, str]) -> dict[str, Any]:
    """Deterministic parser for Tokio Marine Singapore application / policy illustration PDFs."""
    out: dict[str, Any] = {}
    if not re.search(r"Tokio\s+Marine|Wealth\s+Flexi-Link", text, re.I):
        return out

    out["client_name"] = first_match([
        r"PERSONAL PARTICULARS OF PROPOSER[^\n]*[–-]\s*([^\n]+?)(?:\s*\(Retrieved|\s*$)",
        r"Particulars of Main Life Assured\s*/\s*Proposer\s*:\s*(?:Mr|Ms|Mdm|Mrs)?\.?\s*([^\n]+)",
        r"Main Life Assured\s*/\s*Proposer\s*:\s*([^\n]+?)\s+Age NB",
        r"Full Name\s*\n\s*([^\n]+)",
    ], text)
    out["client_name"] = re.sub(r"\s{2,}.*$", "", out.get("client_name", "")).strip()

    out["nric"] = first_match([
        r"NRIC\s*/\s*Passport No\.?(?:\d+)?\s*\n?\s*([STFGM]\d{7}[A-Z])",
        r"\b([STFGM]\d{7}[A-Z])\b",
    ], text)
    out["dob"] = first_match([
        r"Age Next Birthday\s*\n?\s*\d+\s*\n?\s*Date of Birth\s*\n?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
        r"Birthdate\s*:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
        r"Date of Birth\s*\n?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
    ], text)
    out["dob"] = parse_date_ddmmyyyy(out.get("dob", ""))
    out["age_next"] = first_match([
        r"Age Next Birthday\s*\n?\s*(\d{1,3})",
        r"Age NB\*\s*:\s*(\d{1,3})",
        r"Age NB\*\s*/\s*Smoker\?\s*:\s*(\d{1,3})",
    ], text)
    out["gender"] = first_match([
        r"Date of Birth\s*\n?\s*[0-9/]+\s*\n?\s*Gender\s*\n?\s*(Male|Female)",
        r"Sex\s*:\s*(Male|Female)",
        r"Gender\s*:\s*([FM])\b",
    ], text)
    if out.get("gender") == "F": out["gender"] = "Female"
    if out.get("gender") == "M": out["gender"] = "Male"
    smoker = first_match([r"Smoker\?\s*:\s*(Yes|No)", r"Age NB\*\s*/\s*Smoker\?\s*:\s*\d+\s*/\s*(Yes|No)"], text)
    if smoker: out["smoker"] = smoker
    out["nationality"] = first_match([
        r"Nationality\s*\n?\s*(Singapore|Singaporean|[A-Za-z][A-Za-z ]+?)\s*(?:Passport|Country of Birth)",
        r"Nationality\s*:\s*([^\n]+)",
    ], text)
    out["birthplace"] = first_match([r"Country of Birth\s*\n?\s*([^\n]+)", r"Country/Place of birth\s*\n?\s*([^\n]+)"], text)
    address, postal = _tokio_residential_address(text)
    if address: out["residential_address"] = address
    if postal: out["postal"] = postal
    out["mobile"] = first_match([r"Mobile No\.\s*\n?\s*\+?65\s+([0-9 ]{8,})", r"Mobile No\.\s*\+?65\s*([0-9]{8})"], text)
    out["mobile"] = re.sub(r"\D", "", out.get("mobile", ""))[-8:]
    out["client_email"] = first_match([r"Email Address\s*\n?\s*([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})"], text)
    out["occupation"] = first_match([
        r"PERSONAL PARTICULARS OF PROPOSER \(continued\).*?Employment Details\s*Occupation\s*\n?\s*([^\n]+)",
        r"Employment Details\s*Occupation\s*\n?\s*([^\n]+)\s*\n\s*Annual Income",
    ], text)
    out["annual_income"] = first_match([r"Annual Income\s*/\s*Allowance \(\$\)\s*\n?\s*([0-9,]+(?:\.\d+)?)"], text)
    out["employer"] = first_match([r"Name of Company\s*/\s*School\s*\n?\s*([^\n]+)"], text)

    out["adviser_name"] = first_match([
        r"Full Name of Adviser\s*\n?\s*([^\n]+)",
        r"Prepared by\s*:\s*([^\n(]+(?:\([^\n)]+\))?)\s*\(\s*\d+\s*\)",
    ], text)
    if out.get("adviser_name"):
        out["adviser_name_full"] = compact_spaces(out["adviser_name"])
        out["adviser_name"] = compact_spaces(re.sub(r"\s*\([^)]*\)\s*$", "", out["adviser_name"]))
    out["fa_source_code"] = first_match([r"Adviser Code\s*\n?\s*([A-Z0-9]+)", r"Prepared by\s*:[^\n]*\(\s*([A-Z0-9]+)\s*\)"], text)
    out["adviser_mobile"] = first_match([r"Contact No\. of Adviser\s*\n?\s*([0-9]{8})", r"Hp No\.\s*:\s*([0-9]{8})"], text)

    out["plan_name"] = first_match([
        r"Plan Name\s*\n?\s*([^\n]+)",
        r"^\s*(Wealth\s+Flexi-Link[^\n]*)\s*$",
        r"Basic Plan\s*:\s*([^\n]+)",
    ], text, flags=re.I | re.M)
    out["premium"] = first_match([
        r"Total Instalment Premium based on Cash mode\s*([0-9,]+(?:\.\d+)?)",
        r"Total Premium\s*\d*\s*\n?\s*([0-9,]+(?:\.\d+)?)",
        r"Basic Plan Name\s*Sum Assured / Benefit \(\$\)\s*Premium Amount \(\$\).*?\n\s*[^\n]+\s*\n\s*-\s*\n\s*([0-9,]+(?:\.\d+)?)",
    ], text)
    out["premium_frequency"] = first_match([r"Premium Payment Mode\s*\n\s*Premium Payment Mode\s*\n?\s*([^\n]+)"], text) or "Annual"
    out["currency"] = first_match([r"Policy Currency\s*\n?\s*([A-Z]{3})", r"Currency\s*:\s*([A-Z]{3})"], text) or "SGD"
    out["mip"] = first_match([
        r"Minimum Contribution/Investment Period\s*\n?\s*([^\n]+)",
        r"Minimum Investment\s*:\s*(\d+)\b",
    ], text)
    if out.get("mip") and re.fullmatch(r"\d+", out["mip"]): out["mip"] += " years"
    out["benefit_type"] = first_match([r"Death Benefit\s*\n?\s*(Enhanced|Basic)", r"Basic Benefit\s*/\s*:\s*([^\n^]+)"], text)
    out["policy_term"] = first_match([r"Wealth\s+Flexi-Link[^\n]*\n(?:\([^\n]+\)\n)?\s*(Life)\s+(?:Life|\d+)",], text) or ("Life" if re.search(r"Wealth\s+Flexi-Link", text, re.I) else "")
    existing_status = first_match([r"Do you have any existing policy\(ies\)\?.*?\n\s*(No|Yes)\b"], text)
    if existing_status:
        out["existing_policy_status"] = existing_status

    # Proposal / illustration date. Prefer the adviser-prepared date because it is the transaction document date.
    out["case_date"] = first_match([
        r"Prepared by\s*:[^\n]+\s+on\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
        r"Retrieved from MyInfo at\s+([0-9]{1,2}/[A-Za-z]{3}/[0-9]{4})",
    ], text)
    if out.get("case_date"):
        out["case_date"] = parse_date_ddmmyyyy(out["case_date"].replace("/", " ") if re.search(r"/[A-Za-z]{3}/", out["case_date"]) else out["case_date"])

    # Fund table appears in both the application and the BI. Capture up to seven rows.
    funds: list[dict[str, str]] = []
    block = first_match([
        r"INVESTMENT-LINKED FUND TYPES\s*Fund Name\s*Fund Allocation \(%\)\s*(.+?)\s*DIVIDEND DISTRIBUTION OPTION",
        r"Particulars of Fund Allocation\s*Fund Name\s*Fund Allocation\s*(.+?)\s*Total\s+100\s*%",
    ], text)
    if block:
        # Application format: name line followed by allocation line.
        lines = [compact_spaces(x) for x in block.splitlines() if compact_spaces(x)]
        i = 0
        while i < len(lines) and len(funds) < 7:
            line = re.sub(r"^\d+\.\s*", "", lines[i])
            m_same = re.match(r"(.+?)\s+(\d{1,3})\s*%?$", line)
            if m_same and not re.fullmatch(r"\d{1,3}", m_same.group(1).strip()):
                name, alloc = m_same.group(1), m_same.group(2)
                funds.append({"name": tokio_fund_display_name(name), "allocation": alloc, "asset_class": infer_asset_class(name)})
                i += 1
                continue
            if i + 1 < len(lines) and re.fullmatch(r"\d{1,3}\s*%?", lines[i+1]):
                alloc = re.sub(r"\D", "", lines[i+1])
                funds.append({"name": tokio_fund_display_name(line), "allocation": alloc, "asset_class": infer_asset_class(line)})
                i += 2
                continue
            i += 1
    # Regex fallback for Policy Illustration rows where extraction may be one line.
    if not funds:
        for m in re.finditer(r"(?:\d+\.\s*)?([^\n]+?(?:Equity|Eq)[^\n]*?)\s+(\d{1,3})\s*%", text, re.I):
            name, alloc = compact_spaces(m.group(1)), m.group(2)
            if "investment return" in name.lower():
                continue
            funds.append({"name": tokio_fund_display_name(name), "allocation": alloc, "asset_class": infer_asset_class(name)})
            if len(funds) >= 7: break
    premium_n = money_number(out.get("premium", ""))
    if funds:
        out["fund_count"] = str(len(funds))
        for idx, fund in enumerate(funds, 1):
            out[f"fund_{idx}_name"] = fund["name"]
            out[f"fund_{idx}_allocation"] = fund["allocation"]
            out[f"fund_{idx}_asset_class"] = fund["asset_class"]
            if premium_n and fund["allocation"].isdigit():
                out[f"fund_{idx}_amount"] = fmt_money(premium_n * int(fund["allocation"]) / 100.0)
        out["fund_name"] = funds[0]["name"]
        out["fund_allocation"] = funds[0]["allocation"]

    # If a prior / supporting TFP is uploaded under "other documents", use only explicit values from it.
    supporting = {
        "marital_status": ("Married", "Single", "Widowed", "Divorced"),
        "education": ("Highest Education Level",),
        "risk_profile": ("5 Clients Risk Profile", "S  L  JO"),
        "expected_return": ("6 Clients Expected Rate of Return",),
        "sales_charges": ("7 Sales Charges  WRAP  Platform Fee",),
        "investment_risk": ("8 The Nature of Product  Investment Risk",),
        "cashflow_expenses": ("Text25",),
        "cash_assets": ("Text127",),
        "investment_assets": ("Text123",),
        "cpf_total": ("Text125",),
        "total_assets": ("Text129",),
        "total_liabilities": ("Text135",),
        "net_assets": ("Text137",),
        "source_of_funds": ("Text152",),
    }
    # Checkbox marital status first.
    for status in ("Married", "Single", "Widowed", "Divorced"):
        if fields.get(status) and clean(fields.get(status)).lower() not in ("off", "/off"):
            out["marital_status"] = status
            break
    for key, names in supporting.items():
        if key == "marital_status":
            continue
        val = first_field(fields, *names)
        if val:
            out[key] = val
    if fields.get("FullTime") and clean(fields.get("FullTime")).lower() not in ("off", "/off"):
        out["employment_status"] = "Full-Time"
    if fields.get("yes1") and clean(fields.get("yes1")).lower() not in ("off", "/off"):
        out["english"] = "Yes"

    return {k: v for k, v in out.items() if v not in (None, "")}

def extract_from_bi(text: str, fields: dict[str, str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    data["client_name"] = clean(find(r"Specially prepared for\s*:\s*(?:Mr|Mdm|Ms|Mrs)?\s*([^\n]+?)\s+Date Generated", text) or first_field(fields, "Full Name", "Name of Proposer", "Clientname", "client_name"))
    data["plan_name"] = clean(find(r"Plan\s*:\s*([^\n]+)", text) or first_field(fields, "Plan Name", "1", "product_1", "Name of Products"))
    data["gender"] = clean(find(r"Plan\s*:\s*[^\n]+\n[^\n]*\b(Male|Female)\b", text) or first_field(fields, "Gender"))
    data["smoker"] = "No" if re.search(r"Non[- ]Smoker", text, re.I) else ""
    data["premium"] = clean(find(r"(?:Total Premium|Basic Premium)\s*:\s*\$?([0-9,]+(?:\.\d{2})?)", text) or first_field(fields, "undefined_19", "premiums_1", "Premium"))
    data["premium_frequency"] = clean(find(r"Premium Frequency\s*:\s*([^\n]+)", text))
    data["currency"] = clean(find(r"Currency\s*:\s*([A-Z]{3})", text)) or "SGD"
    data["mip"] = clean(find(r"Minimum Investment Period\s*:\s*([^\n]+)", text))
    data["benefit_type"] = clean(find(r"Benefit Type\s*:\s*([^\n]+)", text))
    data["age_last_birthday"] = clean(find(r"Age Last Birthday\s*:\s*(\d+)", text))
    data["policy_term"] = clean(find(r"Manulife InvestReady[^\n]*\s+(Up to age 99)\s+(\d+)\s+", text)) or "Up to 99 years"
    data["premium_term"] = clean(find(r"Manulife InvestReady[^\n]*Up to age 99\s+(\d+)\s+", text))
    # Common known FWD plan text fallback
    if re.search(r"FWD|Invest Flexi Elite", text, re.I) and not data.get("plan_name"):
        data["plan_name"] = "FWD Invest Flexi Elite"
    return {k: v for k, v in data.items() if v}


def extract_client(text: str, fields: dict[str, str], adviser_email: str = "", product_type: str = "") -> dict[str, Any]:
    data = extract_from_bi(text, fields)
    # Client details - prefer application/form fields, then generic text.
    data["client_name"] = first_field(fields, "Full Name", "Name of Proposer", "Clientname", "client_name", "Name") or data.get("client_name", "")
    data["nric"] = first_field(fields, "NRIC Passport", "NRIC / Passport", "NRIC Passport Number", "NRIC No", "NRIC", "nric") or find(r"\b([STFG]\d{7}[A-Z])\b", text)
    data["nationality"] = first_field(fields, "nationality", "undefined_2") or find(r"NATIONALITY\s*/\s*CITIZENSHIP\s*\n?([A-Z ]+)", text) or ("SINGAPORE CITIZEN" if re.search(r"Singaporean|SINGAPORE CITIZEN", text, re.I) else "")
    data["dob"] = first_field(fields, "date_of_birth", "Date of Birth  GG PPP", "DOB") or find(r"(?:DATE OF BIRTH|Date of Birth|DOB)\s*[:\n ]+([0-9]{1,2}[\-/ ][0-9A-Za-z]{1,9}[\-/ ][0-9]{2,4})", text)
    if not data.get("dob") and fields.get("Text11") and fields.get("Text12") and fields.get("Text13"):
        data["dob"] = f"{fields.get('Text11')}/{fields.get('Text12')}/{fields.get('Text13')}"
    data["dob"] = parse_date_ddmmyyyy(data.get("dob", ""))
    data["birthplace"] = first_field(fields, "birthplace", "Country of Birth", "undefined_4") or find(r"(?:PLACE OF BIRTH|Country of Birth)\s*[:\n ]+([A-Z ]+)", text)
    data["gender"] = data.get("gender") or ("Female" if re.search(r"\bFEMALE\b", text, re.I) else ("Male" if re.search(r"\bMALE\b", text, re.I) else ""))
    data["marital_status"] = "Widowed" if fields.get("Widowed") or fields.get("checkbox_widowed") else ("Married" if fields.get("Married") or fields.get("checkbox_married") else ("Single" if fields.get("Single") or fields.get("checkbox_single") else ""))
    data["residential_address"] = first_field(fields, "Residential Address", "residential_address", "is no residential address in the identification document 1") or find(r"ADDRESS\s*\n?(.+?SINGAPORE\s*\d{6})", text)
    data["postal"] = first_field(fields, "Postal Code", "postal") or find(r"SINGAPORE\s*(\d{6})", data.get("residential_address", "") or text)
    data["mobile"] = first_field(fields, "Mobile No", "Mobile Number", "mobile_number", "undefined_7")
    data["client_email"] = first_field(fields, "Email Address", "email", "undefined_8")
    data["occupation"] = first_field(fields, "Occupation", "occupation", "undefined_9")
    data["employer"] = first_field(fields, "Employer", "undefined_10")
    data["annual_income"] = first_field(fields, "Current Year S", "Annual Earned Income S", "annual_income")
    data["employment_status"] = "Retired" if fields.get("checkbox_retired") or fields.get("Retired") else ("Full-Time" if fields.get("FullTime") or fields.get("Full-Time") else "")
    data["source_of_income"] = first_field(fields, "income_source", "if retired  unemployed", "Source of Funds") or ("SAVINGS" if re.search(r"Savings", text, re.I) else "")
    data["education"] = first_field(fields, "highest_education_level", "Highest Education Level")
    data["english"] = "Yes" if fields.get("checkbox_english_yes") or fields.get("yes1") else ""
    if not data.get("age_next"):
        if data.get("age_last_birthday"):
            try: data["age_next"] = str(int(data["age_last_birthday"]) + 1)
            except: pass
        if not data.get("age_next") and data.get("dob"):
            data["age_next"] = age_next_birthday(data["dob"])
    data["adviser_email"] = adviser_email
    data["adviser_name"] = first_field(fields, "FAname", "fa_name", "Representatives Name 1", "namefa") or title_name_from_email(adviser_email)
    data["fa_source_code"] = first_field(fields, "sourcecode", "Representatives Code 1")
    # Fund allocation if found in Manulife application.
    data["fund_code"] = first_field(fields, "Fund CodeRow1")
    data["fund_name"] = first_field(fields, "Fund NameRow1", "fundmanager1", "Name of Fund Manager  Investment Product1")
    data["fund_allocation"] = first_field(fields, "Text115", "investamount1") or "100"
    # CPF balances
    oa = find(r"Ordinary Account \(OA\)\s*\$?([0-9,]+\.\d{2})", text)
    ma = find(r"MediSave Account \(MA\)\s*\$?([0-9,]+\.\d{2})", text)
    ra = find(r"Retirement Account \(RA\)\s*\$?([0-9,]+\.\d{2})", text)
    if oa or ma or ra:
        data["cpf_oa"] = oa; data["cpf_ma"] = ma; data["cpf_ra"] = ra
        data["cpf_total"] = fmt_money(money_number(oa)+money_number(ma)+money_number(ra))

    if product_type == "Tokio Marine" or re.search(r"Tokio\s+Marine|Wealth\s+Flexi-Link", text, re.I):
        tm = extract_tokio_marine(text, fields)
        # Tokio application / BI are authoritative for Tokio-specific client, product and adviser data.
        for k, v in tm.items():
            if v not in (None, ""):
                data[k] = v
        # Do not keep generic keyword guesses from insurer option lists.  Tokio's
        # proposal contains labels such as "Savings" even when no corresponding
        # client declaration is selected, so only retain these values when they
        # were explicitly extracted from a supporting completed TFP.
        if not tm.get("source_of_income"):
            data.pop("source_of_income", None)

    return {k: clean(v) for k, v in data.items() if clean(v)}


def retirement_calc(expected_yearly: str, cpf_life_yearly: str = "") -> dict[str, str]:
    exp = money_number(expected_yearly)
    cpf = money_number(cpf_life_yearly) if cpf_life_yearly else 0.0
    shortfall = max(exp - cpf, 0.0)
    years = 15 if exp else 0
    total = shortfall * years
    return {
        "retirement_amt": fmt_money(exp, compact=True) if exp else "",
        "retirement_income": fmt_money(cpf, compact=True) if cpf else "",
        "retirement_shortfall": fmt_money(shortfall, compact=True) if shortfall else "",
        "retirement_years": str(years) if years else "",
        "retirement_amt_plan": fmt_money(total, compact=True) if total else "",
        "retirement_total_amt": fmt_money(total, compact=True) if total else "",
    }


def recommendation_text(data: dict[str, Any], product_type: str, expected_retirement_income: str) -> str:
    client = data.get("client_name", "Client")
    age = data.get("age_next") or data.get("age_last_birthday") or ""
    if product_type == "Tokio Marine":
        current_age = ""
        try:
            current_age = str(max(int(age) - 1, 0)) if age else ""
        except Exception:
            current_age = ""
        plan = data.get("plan_name") or "Tokio Marine investment-linked plan"
        premium_n = money_number(data.get("premium", ""))
        yearly_n = money_number(expected_retirement_income) if expected_retirement_income else 0.0
        mip = data.get("mip", "")
        policy_term = data.get("policy_term", "") or "Life"
        funds = []
        for i in range(1, 8):
            fname = data.get(f"fund_{i}_name", "")
            alloc = data.get(f"fund_{i}_allocation", "")
            if fname:
                funds.append(f"{fname}{f' ({alloc}%)' if alloc else ''}")
        parts = []
        parts.append(f"Client{f' (current age {current_age})' if current_age else ''} is considering a long-term investment-linked plan for wealth accumulation and retirement planning, with insurance protection as part of the arrangement.")
        if yearly_n:
            parts.append(f"Client has indicated an expected retirement income need of ${fmt_money(yearly_n)} per year. This stated objective is used for the retirement planning figures in this TFP and should be reviewed if the client's circumstances or objective changes.")
        parts.append(f"Based on the documents provided, {plan} is a regular-premium investment-linked plan issued by Tokio Marine Life Insurance Singapore Pte. Ltd.{f' The stated annual premium is ${fmt_money(premium_n)}.' if premium_n else ''}")
        if funds:
            parts.append("The selected fund allocation is: " + "; ".join(funds) + ". Fund values and investment returns are not guaranteed and may rise or fall.")
        benefit = data.get("benefit_type", "")
        if benefit.lower() == "enhanced":
            parts.append("The Policy Illustration shows the Enhanced Death Benefit option. During the Minimum Investment Period, the illustrated death benefit is the higher of 101% of the non-guaranteed policy value or the guaranteed death benefit, with the guaranteed death benefit based on regular premiums paid; thereafter the death benefit is 101% of the non-guaranteed policy value.")
        if mip:
            parts.append(f"The stated Minimum Investment Period is {mip}. Early surrender may result in a surrender value that is lower than premiums paid, and the Policy Illustration states that surrender charges apply during the Minimum Investment Period.")
        if policy_term:
            parts.append(f"Policy term: {policy_term}.")
        parts.append("The Policy Illustration states that illustrated investment returns are not guaranteed and that actual benefits depend on the performance of the underlying investment-linked sub-funds, fees and charges, withdrawals and policy alterations. The client should refer to the Policy Illustration, Product Summary and applicable fund documents for the complete terms, charges and risks.")
        risk = data.get("risk_profile", "")
        if risk:
            parts.append(f"Client risk profile recorded in the supporting documents: {risk}. Any mismatch between the client's risk profile and selected funds should be explained and acknowledged before proceeding.")
        return "\n\n".join(parts)
    plan = data.get("plan_name") or ("Manulife InvestReady (III) 10 Years Flexi 3" if product_type == "Manulife" else "FWD Invest Flexi Elite")
    premium = norm_money(data.get("premium") or "")
    yearly = fmt_money(money_number(expected_retirement_income)) if expected_retirement_income else ""
    cpf = data.get("cpf_total", "")
    fund = data.get("fund_name") or "the selected investment-linked fund(s)"
    base = []
    base.append(f"Client{f' (ANB age {age})' if age else ''} understands that CPF monies alone may be insufficient for retirement based on today's standard of living and inflation.")
    if yearly:
        base.append(f"Client has indicated an expected retirement income need of ${yearly} per year. This retirement income objective was considered when assessing the recommendation and affordability of the plan.")
    base.append("Client wishes to explore options to enhance retirement income and to build a retirement nest egg, after reviewing the desired retirement age and retirement plan.")
    base.append(f"Based on the consideration above, {plan} is recommended as an investment-linked plan to help the client participate in market opportunities while retaining insurance coverage. The selected fund allocation is {fund}.")
    if premium:
        base.append(f"The proposed annual premium / budget is ${fmt_money(money_number(premium))}. Client has confirmed that the premium will be funded from existing savings and/or available financial resources.")
    if cpf:
        base.append(f"CPF account information provided shows total CPF balances of approximately ${cpf}. The CPF information was considered together with other disclosed assets when assessing affordability and concentration risk.")
    base.append("The client has been informed that returns, dividends and surrender values are not guaranteed. Fund prices may go up or down and past performance is not indicative of future performance.")
    if product_type == "Manulife":
        base.append("For Manulife InvestReady (III) 10 Years Flexi 3, client has the flexibility to pay premiums for the first 3 policy years or continue to contribute thereafter. Client has also been informed that withdrawals or surrender within the first 10 policy years may incur applicable surrender / withdrawal charges.")
    else:
        base.append("For FWD Invest Flexi Elite, client has been informed of the plan features, premium commitment, flexibility, charges and investment risks before deciding to proceed.")
    base.append("The investment exposure remains within the client's disclosed financial position and the client has indicated sufficient liquidity to continue with the proposed arrangement.")
    base.append("Client acknowledges the explanation provided and has decided to proceed with the application.")
    return "\n\n".join(base)


def build_case(paths: list[Path], adviser_email: str, product_type: str, expected_retirement_income: str = "") -> dict[str, Any]:
    text, fields = all_text_and_fields(paths)
    data = extract_client(text, fields, adviser_email, product_type)
    data["product_type"] = product_type
    data["expected_retirement_income"] = expected_retirement_income
    data.update(retirement_calc(expected_retirement_income, data.get("cpf_life_income", "")))
    data["recommendation_text"] = recommendation_text(data, product_type, expected_retirement_income)
    data["raw_field_count"] = len(fields)
    return data
