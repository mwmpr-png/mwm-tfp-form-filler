from __future__ import annotations

import base64
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import fitz
from pypdf import PdfReader

from .compliance_rules import enrich_case


def clean(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).replace("\x00", " ").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def normalise_address_and_postal(address: Any, postal: Any = "") -> tuple[str, str]:
    """Keep a Singapore postal code in the dedicated postal field, not twice.

    ID extraction often returns an address ending in ``SINGAPORE 123456`` while
    also returning ``123456`` separately.  The TFP has its own Postal Code field,
    so remove only the trailing duplicate six-digit code from the address line.
    """
    addr = clean(address)
    pc = clean(postal)
    if not pc:
        m = re.search(r"(?:\bSINGAPORE\s+)?(\d{6})\s*$", addr, flags=re.I)
        if m:
            pc = m.group(1)
    if pc and addr:
        addr = re.sub(rf"\s+{re.escape(pc)}\s*$", "", addr).strip()
    return addr, pc


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
    text = clean(s).lower().replace("s$", "").replace("$", "").replace(",", "").strip()
    if not text or text in {"na", "n/a", "not disclosed", "not disclose"}:
        return 0.0
    m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(million|mil|m|k)\b", text)
    if m:
        try:
            n = float(m.group(1))
            return n * (1_000 if m.group(2) == "k" else 1_000_000)
        except Exception:
            return 0.0
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else 0.0


def fmt_money(n: float, compact: bool = False) -> str:
    try:
        n = float(n)
    except Exception:
        return ""
    if compact:
        if n >= 1_000_000 and n % 1_000_000 == 0:
            return f"{int(n / 1_000_000)}MIL"
        if n >= 1000 and n % 1000 == 0:
            return f"{int(n / 1000)}K"
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
                out[str(k)] = clean(val).lstrip("/")
    except Exception:
        pass
    return out


def all_text_and_fields(paths: list[Path]) -> tuple[str, dict[str, str]]:
    texts: list[str] = []
    merged_fields: dict[str, str] = {}
    for p in paths:
        if not p:
            continue
        fields = pdf_fields(p) if p.suffix.lower() == ".pdf" else {}
        if fields:
            merged_fields.update(fields)
            texts.append("\n".join(f"[FIELD] {k}: {v}" for k, v in fields.items()))
        if p.suffix.lower() == ".pdf":
            texts.append(pdf_text(p))
    return clean("\n\n".join(texts)), merged_fields


def normalise_nric_from_text(text: str) -> str:
    """Extract Singapore NRIC/FIN-like value from noisy OCR text."""
    raw = clean(text).upper().replace("§", "S").replace("＄", "S")
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    m = re.search(r"([STFG]\d{7}[A-Z])", compact)
    return m.group(1) if m else ""


def normalise_nationality(raw: str, nric: str = "") -> str:
    val = clean(raw).upper()
    if not val:
        return ""
    if "SINGAPORE CITIZEN" in val or val == "SINGAPOREAN":
        return "SINGAPORE CITIZEN"
    if "SINGAPORE PR" in val or "PERMANENT RESIDENT" in val:
        return "SINGAPORE PR"
    if nric and nric[0] in "ST" and val not in ("SINGAPORE", "SINGAPORE CITIZEN"):
        return "SINGAPORE PR"
    return val.title() if val.isupper() else raw


def find(pattern: str, text: str, flags: int = re.I | re.S, default: str = "") -> str:
    m = re.search(pattern, text, flags)
    return clean(m.group(1)) if m else default


def first_field(fields: dict[str, str], *names: str) -> str:
    for n in names:
        if n in fields and clean(fields[n]):
            return clean(fields[n])
    return ""


