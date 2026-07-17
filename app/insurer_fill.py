from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import fitz

from .settings import TEMPLATE_DIR
from .extractor import clean, money_number, fmt_money, parse_date_ddmmyyyy, age_next_birthday
from .pdf_fill import fill_pdf, stamp_signatures, today_ddmmyyyy, today_human, _clean_image


def _safe(v: Any) -> str:
    return clean(v)


def _upper(v: Any) -> str:
    return _safe(v).upper()


def _split_name(name: str) -> tuple[str, str]:
    parts = _safe(name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0].upper(), ""
    return parts[0].upper(), " ".join(parts[1:]).upper()


def _dob_parts(dob: str) -> tuple[str, str, str]:
    dob = parse_date_ddmmyyyy(dob)
    try:
        d, m, y = dob.split("/")
        return d, m, y
    except Exception:
        return "", "", ""


def _today_parts() -> tuple[str, str, str]:
    d, m, y = today_ddmmyyyy().split("/")
    months = {"01":"JAN", "02":"FEB", "03":"MAR", "04":"APR", "05":"MAY", "06":"JUN", "07":"JUL", "08":"AUG", "09":"SEP", "10":"OCT", "11":"NOV", "12":"DEC"}
    return d, months.get(m, m), y[-2:]


def _premium(data: dict[str, Any], compact: bool = False) -> str:
    n = money_number(data.get("premium", ""))
    return fmt_money(n, compact=compact) if n else _safe(data.get("premium", ""))


def _currency(data: dict[str, Any]) -> str:
    cur = _upper(data.get("currency", ""))
    if cur in {"USD", "US$"}:
        return "USD"
    return "SGD"


def _product_plan(data: dict[str, Any], product_type: str) -> str:
    if data.get("plan_name"):
        return _safe(data.get("plan_name"))
    if product_type == "HSBC":
        return "HSBC Life Indexed Flexi Income"
    return "MANULIFE INVESTREADY (III) 10 YEARS FLEXI 3"


def _stamp_image(page: fitz.Page, img: Path | None, rect: tuple[float, float, float, float]) -> None:
    if not img or not img.exists():
        return
    try:
        clean_img = _clean_image(img)
        page.insert_image(fitz.Rect(*rect), filename=str(clean_img), keep_proportion=True, overlay=True)
    except Exception:
        pass


def _fit_font_size(value: str, rect: tuple[float, float, float, float], base: float = 8.0) -> float:
    """Conservative font sizing so values stay inside small insurer-form boxes."""
    value = _safe(value)
    if not value:
        return base
    x0, y0, x1, y1 = rect
    width = max(x1 - x0 - 3, 1)
    height = max(y1 - y0, 1)
    # Approximate Helvetica width: 0.52em per character. Keep below box width.
    by_width = width / max(len(value), 1) / 0.52
    by_height = max(4.8, height * 0.62)
    return max(4.8, min(base, by_width, by_height))


def _add_text_widget(page: fitz.Page, name: str, rect: tuple[float, float, float, float], value: Any, fontsize: float = 8.0, multiline: bool = False, fill_white: bool = False) -> None:
    value = _safe(value)
    w = fitz.Widget()
    w.field_name = name
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.rect = fitz.Rect(*rect)
    w.field_value = value
    w.text_font = "helv"
    w.text_fontsize = _fit_font_size(value, rect, fontsize) if not multiline else min(fontsize, 7.0)
    w.text_color = (0, 0, 0)
    # Keep widgets printable/editable but do not add extra black borders over insurer templates.
    w.border_width = 0
    w.border_color = None
    w.fill_color = (1, 1, 1) if fill_white else None
    if multiline:
        w.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
    try:
        page.add_widget(w)
    except Exception:
        # If the exact field name collides, add a suffix and keep going.
        w.field_name = f"{name}_{abs(hash(str(rect))) % 9999}"
        try:
            page.add_widget(w)
        except Exception:
            pass