def parse_date_ddmmyyyy(raw: str) -> str:
    raw = clean(raw)
    if not raw:
        return ""
    months = {
        "jan": "01", "january": "01", "feb": "02", "february": "02", "mar": "03", "march": "03",
        "apr": "04", "april": "04", "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
        "aug": "08", "august": "08", "sep": "09", "sept": "09", "september": "09", "oct": "10", "october": "10",
        "nov": "11", "november": "11", "dec": "12", "december": "12",
    }
    m = re.search(r"(\d{1,2})[\-/\. ]+(\d{1,2})[\-/\. ]+(\d{2,4})", raw)
    if m:
        d, mo, y = m.groups()
        y = ("20" + y) if len(y) == 2 and int(y) < 40 else (("19" + y) if len(y) == 2 else y)
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw)
    if m:
        d, mo, y = m.groups()
        mo = months.get(mo.lower(), mo)
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


def parse_id_text(text: str) -> dict[str, str]:
    text = clean(text)
    out: dict[str, str] = {}
    nric = normalise_nric_from_text(text)
    if nric:
        out["nric"] = nric
    name = find(
        r"(?:^|\n)\s*(?:NAME|Name)\s*\n\s*([A-Z][A-Z\s,.'\-()/]+?)(?:\n|NRIC|DATE OF BIRTH|NATIONALITY)",
        text,
        flags=re.I | re.S,
    )
    if name:
        name = re.sub(r"\s+", " ", name).strip(" -,/()")
        if 2 <= len(name) <= 80:
            out["client_name"] = name.title() if name.isupper() else name
    dob = find(r"(?:DATE OF BIRTH|Date of Birth|DOB)\s*[:\n ]+([0-9]{1,2}[\-/ ][0-9A-Za-z]{1,9}[\-/ ][0-9]{2,4})", text)
    if dob:
        out["dob"] = parse_date_ddmmyyyy(dob)
    gender = find(r"(?:SEX|Gender)\s*[:\n ]+(MALE|FEMALE|M|F)\b", text)
    if gender:
        out["gender"] = "Female" if gender.upper().startswith("F") else "Male"
    nat = find(r"(?:NATIONALITY\s*/\s*CITIZENSHIP|NATIONALITY|CITIZENSHIP)\s*[:\n ]+([A-Z ]{3,40})", text)
    if nat:
        out["nationality"] = normalise_nationality(nat, nric)
    pob = find(r"(?:PLACE OF BIRTH|Country/Place of birth|Country of Birth)\s*[:\n ]+([A-Z ]{3,40})", text)
    if pob:
        out["birthplace"] = clean(pob).title() if pob.isupper() else clean(pob)
    addr = find(r"(?:ADDRESS|Address)\s*[:\n ]+(.{5,160}?SINGAPORE\s*\d{6})", text)
    if addr:
        addr = re.sub(r"\s+", " ", addr).strip()
        out["residential_address"] = addr.upper()
        pc = find(r"SINGAPORE\s*(\d{6})", addr)
        if pc:
            out["postal"] = pc
    return {k: clean(v) for k, v in out.items() if clean(v)}


def render_first_page_image(path: Path, max_px: int = 1800) -> tuple[str, str] | tuple[None, None]:
    """Return (mime, base64) for first page/image, downscaled for OpenAI vision."""
    try:
        from PIL import Image
        import io

        if path.suffix.lower() == ".pdf":
            doc = fitz.open(str(path))
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            im = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
        else:
            im = Image.open(path).convert("RGB")
        im.thumbnail((max_px, max_px))
        bio = io.BytesIO()
        im.save(bio, format="JPEG", quality=88)
        return "image/jpeg", base64.b64encode(bio.getvalue()).decode("ascii")
    except Exception:
        return None, None


def local_ocr_id(path: Path) -> str:
    """Best-effort local OCR only when explicitly enabled."""
    if os.getenv("ENABLE_LOCAL_OCR", "").lower() not in {"1", "true", "yes"}:
        return ""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance

        if path.suffix.lower() == ".pdf":
            doc = fitz.open(str(path))
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
            base = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
        else:
            base = Image.open(path).convert("RGB")
        variants = [base, base.convert("L"), ImageEnhance.Contrast(base.convert("L")).enhance(1.8)]
        parts: list[str] = []
        for im in variants:
            for psm in (6, 11, 3):
                try:
                    txt = pytesseract.image_to_string(im, config=f"--psm {psm}")
                    if txt and txt not in parts:
                        parts.append(txt)
                except Exception:
                    continue
        return clean("\n".join(parts))
    except Exception:
        return ""