def _add_mark(page: fitz.Page, name: str, rect: tuple[float, float, float, float], checked: bool = True) -> None:
    """Draw a centered mark inside the printed checkbox.

    Text-widget X marks were previously rendered too high/low by different PDF
    viewers. Drawing two short diagonal lines keeps the mark inside the box.
    """
    if not checked:
        return
    x0, y0, x1, y1 = rect
    size = min(x1 - x0, y1 - y0)
    # Keep the mark well inside the printed checkbox. A smaller inset prevents
    # it from touching/outside the square in browser PDF renderers.
    pad = max(3.4, size * 0.38)
    width = 0.55
    page.draw_line((x0 + pad, y0 + pad), (x1 - pad, y1 - pad), color=(0, 0, 0), width=width, overlay=True)
    page.draw_line((x0 + pad, y1 - pad), (x1 - pad, y0 + pad), color=(0, 0, 0), width=width, overlay=True)


def _save_doc(doc: fitz.Document, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkstemp(suffix=".pdf")[1])
    try:
        doc.need_appearances(True)
    except Exception:
        pass
    doc.save(str(tmp), garbage=4, deflate=True)
    doc.close()
    shutil.move(str(tmp), str(output))
    return output


def _stamp_manulife_signature_fields(pdf: Path, output: Path, client_sig: Path | None, fa_sig: Path | None) -> Path:
    shutil.copyfile(pdf, output)
    doc = fitz.open(str(output))
    for page in doc:
        for w in list(page.widgets() or []):
            nm = w.field_name or ""
            if nm in {"Signature21", "Signature22"}:
                _stamp_image(page, client_sig, tuple(w.rect))
            elif nm in {"Signature23", "Representatives Signature"}:
                _stamp_image(page, fa_sig, tuple(w.rect))
    doc.saveIncr()
    doc.close()
    return output


def fill_manulife_application(data: dict[str, Any], output: Path, client_sig: Path | None = None, fa_sig: Path | None = None) -> Path:
    dob_d, dob_m, dob_y = _dob_parts(data.get("dob", ""))
    today_d, today_m, today_y = _today_parts()
    age_last = _safe(data.get("age_last_birthday"))
    if not age_last and data.get("age_next"):
        try:
            age_last = str(int(data.get("age_next")) - 1)
        except Exception:
            age_last = ""
    nat = _upper(data.get("nationality", ""))
    fields = {
        "Representatives Name 1": _upper(data.get("adviser_name")),
        "Representatives Code 1": _upper(data.get("fa_source_code")),
        "Representatives Branch": "PROMISELAND FINANCIAL ADVISORY PTE LTD",
        "is no residential address in the identification document 1": _upper(data.get("residential_address")),
        "Country": "SINGAPORE" if data.get("residential_address") else "",
        "Postal Code": data.get("postal", ""),
        "Full Name": _upper(data.get("client_name")),
        "Citizenship": "SINGAPORE" if "SINGAPORE" in nat else _upper(data.get("nationality")),
        "NRIC  Passport": _upper(data.get("nric")),
        "Country of Birth": _upper(data.get("birthplace")) or "SINGAPORE",
        "Age Last Birthday": age_last,
        "Text11": dob_d,
        "Text12": dob_m,
        "Text13": dob_y,
        "Mobile No": data.get("mobile", ""),
        "Email Address": data.get("client_email", ""),
        "Occupation": _upper(data.get("occupation")),
        "Employer": _upper(data.get("employer")),
        "Current Year S": data.get("annual_income", ""),
        "14 Net Worth": data.get("net_worth", ""),
        "Plan Name": _upper(_product_plan(data, "Manulife")),
        "Term  Premium Duration": _safe(data.get("policy_term")) or "UP TO AGE 99",
        "undefined_19": _premium(data, compact=True),
        "Fund CodeRow1": data.get("fund_code", ""),
        "Fund NameRow1": data.get("fund_name", ""),
        "Text115": data.get("fund_allocation", "100"),
        "Name  Code of Fund 1": data.get("fund_code", ""),
        "The Representative": _upper(data.get("adviser_name")),
        "of": "PROMISELAND FINANCIAL ADVISORY PTE LTD",
        "Text267": today_human().upper(),
        "Text269": today_human().upper(),
        "Representatives Name": _upper(data.get("adviser_name")),
        "Date": _upper(data.get("fa_source_code")),
        "Representatives Contact No": data.get("adviser_mobile", ""),
        "Text300": today_d,
        "Text301": today_m,
        "Text302": today_y,
    }
    gender = _safe(data.get("gender")).lower()
    marital = _safe(data.get("marital_status")).lower()
    cur = _currency(data)
    checks = {
        "FA Firm": "On",
        "Adult": "On",
        "Singaporean": "On" if "SINGAPORE" in nat and "PR" not in nat else "Off",
        "Singapore PR": "On" if "PR" in nat or "PERMANENT" in nat else "Off",
        "Self": "On",
        "Male1": "On" if gender.startswith("m") else "Off",
        "Female1": "On" if gender.startswith("f") else "Off",
        "Single": "On" if marital == "single" else "Off",
        "Married": "On" if marital == "married" else "Off",
        "Divorced": "On" if marital == "divorced" else "Off",
        "Widowed": "On" if marital == "widowed" else "Off",
        "Savings": "On",
        "Local Funds from Self": "On",
        "Employment": "On",
        "BO_NO": "On",
        "SGD": "On" if cur == "SGD" else "Off",
        "USD": "On" if cur == "USD" else "Off",
        "Bankrupt_No": "On",
        "undefined_22": "On",
        "SGD_3": "On" if cur == "SGD" else "Off",
        "USD_3": "On" if cur == "USD" else "Off",
        "Annually": "On",
        "Electronic Transfer_2": "On",
        "Electronic Transfer_3": "On",
        "The Payor is the Owner  Proposed Life Insured": "On",
        "The Payor is the Owner  Proposed Life Insured_2": "On",
        "Option 2 PayNow registered with Singapore NRIC  FIN": "On",
        "Section F - 1 - No": "On",
        "Section F - 2 - No": "On",
        "Section F - 3 - No": "On",
        "Please complete Section C  if required and D": "On",
        "I confirm that I am not a tax resident of any countryies other than the ones that I have declared above": "On",
        "Section J - 2a - No": "On",
        "Section J - 2b - No": "On",
    }
    checks = {k: v for k, v in checks.items() if v != "Off"}
    tmp = output.with_suffix(".fields.pdf")
    fill_pdf(TEMPLATE_DIR / "manulife_gio_application.pdf", tmp, fields, checks, clear_existing=True)
    _stamp_manulife_signature_fields(tmp, output, client_sig, fa_sig)
    try:
        tmp.unlink()
    except Exception:
        pass
    return output