def openai_vision_extract_id(path: Path) -> dict[str, str]:
    """Use OpenAI vision for NRIC/ID scans when normal PDF text extraction is insufficient."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {}
    mime, b64 = render_first_page_image(path)
    if not b64:
        return {}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_VISION_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
        prompt = (
            "Extract the visible details from this Singapore NRIC/ID/passport image. "
            "Return only JSON with these keys when visible: client_name, nric, dob, gender, "
            "nationality, birthplace, residential_address, postal. Use exact document text. "
            "For dob use DD/MM/YYYY. Do not guess unreadable details."
        )
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
        content = resp.choices[0].message.content or "{}"
        m = re.search(r"\{.*\}", content, flags=re.S)
        obj = json.loads(m.group(0) if m else content)
        out = {k: clean(v) for k, v in obj.items() if clean(v)}
        if out.get("nric"):
            out["nric"] = normalise_nric_from_text(out["nric"])
        if out.get("dob"):
            out["dob"] = parse_date_ddmmyyyy(out["dob"])
        if out.get("nationality"):
            out["nationality"] = normalise_nationality(out["nationality"], out.get("nric", ""))
        return {k: v for k, v in out.items() if v}
    except Exception:
        return {}


def extract_id_document(path: Path) -> dict[str, str]:
    """Extract key personal details from uploaded Client NRIC / ID file."""
    if not path:
        return {}
    combined = pdf_text(path, max_pages=1) if path.suffix.lower() == ".pdf" else ""
    parsed = parse_id_text(combined)
    if not parsed.get("nric") or not parsed.get("dob") or not parsed.get("client_name"):
        vision = openai_vision_extract_id(path)
        for k, v in vision.items():
            if v and (k in {"nric", "dob", "gender", "nationality", "birthplace", "residential_address", "postal"} or not parsed.get(k)):
                parsed[k] = v
    if not parsed.get("nric") or not parsed.get("dob") or not parsed.get("residential_address"):
        ocr_text = local_ocr_id(path)
        if ocr_text:
            parsed.update({k: v for k, v in parse_id_text(combined + "\n" + ocr_text).items() if v})
    if parsed.get("nationality"):
        parsed["nationality"] = normalise_nationality(parsed["nationality"], parsed.get("nric", ""))
    return parsed


def title_name_from_email(email: str) -> str:
    name = email.split("@")[0].replace(".", " ").replace("_", " ").strip()
    return name.upper() if name else ""


def _clean_name_candidate(raw: str, client_name: str = "") -> str:
    """Normalise and validate a likely human adviser name extracted from BI/TFP text."""
    val = clean(raw)
    if not val:
        return ""
    parts: list[str] = []
    for line in val.splitlines():
        line = clean(line)
        if not line:
            continue
        if re.fullmatch(
            r"(?i)(date|signature|page \d+ of \d+|this illustration.*|financial consultant'?s name|financial consultant'?s code|your fa representative\(s\)|specially for:?|specially prepared for:?)",
            line,
        ):
            continue
        parts.append(line)
    val = clean(" ".join(parts))
    val = re.sub(r"^(Mr|Mdm|Ms|Mrs|Miss)\s+", "", val, flags=re.I).strip()
    val = re.sub(r"\s+", " ", val).strip(" -:,.|/")
    if not val:
        return ""
    val_u = val.upper()
    bad_fragments = (
        "DATE GENERATED", "THIS ILLUSTRATION", "PAGE ", "FINANCIAL PLANNER", "TRUSTED ADVICE",
        "SPECIAL DISCLOSURE", "POLICY", "PREMIUM", "SUM INSURED", "BENEFIT", "CURRENCY",
        "PROMISELAND", "MASSIVE WEALTH", "GROUP INSURANCE", "STEP 1", "UPLOAD", "NO FILE",
        "MWM ADMIN", "MWM PR", "MWM CREATIVE", "ADMIN", "TEST",
    )
    if any(x in val_u for x in bad_fragments):
        return ""
    if "@" in val or re.search(r"\d{4,}", val):
        return ""
    if not re.fullmatch(r"[A-Za-z][A-Za-z \-().,'/]{2,90}", val):
        return ""
    client_u = clean(client_name).upper()
    if client_u and (val_u == client_u or val_u in client_u or client_u in val_u):
        return ""
    alpha_tokens = re.findall(r"[A-Za-z]+", val)
    if len(alpha_tokens) < 2 and len(val) < 10:
        return ""
    return val


def useful_name_from_email(email: str) -> str:
    """Last-resort email fallback. Generic team addresses are deliberately rejected."""
    local = clean(email.split("@")[0] if email else "").lower()
    if not local:
        return ""
    generic = {"admin", "mwm", "mwm.admin", "mwm.pr", "mwm.creative", "creative", "support", "ops", "operations"}
    if local in generic or local.startswith("mwm.") or "admin" in local:
        return ""
    return title_name_from_email(email)


def extract_adviser_name_from_text(text: str, client_name: str = "") -> str:
    """Extract FA representative name from BI / completed TFP text before using any fallback."""
    txt = clean(text)
    if not txt:
        return ""
    candidates: list[str] = []
    for m in re.finditer(r"\n\s*Date\s*\n\s*([A-Z][A-Z \n().,'/-]{3,140}?)\n\s*Date\s*\n\s*This illustration", txt, flags=re.I | re.S):
        candidates.append(m.group(1))
    m = re.search(r"Group Insurance\.\s*\n\s*([^\n]{2,90})\s*\n\s*([^\n]{2,90})\s*\n\s*(?:STEP\s*1|Step\s*1)", txt, flags=re.I)
    if m:
        candidates.append(m.group(2))
    for pat in (
        r"Your FA Representative\(s\)\s*\n\s*([^\n]{2,90})",
        r"Financial Consultant'?s name\s*\n\s*([^\n]{2,90})",
        r"FA Rep.?s Name\s*\n(?:[^\n]*\n){0,8}?\s*([A-Z][A-Z \-().']{3,90})\s*\n\s*(?:[A-Z0-9]{4,12}|\d{1,2}\s+[A-Z]{3})",
    ):
        for m in re.finditer(pat, txt, flags=re.I):
            candidates.append(m.group(1))
    for m in re.finditer(r"Sighted and verified\s+by\s+([A-Z][A-Za-z \-().']{3,90})", txt, flags=re.I):
        candidates.append(m.group(1))
    for cand in candidates:
        cleaned = _clean_name_candidate(cand, client_name)
        if cleaned:
            return cleaned
    return ""


def split_client_name(name: str) -> tuple[str, str]:
    parts = clean(name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0].upper(), ""
    return parts[0].upper(), " ".join(parts[1:]).upper()


def extract_hsbc_tfp_personal(text: str) -> dict[str, Any]:
    """Best-effort extraction from HSBC life/application documents."""
    out: dict[str, Any] = {}
    m = re.search(
        r"Name\s*\nNRIC\s*/\s*FIN\s*/\s*Passport No\.\s*\nNationality\s*\nDate of Birth[^\n]*\nPlace of Birth[\s\S]{0,120}?\n\s*([A-Z][A-Za-z ,.'-]{2,80})\s*\n\s*([STFG]\d{7}[A-Z])\s*\n\s*([A-Z ]{3,30})\s*\n\s*(\d{1,2}/\d{1,2}/\d{4})\s*\n\s*([A-Z ]{3,30})",
        text,
        flags=re.I,
    )
    if m:
        out["client_name"] = clean(m.group(1)).title()
        out["nric"] = m.group(2).upper()
        out["nationality"] = normalise_nationality(m.group(3), out["nric"])
        out["dob"] = parse_date_ddmmyyyy(m.group(4))
        out["birthplace"] = clean(m.group(5)).title()
    if not out.get("client_name"):
        m = re.search(r"Last Name/Surname\s*\n\s*First/Given Name[\s\S]{0,120}?\n\s*([A-Z][A-Z'-]+)\s*\n\s*([A-Z][A-Z\s'-]+)\s*\n", text, flags=re.I)
        if m:
            out["client_name"] = clean(m.group(1) + " " + m.group(2)).title()
    if not out.get("nric"):
        nric = normalise_nric_from_text(text)
        if nric:
            out["nric"] = nric
    if not out.get("dob"):
        dob = find(r"Date of birth\s*\(dd/mm/yyyy\)\s*\n\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", text)
        if dob:
            out["dob"] = parse_date_ddmmyyyy(dob)
    if not out.get("residential_address"):
        m = re.search(r"Residential Address[\s\S]{0,420}?\n\s*([A-Z0-9 #,.'/-]+SINGAPORE)\s*\n\s*Postal Code\s*\n\s*(\d{6})", text, flags=re.I)
        if m:
            out["residential_address"] = clean(m.group(1)).upper()
            out["postal"] = m.group(2)
    if not out.get("mobile"):
        mob = find(r"Mobile Number\s*\nEmail Address[\s\S]{0,80}?\n\s*([689]\d{7})", text)
        if mob:
            out["mobile"] = mob
    if not out.get("client_email"):
        email = find(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", text, flags=re.I)
        if email:
            out["client_email"] = email
    if re.search(r"\bFemale\b|IZl Female|\[Z\]\s*Female|Female\s*\n", text, flags=re.I):
        out.setdefault("gender", "Female")
    elif re.search(r"\bMale\b", text, flags=re.I):
        out.setdefault("gender", "Male")
    if re.search(r"\bMarried\b", text, flags=re.I):
        out.setdefault("marital_status", "Married")
    plan = find(r"I recommend the\s+([^\n]+)", text) or find(r"Product\s*Name\s*[:\n ]+([^\n]+)", text)
    if plan:
        out["plan_name"] = clean(plan)
    if re.search(r"HSBC Life Indexed Flexi Income", text, re.I):
        out.setdefault("plan_name", "HSBC Life Indexed Flexi Income")
    if re.search(r"Diamond Prestige|IUL", text, re.I):
        out.setdefault("plan_name", "HSBC Life Diamond Prestige IUL II")
    prem = (
        find(r"US\$\s*([0-9,]+(?:\.\d+)?)\s+single premium", text)
        or find(r"single premium policy\s+using.*?US\$\s*([0-9,]+)", text)
        or find(r"Premium\s*Amount\s*[:\n ]+\$?([0-9,]+(?:\.\d+)?)", text)
    )
    if prem:
        out["premium"] = prem
        out.setdefault("currency", "USD" if "US$" in text or "USD" in text else "SGD")
    fa = find(r"Financial Consultant's name\s*\n\s*([^\n]+)", text)
    code = find(r"Financial Consultant's code\s*\n\s*([0-9A-Za-z]+)", text)
    if fa and not re.search(r"Financial Consultant|Organisation", fa, re.I):
        out["adviser_name_from_hsbc"] = clean(fa)
    if code:
        out["fa_source_code"] = code
    return {k: clean(v) for k, v in out.items() if clean(v)}


def extract_from_bi(text: str, fields: dict[str, str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    data["client_name"] = clean(
        find(r"Specially prepared for\s*:\s*(?:Mr|Mdm|Ms|Mrs)?\s*([^\n]+?)\s+Date Generated", text)
        or first_field(fields, "Full Name", "Name of Proposer", "Clientname", "client_name")
    )
    data["plan_name"] = clean(find(r"Plan\s*:\s*([^\n]+)", text) or first_field(fields, "Plan Name", "1", "product_1", "Name of Products"))
    data["gender"] = clean(find(r"Plan\s*:\s*[^\n]+\n[^\n]*\b(Male|Female)\b", text) or first_field(fields, "Gender"))
    data["smoker"] = "No" if re.search(r"Non[- ]Smoker", text, re.I) else ""
    data["premium"] = clean(
        find(r"(?:Total Premium|Basic Premium)\s*:\s*\$?([0-9,]+(?:\.\d{2})?)", text)
        or first_field(fields, "undefined_19", "premiums_1", "Premium", "fill_23")
    )
    data["premium_frequency"] = clean(find(r"Premium Frequency\s*:\s*([^\n]+)", text))
    data["currency"] = clean(find(r"Currency\s*:\s*([A-Z]{3})", text)) or "SGD"
    data["mip"] = clean(find(r"Minimum Investment Period\s*:\s*([^\n]+)", text))
    data["benefit_type"] = clean(find(r"Benefit Type\s*:\s*([^\n]+)", text))
    data["age_last_birthday"] = clean(find(r"Age Last Birthday\s*:\s*(\d+)", text))
    # Do not manufacture a policy term for unknown products.
    data["policy_term"] = clean(find(r"Manulife InvestReady[^\n]*\s+(Up to age 99)\s+(\d+)\s+", text))
    data["premium_term"] = clean(find(r"Manulife InvestReady[^\n]*Up to age 99\s+(\d+)\s+", text))
    data["sum_assured"] = first_field(fields, "sum_assured", "Sum Assured", "fill_22_2")

    fa_match = re.search(r"\nDate\s*\n([A-Z][A-Z \n().,'/-]{3,140}?)\nDate\s*\nThis illustration", text, flags=re.S)
    if fa_match:
        fa = clean(" ".join(line.strip() for line in fa_match.group(1).splitlines() if line.strip()))
        fa = _clean_name_candidate(fa, data.get("client_name", ""))
        if fa:
            data["adviser_name_from_bi"] = fa
    if not data.get("adviser_name_from_bi"):
        fa = extract_adviser_name_from_text(text, data.get("client_name", ""))
        if fa:
            data["adviser_name_from_bi"] = fa

    if re.search(r"HSBC Life Indexed Flexi Income", text, re.I) and not data.get("plan_name"):
        data["plan_name"] = "HSBC Life Indexed Flexi Income"
    if re.search(r"HSBC Life Diamond Prestige|Diamond Prestige IUL|IUL II", text, re.I) and not data.get("plan_name"):
        data["plan_name"] = "HSBC Life Diamond Prestige IUL II"
    if re.search(r"FWD|Invest Flexi Elite", text, re.I) and not data.get("plan_name"):
        data["plan_name"] = "FWD Invest Flexi Elite"

    hsbc_extra = extract_hsbc_tfp_personal(text)
    for k, v in hsbc_extra.items():
        if v and not data.get(k):
            data[k] = v
    return {k: v for k, v in data.items() if v}


def extract_client(text: str, fields: dict[str, str], adviser_email: str = "") -> dict[str, Any]:
    data = extract_from_bi(text, fields)
    data["client_name"] = first_field(fields, "Full Name", "Name of Proposer", "Clientname", "client_name", "Name") or data.get("client_name", "")
    data["nric"] = first_field(fields, "NRIC Passport", "NRIC / Passport", "NRIC Passport Number", "NRIC No", "NRIC", "nric") or find(r"\b([STFG]\d{7}[A-Z])\b", text)
    data["nationality"] = (
        first_field(fields, "nationality", "undefined_2")
        or find(r"NATIONALITY\s*/\s*CITIZENSHIP\s*\n?([A-Z ]+)", text)
        or ("SINGAPORE CITIZEN" if re.search(r"Singaporean|SINGAPORE CITIZEN", text, re.I) else "")
    )
    data["dob"] = first_field(fields, "date_of_birth", "Date of Birth  GG PPP", "DOB") or find(
        r"(?:DATE OF BIRTH|Date of Birth|DOB)\s*[:\n ]+([0-9]{1,2}[\-/ ][0-9A-Za-z]{1,9}[\-/ ][0-9]{2,4})", text
    )
    if not data.get("dob") and fields.get("Text11") and fields.get("Text12") and fields.get("Text13"):
        data["dob"] = f"{fields.get('Text11')}/{fields.get('Text12')}/{fields.get('Text13')}"
    data["dob"] = parse_date_ddmmyyyy(data.get("dob", ""))
    data["birthplace"] = first_field(fields, "birthplace", "Country of Birth", "undefined_4") or find(r"(?:PLACE OF BIRTH|Country of Birth)\s*[:\n ]+([A-Z ]+)", text)
    data["gender"] = data.get("gender") or ("Female" if re.search(r"\bFEMALE\b", text, re.I) else ("Male" if re.search(r"\bMALE\b", text, re.I) else ""))
    data["marital_status"] = (
        "Widowed" if fields.get("Widowed") or fields.get("checkbox_widowed")
        else "Married" if fields.get("Married") or fields.get("checkbox_married")
        else "Single" if fields.get("Single") or fields.get("checkbox_single")
        else data.get("marital_status", "")
    )
    data["residential_address"] = first_field(fields, "Residential Address", "residential_address", "is no residential address in the identification document 1") or find(r"ADDRESS\s*\n?(.+?SINGAPORE\s*\d{6})", text)
    data["postal"] = first_field(fields, "Postal Code", "postal")
    if not data.get("postal") and data.get("residential_address"):
        data["postal"] = find(r"SINGAPORE\s*(\d{6})", data.get("residential_address", ""))
    data["mobile"] = first_field(fields, "Mobile No", "Mobile Number", "mobile_number", "undefined_7")
    data["client_email"] = first_field(fields, "Email Address", "email", "undefined_8")
    data["occupation"] = first_field(fields, "Occupation", "occupation", "undefined_9")
    data["employer"] = first_field(fields, "Employer", "undefined_10")
    data["annual_income"] = first_field(fields, "Current Year S", "Annual Earned Income S", "annual_income", "Text119")
    data["employment_status"] = (
        "Retired" if fields.get("checkbox_retired") or fields.get("Retired")
        else "Full-Time" if fields.get("FullTime") or fields.get("Full-Time")
        else ""
    )
    # Keep source of income and transaction source of funds separate.  One must
    # never be silently substituted for the other.
    data["source_of_income"] = first_field(fields, "income_source", "if retired  unemployed")

    funding_sources: list[str] = []
    direct_source = first_field(fields, "Source of Funds", "Text152", "Text156")
    if direct_source:
        funding_sources.append(direct_source)
    if first_field(fields, "Employment  Trade Income", "Employment Trade Income"):
        funding_sources.append("Employment / Trade Income")
    if first_field(fields, "Investment Income"):
        funding_sources.append("Investment Income")
    if first_field(fields, "Savings"):
        funding_sources.append("Savings")
    other_source = first_field(fields, "undefined_72")
    if other_source:
        funding_sources.append(other_source)
    # Preserve order while removing duplicates.
    if funding_sources:
        data["source_of_funds"] = " & ".join(dict.fromkeys(funding_sources))

    data["education"] = first_field(fields, "highest_education_level", "Highest Education Level")
    data["english"] = "Yes" if fields.get("checkbox_english_yes") or fields.get("yes1") else ""

    if not data.get("age_next"):
        if data.get("age_last_birthday"):
            try:
                data["age_next"] = str(int(data["age_last_birthday"]) + 1)
            except Exception:
                pass
        if not data.get("age_next") and data.get("dob"):
            data["age_next"] = age_next_birthday(data["dob"])

    data["adviser_email"] = adviser_email
    adviser_from_fields = _clean_name_candidate(first_field(fields, "FAname", "fa_name", "Representatives Name 1", "namefa"), data.get("client_name", ""))
    adviser_from_text = extract_adviser_name_from_text(text, data.get("client_name", ""))
    # Never turn a generic team email into a fake FA name.
    data["adviser_name"] = data.get("adviser_name_from_bi") or data.get("adviser_name_from_hsbc") or adviser_from_text or adviser_from_fields or ""
    data["fa_source_code"] = first_field(fields, "sourcecode", "Representatives Code 1") or data.get("fa_source_code", "")

    # Fund details: keep exact names from source fields/factsheets when available.
    data["fund_code"] = first_field(fields, "Fund CodeRow1")
    data["fund_name"] = first_field(fields, "Fund NameRow1", "fundmanager1", "Name of Fund Manager  Investment Product1")
    data["fund_allocation"] = first_field(fields, "Text115", "investamount1", "RSP 1")
    data["asset_class"] = first_field(fields, "Asset Class")
    data["risk_profile"] = first_field(fields, "S  L  JO", "5 Clients Risk Profile")

    # CPF balances from CPF statements.
    oa = find(r"Ordinary Account \(OA\)\s*\$?([0-9,]+\.\d{2})", text)
    ma = find(r"MediSave Account \(MA\)\s*\$?([0-9,]+\.\d{2})", text)
    ra = find(r"Retirement Account \(RA\)\s*\$?([0-9,]+\.\d{2})", text)
    if oa or ma or ra:
        data["cpf_oa"] = oa
        data["cpf_ma"] = ma
        data["cpf_ra"] = ra
        data["cpf_total"] = fmt_money(money_number(oa) + money_number(ma) + money_number(ra))

    return {k: clean(v) if isinstance(v, str) else v for k, v in data.items() if v not in (None, "")}


def retirement_calc(expected_yearly: str, cpf_life_yearly: str = "", years: str | int | None = None) -> dict[str, str]:
    """Retirement FNA without inventing a fixed duration.

    Older code silently assumed 15 years.  The updated version only calculates a
    total retirement amount when an actual number of retirement-income years is
    supplied.  Otherwise the annual need/shortfall can be shown while the total
    remains blank for review.
    """
    exp = money_number(expected_yearly)
    cpf = money_number(cpf_life_yearly) if cpf_life_yearly else 0.0
    shortfall = max(exp - cpf, 0.0)
    try:
        years_n = int(float(years)) if years not in (None, "") else 0
    except Exception:
        years_n = 0
    total = shortfall * years_n if years_n > 0 else 0.0
    return {
        "retirement_amt": fmt_money(exp, compact=True) if exp else "",
        "retirement_income": fmt_money(cpf, compact=True) if cpf else "",
        "retirement_shortfall": fmt_money(shortfall, compact=True) if exp else "",
        "retirement_years": str(years_n) if years_n else "",
        "retirement_amt_plan": fmt_money(total, compact=True) if total else "",
        "retirement_total_amt": fmt_money(total, compact=True) if total else "",
    }


def recommendation_text(data: dict[str, Any], product_type: str, expected_retirement_income: str) -> str:
    """Compatibility wrapper: deterministic BOR is now built by compliance_rules.enrich_case."""
    working = dict(data)
    working["expected_retirement_income"] = expected_retirement_income
    enrich_case(working, product_type, source_text="", fields={})
    return clean(working.get("recommendation_text"))


def build_case(paths: list[Path], adviser_email: str, product_type: str, expected_retirement_income: str = "") -> dict[str, Any]:
    text, fields = all_text_and_fields(paths)
    data = extract_client(text, fields, adviser_email)

    # First uploaded document remains the Client NRIC / ID in the existing UI.
    id_data = extract_id_document(paths[0]) if paths else {}
    for key, val in id_data.items():
        if not val:
            continue
        if key in {"nric", "dob", "gender", "nationality", "birthplace", "residential_address", "postal"}:
            data[key] = val
        elif not data.get(key):
            data[key] = val
    if data.get("dob") and not data.get("age_next"):
        data["age_next"] = age_next_birthday(data["dob"])

    # The ID may contain the six-digit postal code at the end of the residential
    # address and also in a dedicated postal field. Keep it only once in the TFP.
    if data.get("residential_address"):
        addr, pc = normalise_address_and_postal(data.get("residential_address"), data.get("postal"))
        data["residential_address"] = addr
        if pc:
            data["postal"] = pc

    data["product_type"] = product_type
    data["expected_retirement_income"] = expected_retirement_income

    # Preserve retirement inputs only when supported; do not use the old fixed 15-year assumption.
    data.update(retirement_calc(expected_retirement_income, data.get("cpf_life_income", ""), data.get("retirement_years")))

    # Compliance enrichment sees all uploaded source text + actual form fields.  It may
    # calculate deterministic items, but missing client facts remain missing/REVIEW.
    data = enrich_case(data, product_type, source_text=text, fields=fields)
    data["raw_field_count"] = len(fields)
    return data