def fill_manulife_nftf(data: dict[str, Any], output: Path, client_sig: Path | None = None, fa_sig: Path | None = None) -> Path:
    fields = {
        "Name": _upper(data.get("client_name")),
        "Name_2": _upper(data.get("client_name")),
        "NRIC  Passport Number": _upper(data.get("nric")),
        "NRIC  Passport Number_2": _upper(data.get("nric")),
        "Plan Name": _upper(_product_plan(data, "Manulife")),
        "I confirm and declare that the Representative": _upper(data.get("adviser_name")),
        "Date1": today_human().upper(),
        "Date3": today_human().upper(),
    }
    tmp = output.with_suffix(".fields.pdf")
    fill_pdf(TEMPLATE_DIR / "manulife_nftf.pdf", tmp, fields, {}, clear_existing=True)
    stamp_signatures(tmp, output, client_sig, fa_sig, kind="nftf")
    try:
        tmp.unlink()
    except Exception:
        pass
    return output


def fill_hsbc_gio(data: dict[str, Any], output: Path, client_sig: Path | None = None, fa_sig: Path | None = None) -> Path:
    template = TEMPLATE_DIR / "hsbc_gio_application.pdf"
    doc = fitz.open(str(template))
    name = _upper(data.get("client_name"))
    last, given = _split_name(name)
    dob = parse_date_ddmmyyyy(data.get("dob", ""))
    age_next = data.get("age_next") or (age_next_birthday(dob) if dob else "")
    try:
        age_last = str(int(age_next) - 1) if age_next else _safe(data.get("age_last_birthday"))
    except Exception:
        age_last = _safe(data.get("age_last_birthday"))
    page = doc[0]
    # Header / representative
    _add_text_widget(page, "hsbc_fc_org", (405, 134, 560, 150), "PROMISELAND FINANCIAL ADVISORY PTE LTD", fontsize=6.8)
    _add_text_widget(page, "hsbc_fc_name", (148, 151, 292, 168), data.get("adviser_name", ""))
    _add_text_widget(page, "hsbc_fc_code", (148, 169, 292, 185), data.get("fa_source_code", ""))
    # Life insured particulars
    _add_text_widget(page, "hsbc_li_surname", (48, 303, 132, 335), last)
    _add_text_widget(page, "hsbc_li_given", (136, 303, 290, 335), given)
    _add_text_widget(page, "hsbc_li_other", (48, 348, 290, 363), "NA")
    _add_mark(page, "hsbc_gender_m", (90, 359, 101, 371), _safe(data.get("gender")).lower().startswith("m"))
    _add_mark(page, "hsbc_gender_f", (132, 359, 143, 371), _safe(data.get("gender")).lower().startswith("f"))
    marital = _safe(data.get("marital_status")).lower()
    _add_mark(page, "hsbc_ms_single", (90, 380, 101, 392), marital == "single")
    _add_mark(page, "hsbc_ms_married", (132, 380, 143, 392), marital == "married")
    _add_mark(page, "hsbc_ms_widowed", (185, 380, 196, 392), marital == "widowed")
    _add_mark(page, "hsbc_ms_divorced", (90, 394, 101, 406), marital == "divorced")
    _add_text_widget(page, "hsbc_li_nric", (48, 411, 160, 428), data.get("nric", ""))
    _add_text_widget(page, "hsbc_li_dob", (167, 411, 292, 428), dob)
    nat = _upper(data.get("nationality")) or "SINGAPOREAN"
    _add_text_widget(page, "hsbc_li_nat1", (48, 436, 292, 451), nat)
    _add_text_widget(page, "hsbc_li_birth_country", (48, 492, 292, 506), _upper(data.get("birthplace")) or "SINGAPORE", fontsize=7.0)
    # Keep residential address on the address line only. The newer HSBC template has very tight date/postal rows;
    # appending the postal code to the address avoids text spilling into the mailing-address section.
    address_line = _upper(data.get("residential_address"))
    postal = _safe(data.get("postal"))
    if postal and postal not in address_line:
        address_line = (address_line + " " + postal).strip()
    _add_text_widget(page, "hsbc_li_address", (48, 520, 292, 538), address_line, fontsize=5.2)
    _add_text_widget(page, "hsbc_li_since", (160, 541, 205, 554), "")
    _add_text_widget(page, "hsbc_li_postal", (224, 540, 292, 554), "", fontsize=6.8)
    _add_text_widget(page, "hsbc_li_mobile", (48, 684, 160, 700), data.get("mobile", ""))
    _add_text_widget(page, "hsbc_li_email", (167, 684, 292, 700), data.get("client_email", ""), fontsize=6.8)
    

    # Employment page
    if len(doc) > 1:
        page = doc[1]
        _add_text_widget(page, "hsbc_job", (48, 65, 292, 85), _upper(data.get("occupation")))
        _add_text_widget(page, "hsbc_duties", (48, 95, 292, 115), _upper(data.get("occupation")))
        _add_mark(page, "hsbc_employed", (48, 165, 59, 177), True)
        # Keep values in the blank answer areas only. Do not place values over
        # the printed labels, which caused overlap in browser previews.
        _add_text_widget(page, "hsbc_annual_income", (103, 345, 160, 359), data.get("annual_income", ""), fontsize=7.2, fill_white=True)
        _add_mark(page, "hsbc_income_sgd", (139, 318, 149, 329), _currency(data) == "SGD")
        _add_mark(page, "hsbc_income_usd", (96, 318, 106, 329), _currency(data) == "USD")
        employer = _upper(data.get("employer"))
        if employer in {"SELF EMPLOYED", "SELF-EMPLOYED", "SELF EMPLOYED/SOLE PROPRIETOR", "SELF-EMPLOYED/SOLE PROPRIETOR"}:
            employer = ""
        _add_text_widget(page, "hsbc_employer", (198, 388, 292, 405), employer, fontsize=6.6)
        _add_mark(page, "hsbc_occ_no_change", (48, 546, 59, 557), True)

    # Plan details page
    if len(doc) > 3:
        page = doc[3]
        plan = _product_plan(data, "HSBC")
        cur = _currency(data)
        _add_text_widget(page, "hsbc_plan1_name", (155, 169, 352, 190), plan, fontsize=7.0, multiline=True)
        _add_mark(page, "hsbc_currency_usd", (157, 193, 168, 205), cur == "USD")
        _add_mark(page, "hsbc_currency_sgd", (207, 193, 218, 205), cur == "SGD")
        _add_mark(page, "hsbc_premium_single", (157, 222, 168, 234), True)
        _add_text_widget(page, "hsbc_sum_assured", (155, 262, 352, 277), data.get("sum_assured", ""))
        _add_text_widget(page, "hsbc_policy_term", (155, 303, 352, 318), data.get("policy_term", ""))
        _add_text_widget(page, "hsbc_premium_amount", (155, 318, 352, 333), _premium(data), fontsize=8)
        _add_text_widget(page, "hsbc_age_last", (265, 331, 352, 345), age_last)
        _add_text_widget(page, "hsbc_age_next", (265, 345, 352, 359), age_next)
        # Common IUL allocation - editable if user needs to amend.
        # Leave specific account allocation rows blank unless reliable allocation can be extracted; keep only total.
        _add_text_widget(page, "hsbc_allocation_general", (312, 525, 352, 539), "")
        # Leave allocation total blank unless a precise row mapping is available;
        # the previous automatic 100 overlapped the template rows in some viewers.
        _add_text_widget(page, "hsbc_allocation_total", (312, 632, 352, 646), "")

    # Signature/declaration page in the 12-page form.
    if len(doc) > 11:
        page = doc[11]
        _add_text_widget(page, "hsbc_sig_life_name", (48, 690, 270, 716), name)
        _add_text_widget(page, "hsbc_sig_life_date", (292, 690, 407, 716), today_ddmmyyyy())
        _add_text_widget(page, "hsbc_sig_life_city", (424, 690, 560, 716), "SINGAPORE")
        _add_text_widget(page, "hsbc_sig_rep_name", (48, 785, 270, 812), _upper(data.get("adviser_name")))
        _add_text_widget(page, "hsbc_sig_rep_date", (292, 785, 407, 812), today_ddmmyyyy())
        _add_text_widget(page, "hsbc_sig_rep_city", (424, 785, 560, 812), "SINGAPORE")
        _stamp_image(page, client_sig, (50, 662, 160, 690))
        _stamp_image(page, fa_sig, (50, 758, 160, 785))

    return _save_doc(doc, output)


def fill_hsbc_acknowledgement(data: dict[str, Any], output: Path, client_sig: Path | None = None, fa_sig: Path | None = None) -> Path:
    doc = fitz.open(str(TEMPLATE_DIR / "hsbc_customer_acknowledgement.pdf"))
    plan = _product_plan(data, "HSBC").lower()
    page = doc[0]
    _add_mark(page, "ack_emerald", (53, 127, 65, 140), "emerald" in plan)
    _add_mark(page, "ack_diamond", (53, 231, 65, 244), "diamond" in plan or "iul" in plan)
    _add_mark(page, "ack_indexed_flexi", (53, 418, 65, 431), "indexed" in plan or "flexi income" in plan)
    # If no specific campaign can be inferred, leave campaign boxes blank for manual editing.
    if len(doc) > 1:
        page = doc[1]
        _add_text_widget(page, "ack_customer_name", (36, 132, 250, 150), _upper(data.get("client_name")), fontsize=7.2)
        _add_text_widget(page, "ack_customer_nric", (36, 205, 250, 222), _upper(data.get("nric")), fontsize=7.2)
        _add_text_widget(page, "ack_rep_name", (36, 280, 250, 298), _upper(data.get("adviser_name")), fontsize=6.6)
        _add_text_widget(page, "ack_date", (430, 132, 520, 150), today_ddmmyyyy(), fontsize=7.2)
        _stamp_image(page, client_sig, (40, 110, 145, 137))
    return _save_doc(doc, output)


def fill_hsbc_e_sign_consent(data: dict[str, Any], output: Path, client_sig: Path | None = None, fa_sig: Path | None = None) -> Path:
    doc = fitz.open(str(TEMPLATE_DIR / "hsbc_e_signing_consent.pdf"))
    page = doc[0]
    plan = _product_plan(data, "HSBC")
    name = _upper(data.get("client_name"))
    _add_text_widget(page, "esign_life_name", (120, 170, 300, 190), name)
    _add_text_widget(page, "esign_life_nric", (392, 170, 530, 190), _upper(data.get("nric")))
    _add_text_widget(page, "esign_policy_no", (120, 225, 300, 245), data.get("policy_number", ""))
    _add_text_widget(page, "esign_plan", (438, 232, 558, 248), plan, fontsize=5.8)
    # Bottom name labels have no safe blank line; keep blank to avoid overlap.
    _add_text_widget(page, "esign_life_date", (74, 527, 155, 544), today_ddmmyyyy(), fontsize=7.0)
    # Representative name is already captured elsewhere; do not overlap the long bottom label.
    _add_text_widget(page, "esign_rep_date", (430, 527, 515, 544), today_ddmmyyyy(), fontsize=7.0)
    _stamp_image(page, client_sig, (42, 490, 150, 526))
    _stamp_image(page, fa_sig, (392, 490, 508, 526))
    return _save_doc(doc, output)


def fill_hsbc_nftf(data: dict[str, Any], output: Path, client_sig: Path | None = None, fa_sig: Path | None = None) -> Path:
    doc = fitz.open(str(TEMPLATE_DIR / "hsbc_nftf.pdf"))
    page = doc[0]
    _add_text_widget(page, "nftf_assured", (226, 150, 518, 164), _upper(data.get("client_name")), fontsize=7.0)
    _add_text_widget(page, "nftf_life_insured", (226, 177, 518, 200), _upper(data.get("client_name")), fontsize=7.0)
    _add_text_widget(page, "nftf_rep", (226, 214, 518, 228), _upper(data.get("adviser_name")), fontsize=6.8)
    # Date / start / end time rows are intentionally left blank to avoid placing values across tight table rules; they remain available for manual completion.
    # Names are not printed in the bottom date/signature label row to avoid overlap.
    # Representative name is filled in the top section; keep bottom label row clear.
    _stamp_image(page, client_sig, (92, 672, 210, 715))
    _stamp_image(page, fa_sig, (383, 672, 505, 715))
    return _save_doc(doc, output)


def generate_insurer_forms(product_type: str, data: dict[str, Any], job_dir: Path, client_safe_name: str, client_sig: Path | None = None, fa_sig: Path | None = None) -> list[Path]:
    product = _safe(product_type).lower()
    outputs: list[Path] = []
    if product == "manulife":
        gio = job_dir / f"{client_safe_name}_Manulife_GIO_Application.pdf"
        nftf = job_dir / f"{client_safe_name}_Manulife_NFTF.pdf"
        fill_manulife_application(data, gio, client_sig, fa_sig)
        fill_manulife_nftf(data, nftf, client_sig, fa_sig)
        outputs.extend([gio, nftf])
    elif product == "hsbc":
        gio = job_dir / f"{client_safe_name}_HSBC_GIO_Application.pdf"
        ack = job_dir / f"{client_safe_name}_HSBC_Customer_Acknowledgement.pdf"
        consent = job_dir / f"{client_safe_name}_HSBC_E_Signing_Consent.pdf"
        nftf = job_dir / f"{client_safe_name}_HSBC_NFTF.pdf"
        fill_hsbc_gio(data, gio, client_sig, fa_sig)
        fill_hsbc_acknowledgement(data, ack, client_sig, fa_sig)
        fill_hsbc_e_sign_consent(data, consent, client_sig, fa_sig)
        fill_hsbc_nftf(data, nftf, client_sig, fa_sig)
        outputs.extend([gio, ack, consent, nftf])
    return outputs
