from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import fitz
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from .settings import TEMPLATE_DIR
from .extractor import money_number, fmt_money, norm_money
from .compliance_rules import PRIORITY_FIELD_MAP, classify_product


BOR_FIELD = (
    "Business Trail and why was the products andor funds selected Cont If the client has any deviation "
    "from your recommendations please also note down the reason here Please include any factors which may "
    "significantly increase or decrease the clients income and expense  assets and liabilities in the next "
    "12 months that may impact the clients affordability eg inheritance proceeds from the sale of a property "
    "or planning to purchase of a property"
)
BOR_FIELD_ALT = BOR_FIELD.replace("expense  assets", "expense assets")


def today_ddmmyyyy() -> str:
    return date.today().strftime("%d/%m/%Y")


def today_human() -> str:
    # %-d is supported on Railway/Linux. Keep a portable fallback for Windows dev machines.
    try:
        return date.today().strftime("%-d %B %Y")
    except Exception:
        return date.today().strftime("%d %B %Y").lstrip("0")


def set_need_appearances(writer: PdfWriter) -> None:
    try:
        root = writer._root_object
        acro = root.get("/AcroForm")
        if acro is None:
            acro = DictionaryObject()
            root[NameObject("/AcroForm")] = acro
        acro.update({NameObject("/NeedAppearances"): BooleanObject(True)})
    except Exception:
        pass


def _fitz_font_size(value: str, rect) -> float:
    value = str(value or "")
    w = max(float(rect.x1 - rect.x0), 1.0)
    h = max(float(rect.y1 - rect.y0), 1.0)
    n = max(len(value), 1)
    if h > 120:
        return 6.2
    if n > 250:
        return 5.8
    if n > 120:
        return 6.3
    if h <= 14:
        return max(5.0, min(7.0, w / n * 1.25))
    if h <= 20:
        return max(6.0, min(8.0, w / n * 1.45))
    if n > 60:
        return 7.0
    return 8.0


def _checkbox_on_value(widget) -> str:
    try:
        states = widget.button_states() or {}
        normal = states.get("normal") or []
        for val in normal:
            if val and str(val).lower() != "off":
                return str(val)
    except Exception:
        pass
    return "On"


def fill_pdf(
    template: Path,
    output: Path,
    field_values: dict[str, Any],
    checkbox_values: dict[str, str] | None = None,
    clear_existing: bool = False,
) -> Path:
    """Fill AcroForm widgets while keeping them editable.

    Compliance change: we no longer stamp duplicate visible text over editable fields.  PyMuPDF
    generates the widget appearances directly, so a later manual edit does not leave stale text behind.
    """
    checkbox_values = checkbox_values or {}
    text_values = {
        str(k): str(v)
        for k, v in field_values.items()
        if v is not None and str(v) != ""
    }
    check_values = {
        str(k): str(v)
        for k, v in checkbox_values.items()
        if v is not None and str(v) not in ("", "Off", "/Off")
    }
    all_names = set(text_values) | set(check_values)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(template))
    for page in doc:
        for widget in list(page.widgets() or []):
            name = widget.field_name
            if not name:
                continue
            try:
                if clear_existing:
                    if widget.field_type_string in ("CheckBox", "RadioButton"):
                        widget.field_value = False
                    else:
                        widget.field_value = ""
                    widget.update()

                if name not in all_names:
                    continue
                if name in check_values or widget.field_type_string in ("CheckBox", "RadioButton"):
                    if name in check_values:
                        widget.field_value = _checkbox_on_value(widget)
                        widget.update()
                    continue

                value = text_values.get(name, "")
                widget.field_value = value
                try:
                    widget.text_font = "Helv"
                except Exception:
                    pass
                try:
                    widget.text_fontsize = _fitz_font_size(value, widget.rect)
                except Exception:
                    pass
                widget.update()
            except Exception:
                continue
    doc.save(str(output), garbage=4, deflate=True)
    doc.close()
    return output


def _field_widgets(template: Path):
    try:
        reader = PdfReader(str(template))
        for page_index, page in enumerate(reader.pages):
            height = float(page.mediabox.height)
            for aref in page.get("/Annots") or []:
                try:
                    annot = aref.get_object()
                    name = annot.get("/T")
                    parent = annot.get("/Parent")
                    if not name and parent:
                        name = parent.get_object().get("/T")
                    if not name:
                        continue
                    ft = annot.get("/FT") or (parent.get_object().get("/FT") if parent else None)
                    rect = [float(x) for x in annot.get("/Rect")]
                    yield str(name), page_index, height, rect, str(ft)
                except Exception:
                    continue
    except Exception:
        return


def _text_font_size(value: str, rect) -> float:
    w = max(rect[2] - rect[0], 1)
    h = max(rect[3] - rect[1], 1)
    val_len = max(len(value), 1)
    if val_len > 300:
        return 6.0
    if val_len > 120:
        return 6.5
    if h <= 16:
        return max(4.2, min(8.0, (w / val_len) * 1.25))
    if val_len > 60:
        return 7.0
    if w < 70:
        return 7.0
    return 8.0


def overlay_visible_values(template: Path, pdf_path: Path, values: dict[str, str]) -> None:
    """Compatibility no-op.

    Older builds used a second non-editable text layer to compensate for browser appearance bugs.
    That made later edits look duplicated/wonky.  ``fill_pdf`` now updates widget appearances itself.
    """
    return None


def _clean_image(path: Path) -> Path:
    if not path or not path.exists():
        return path
    try:
        im = Image.open(path).convert("RGBA")
        new = []
        for r, g, b, a in im.getdata():
            if r > 245 and g > 245 and b > 245:
                new.append((255, 255, 255, 0))
            else:
                new.append((r, g, b, a))
        im.putdata(new)
        out = path.with_suffix(".clean.png")
        im.save(out)
        return out
    except Exception:
        return path


def _widget_checked(widget) -> bool:
    try:
        v = str(widget.field_value or "").strip().lower()
        return bool(v and v not in {"off", "/off", "false", "0", "none"})
    except Exception:
        return False


def _checked_names(doc: fitz.Document) -> set[str]:
    out: set[str] = set()
    for page in doc:
        for w in list(page.widgets() or []):
            if w.field_name and w.field_type_string in ("CheckBox", "RadioButton") and _widget_checked(w):
                out.add(w.field_name)
    return out


def _insert_signature_at_widget(doc: fitz.Document, field_name: str, img: Path | None, pad: float = 1.0) -> bool:
    if not img or not img.exists():
        return False
    inserted = False
    for page in doc:
        for widget in list(page.widgets() or []):
            if widget.field_name != field_name:
                continue
            rect = fitz.Rect(widget.rect)
            rect.x0 += pad
            rect.x1 -= pad
            rect.y0 += pad
            rect.y1 -= pad
            if rect.width <= 2 or rect.height <= 2:
                rect = fitz.Rect(widget.rect)
            try:
                page.insert_image(rect, filename=str(img), keep_proportion=True, overlay=True)
                inserted = True
            except Exception:
                pass
    return inserted


def stamp_signatures(
    pdf_path: Path,
    output: Path,
    client_sig: Path | None = None,
    fa_sig: Path | None = None,
    kind: str = "tfp",
) -> Path:
    """Stamp signatures into the form's actual signature widgets where available.

    The same client signature is deliberately NOT copied into joint-client signature slots. A joint
    case needs a separate joint signature/CKA and is flagged by the compliance preflight.
    """
    shutil.copyfile(pdf_path, output)
    doc = fitz.open(str(output))
    c_sig = _clean_image(client_sig) if client_sig else None
    f_sig = _clean_image(fa_sig) if fa_sig else None

    if kind == "tfp":
        checked = _checked_names(doc)

        # Core client acknowledgements/declarations.
        for name in ("Signature19", "Signature184", "Clients Signature"):
            _insert_signature_at_widget(doc, name, c_sig)

        # CKA signature only when a deterministic CKA outcome is actually filled.
        if "Yes7" in checked or "No7" in checked:
            _insert_signature_at_widget(doc, "Signature36", c_sig)

        # Use the applicable disclosure checklist only.
        if "Check Box42" in checked:
            _insert_signature_at_widget(doc, "Signature2", c_sig)
        if "Check Box43" in checked:
            _insert_signature_at_widget(doc, "Signature4", c_sig)

        # Adviser declarations / acknowledgement.
        for name in ("FA Representatives Signature", "Signature191"):
            _insert_signature_at_widget(doc, name, f_sig)
    elif kind == "checklist":
        # External checklist templates supplied previously do not consistently expose a signature widget.
        if f_sig and f_sig.exists() and len(doc):
            doc[0].insert_image(fitz.Rect(260, 650, 340, 710), filename=str(f_sig), keep_proportion=True, overlay=True)
    elif kind == "special":
        if len(doc) > 1:
            if f_sig and f_sig.exists():
                doc[1].insert_image(fitz.Rect(170, 700, 250, 755), filename=str(f_sig), keep_proportion=True, overlay=True)
            if c_sig and c_sig.exists():
                doc[1].insert_image(fitz.Rect(310, 700, 410, 755), filename=str(c_sig), keep_proportion=True, overlay=True)
    elif kind == "nftf":
        if len(doc):
            if c_sig and c_sig.exists():
                doc[0].insert_image(fitz.Rect(70, 675, 170, 745), filename=str(c_sig), keep_proportion=True, overlay=True)
            if f_sig and f_sig.exists():
                doc[0].insert_image(fitz.Rect(435, 675, 535, 745), filename=str(f_sig), keep_proportion=True, overlay=True)

    doc.saveIncr()
    doc.close()
    return output


def check(cb: str) -> str:
    return cb


def _money_text(value: Any, compact: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    n = money_number(raw)
    if n == 0 and raw not in {"0", "0.0", "0.00"}:
        return raw
    return fmt_money(n, compact=compact)


def _bool_cb(cb: dict[str, str], true_name: str, false_name: str, value: bool | None) -> None:
    if value is True:
        cb[true_name] = true_name
    elif value is False:
        cb[false_name] = false_name


def _priority_checkboxes(data: dict[str, Any], cb: dict[str, str]) -> None:
    priorities = data.get("priorities") or {}
    if not isinstance(priorities, dict):
        return
    for row, level in priorities.items():
        level = str(level or "").lower().replace("n/a", "na")
        field = PRIORITY_FIELD_MAP.get(row, {}).get(level)
        if field:
            cb[field] = field


def _financial_disclosure_checkboxes(data: dict[str, Any], cb: dict[str, str]) -> None:
    partial = data.get("financial_disclosure_partial")
    has_cashflow = bool(data.get("annual_income") or data.get("annual_expenses") or data.get("annual_surplus"))
    has_assets = bool(
        data.get("personal_use_assets")
        or data.get("investment_assets")
        or data.get("cpf_total")
        or data.get("other_assets")
        or data.get("total_assets")
        or data.get("loans")
        or data.get("other_liabilities")
        or data.get("total_liabilities")
        or data.get("net_assets")
    )
    if partial is True:
        cb["1R"] = "1R"
        cb["1R_4"] = "1R_4"
    else:
        if has_cashflow:
            cb["HV"] = "HV"
        if has_assets:
            cb["HV_4"] = "HV_4"


def _fund_rows(data: dict[str, Any], profile, fields: dict[str, Any]) -> None:
    funds = data.get("funds") or []
    if not isinstance(funds, list):
        funds = []
    if not funds and data.get("fund_name"):
        funds = [{
            "name": data.get("fund_name", ""),
            "asset_class": data.get("asset_class", ""),
            "amount": data.get("fund_invested_amount", ""),
        }]

    for idx, fund in enumerate(funds[:7], start=1):
        if not isinstance(fund, dict):
            continue
        name = str(fund.get("name") or "").strip()
        asset = str(fund.get("asset_class") or "").strip()
        amount = str(fund.get("amount") or "").strip()
        if not amount and idx == 1 and profile.category in {"ilp", "unit_trust"}:
            # The product premium is the only safe amount fallback; never fabricate a 100% allocation.
            amount = str(data.get("premium") or "").strip()
        if profile.category == "unit_trust":
            fields[f"UT {idx}"] = "IFAST (UT)" if profile.key == "ifast_unit_trust" else "UT"
        elif profile.category == "ilp":
            fields[f"UT {idx}"] = "ILP"
        if name:
            fields[f"Name of Fund Manager  Investment Product{idx}"] = name
        if amount:
            fields[f"RSP {idx}"] = _money_text(amount, compact=False)
        asset_field = "Asset Class" if idx == 1 else f"Asset Class_{idx}"
        if asset:
            fields[asset_field] = asset


def _premium_display(data: dict[str, Any], profile) -> str:
    premium = str(data.get("premium") or "").strip()
    if not premium:
        return ""
    amount = _money_text(premium, compact=False)
    mode = str(data.get("premium_mode") or profile.premium_mode or "").lower()
    frequency = str(data.get("premium_frequency") or "").lower()
    if mode == "single" or "single" in frequency:
        return f"{amount} SP"
    if mode == "annual" or any(x in frequency for x in ("annual", "year")):
        return f"{amount}/year"
    return amount


def tfp_field_map(data: dict[str, Any], product_type: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Map enriched case data to TFP fields without inventing compliance facts."""
    profile = classify_product(data, product_type)
    name = str(data.get("client_name") or "")
    nric = str(data.get("nric") or "")
    fa = str(data.get("adviser_name") or "")
    plan = str(data.get("plan_name") or profile.label)
    insurer = str(data.get("insurer_name") or profile.company or product_type)
    page13 = data.get("page13") if isinstance(data.get("page13"), dict) else {}
    today = today_ddmmyyyy()

    # Premium from the insurer/platform document is a safe budget-amount fallback.  The funding
    # source still has to be supported by the uploaded data and is never invented.
    premium_mode = str(data.get("premium_mode") or profile.premium_mode or "").lower()
    source_of_funds = data.get("source_of_funds", "") or data.get("source_of_income", "")
    annual_budget_value = data.get("annual_budget", "")
    annual_budget_source = data.get("annual_budget_source", "")
    single_budget_value = data.get("single_budget", "")
    single_budget_source = data.get("single_budget_source", "")
    if premium_mode == "annual":
        annual_budget_value = annual_budget_value or data.get("premium", "")
        annual_budget_source = annual_budget_source or source_of_funds
    elif premium_mode == "single":
        single_budget_value = single_budget_value or data.get("premium", "")
        single_budget_source = single_budget_source or source_of_funds

    fields: dict[str, Any] = {
        # Cover / parties
        "Clientname": name,
        "FAname": fa,
        "Client 2": data.get("joint_client_name", ""),
        "FA 2": data.get("co_adviser_name", ""),
        "NRIC": nric,
        "NRICS": data.get("joint_nric", ""),
        # Personal particulars
        "undefined_2": data.get("nationality", ""),
        "Date of Birth  GG PPP": data.get("dob", ""),
        "undefined_4": data.get("birthplace", ""),
        "Age Next Birthday ANB": data.get("age_next", ""),
        "Residential Address": data.get("residential_address", ""),
        "Postal Code": data.get("postal", ""),
        "undefined_7": data.get("mobile", ""),
        "undefined_8": data.get("client_email", ""),
        "undefined_9": data.get("occupation", ""),
        "undefined_10": data.get("employer", ""),
        "if retired  unemployed": data.get("source_of_income", ""),
        "Highest Education Level": data.get("education", ""),
        # Page 8 - actual financial profile only
        "Text119": _money_text(data.get("annual_income")),
        "Text25": _money_text(data.get("annual_expenses")),
        "Text27": _money_text(data.get("annual_surplus")),
        "Text115": data.get("financial_disclosure_note", ""),
        "Text118": data.get("financial_disclosure_note", ""),
        "Text121": _money_text(data.get("personal_use_assets"), compact=True),
        "Text123": _money_text(data.get("investment_assets"), compact=True),
        "Text125": _money_text(data.get("cpf_total"), compact=True),
        "Text127": _money_text(data.get("other_assets"), compact=True),
        "Text129": _money_text(data.get("total_assets"), compact=True),
        "Text131": _money_text(data.get("loans"), compact=True),
        "Text133": _money_text(data.get("other_liabilities"), compact=True),
        "Text135": _money_text(data.get("total_liabilities"), compact=True),
        "Text137": _money_text(data.get("net_assets"), compact=True),
        "Text150": _money_text(annual_budget_value, compact=True),
        "Text152": annual_budget_source,
        "Text154": _money_text(single_budget_value, compact=True),
        "Text156": single_budget_source,
        "Text116": data.get("future_changes_reason", ""),
        # Common TFP assumptions retained from the approved reference templates.
        "Text3000": data.get("life_expectancy_assumption", "3"),
        "Text3111": data.get("inflation_assumption", "3"),
        "Text3222": data.get("education_inflation_assumption", "NA"),
        "Text322": data.get("education_return_assumption", "0"),
        # Page 9 retirement - only supported values
        "fill_27": data.get("retirement_amt", ""),
        "fill_29": data.get("retirement_income", ""),
        "fill_311": data.get("retirement_shortfall", ""),
        "Text306": data.get("retirement_years", ""),
        "fill_33": data.get("retirement_total_amt", ""),
        "fill_35": data.get("retirement_other_sources", ""),
        "fill_37": data.get("retirement_amt_plan", ""),
        # Page 9 investment-needs FNA
        "fill_39": data.get("investment_goal", ""),
        "Text308": data.get("investment_duration_years", ""),
        "fill_41": data.get("investment_existing", ""),
        "fill_43": data.get("investment_amount_to_plan", ""),
        # Page 10 / Page 13 risk
        "S  L  JO": data.get("risk_profile", ""),
        "5 Clients Risk Profile": data.get("risk_profile", ""),
        # Page 13 recommendation
        "Name of Products": plan,
        "Company1": insurer,
        "fill_22_2": data.get("sum_assured", ""),
        "fill_23": _premium_display(data, profile),
        "Text37": page13.get("objective", ""),
        "Text38": page13.get("time_horizon", ""),
        "Text39": page13.get("features", ""),
        "Text40": page13.get("limitations", ""),
        "6 Clients Expected Rate of Return": page13.get("expected_return", ""),
        "7 Sales Charges  WRAP  Platform Fee": page13.get("charges", ""),
        "7 Sales Charges WRAP Platform Fee": page13.get("charges", ""),
        "8 The Nature of Product  Investment Risk": page13.get("investment_risk", ""),
        "8 The Nature of Product Investment Risk": page13.get("investment_risk", ""),
        "Text41": page13.get("other_limitations", ""),
        BOR_FIELD: data.get("recommendation_text", ""),
        BOR_FIELD_ALT: data.get("recommendation_text", ""),
        "date": today,
        # Dates beside signatures/acknowledgements generated by this workflow.
        "Date21_af_client_1": today,
        "Date21_af_client_5": today,
        "Date21_af_client_6": today,
        "Date23_af_client_1": today,
        "Date23_af_client": today,
    }

    # Only date CKA / disclosure checklist when those sections are actually applicable.
    if isinstance(data.get("cka_met"), bool) and profile.requires_cka:
        fields["Date21_af_client_2"] = today
    if profile.disclosure_checklist == "life":
        fields["Date21_af_client_3"] = today
    elif profile.disclosure_checklist == "unit_trust":
        fields["Date21_af_client_4"] = today

    _fund_rows(data, profile, fields)

    cb: dict[str, str] = {}

    # FA declaration category - one applicable category, not every category.
    if profile.category == "unit_trust":
        cb["Collective Investment"] = "Collective Investment"
    elif profile.category in {"ilp", "life", "participating_life"}:
        cb["Life Insurance  InvestmentLinked ILP"] = "Life Insurance  InvestmentLinked ILP"

    # Personal particulars: only facts actually known.
    gender = str(data.get("gender") or "").lower()
    if gender.startswith("m"):
        cb["Male"] = "Male"
    elif gender.startswith("f"):
        cb["Female"] = "Female"
    smoker = str(data.get("smoker") or "").lower()
    if smoker in {"no", "n", "non-smoker", "nonsmoker", "non smoker"}:
        cb["No"] = "No"
    elif smoker in {"yes", "y", "smoker"}:
        cb["Yes"] = "Yes"

    marital = str(data.get("marital_status") or "").lower()
    marital_map = {"single": "Single", "married": "Married", "widowed": "Widowed", "divorced": "Divorced"}
    if marital in marital_map:
        cb[marital_map[marital]] = marital_map[marital]

    status = str(data.get("employment_status") or "").lower()
    if status.startswith("full"):
        cb["FullTime"] = "FullTime"
    elif status.startswith("retired"):
        cb["Retired"] = "Retired"

    english = data.get("english")
    if str(english or "").lower() in {"yes", "y", "true", "proficient"}:
        cb["yes1"] = "yes1"

    _priority_checkboxes(data, cb)
    _financial_disclosure_checkboxes(data, cb)

    affordability = data.get("affordability") if isinstance(data.get("affordability"), dict) else {}
    substantial = affordability.get("budget_substantial")
    if substantial is True:
        cb["Y11"] = "Y11"
    elif substantial is False:
        cb["N11"] = "N11"

    _bool_cb(cb, "HV_2", "1R_2", data.get("future_changes") if isinstance(data.get("future_changes"), bool) else None)

    # Page 10 risk answers.
    rr = str(data.get("risk_return_preference") or "").upper()[:1]
    rt = str(data.get("risk_taking_preference") or "").upper()[:1]
    rr_map = {"H": "Check Box37", "M": "Check Box38", "L": "Check Box39"}
    rt_map = {"H": "Check Box433", "M": "Check Box455", "L": "Check Box466"}
    if rr in rr_map:
        cb[rr_map[rr]] = rr_map[rr]
    if rt in rt_map:
        cb[rt_map[rt]] = rt_map[rt]

    # Page 11 CKA: only if each answer/outcome is known. No made-up CKA failure.
    if profile.requires_cka:
        _bool_cb(cb, "Yes3", "No3", data.get("cka_education") if isinstance(data.get("cka_education"), bool) else None)
        _bool_cb(cb, "Yes4", "No4", data.get("cka_professional_qualification") if isinstance(data.get("cka_professional_qualification"), bool) else None)
        _bool_cb(cb, "Yes5", "No5", data.get("cka_investment_experience") if isinstance(data.get("cka_investment_experience"), bool) else None)
        _bool_cb(cb, "Yes6", "No6", data.get("cka_work_experience") if isinstance(data.get("cka_work_experience"), bool) else None)
        _bool_cb(cb, "Yes7", "No7", data.get("cka_met") if isinstance(data.get("cka_met"), bool) else None)
        # Page 12 choice (advice/suitability/proceed) intentionally remains blank unless explicitly supplied.
        ack = str(data.get("cka_acknowledgement") or "").lower()
        ack_map = {
            "pass_no_advice": "Yes8",
            "pass_advice": "No8",
            "pass_suitable": "Yes9",
            "pass_not_suitable": "No9",
            "fail_proceed": "Check Box5",
            "fail_suitable": "Yes10",
            "fail_not_suitable": "No10",
        }
        if ack in ack_map:
            cb[ack_map[ack]] = ack_map[ack]

    # Applicable disclosure checklist only; never tick both.
    if profile.disclosure_checklist == "life":
        cb["Check Box42"] = "Check Box42"
    elif profile.disclosure_checklist == "unit_trust":
        cb["Check Box43"] = "Check Box43"

    # Source of funds declaration: tick only a supported category.
    source = str(data.get("source_of_funds") or data.get("source_of_income") or "").lower()
    if any(x in source for x in ("salary", "employment", "trade", "business income")):
        cb["Employment  Trade Income"] = "Employment  Trade Income"
    elif "investment" in source or "dividend" in source:
        cb["Investment Income"] = "Investment Income"
    elif any(x in source for x in ("saving", "cash", "asset", "cpf")):
        cb["Savings"] = "Savings"

    return {k: v for k, v in fields.items() if v is not None and str(v) != ""}, cb


def checklist_map(data: dict[str, Any], product_type: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Map the previously supplied insurer submission checklist.

    This keeps legacy output compatibility while using the detected product category for the CKA line.
    """
    profile = classify_product(data, product_type)
    name = data.get("client_name", "")
    nric = data.get("nric", "")
    plan = data.get("plan_name") or profile.label
    fields = {
        "1": str(plan).upper(),
        "Name of Proposer": name,
        "NRIC No": nric,
        "Name of Life Assured": name,
        "NRIC No_2": nric,
        "Quantity SubmittedApplication for Life Insurance Proposal Forms": "1",
        "Quantity SubmittedBenefit Illustration and Product Summary": "1",
        "Quantity SubmittedIdentity Card  Driving License  Passport": "1",
        "Quantity SubmittedThe Financial Planner Form for PLD use only": "1",
        "Quantity SubmittedClient Knowledge Assessment Form ILP cases": "1" if profile.requires_cka else "",
        "Quantity SubmittedNon Face to Face Advisory Form": "1" if product_type == "Manulife" else "",
        "Quantity SubmittedOthers": "1",
        "Quantity SubmittedOthers_2": "1" if product_type == "Manulife" else "",
        "Quantity SubmittedOthers_3": "1" if product_type == "Manulife" else "",
        "ch2": "SPECIAL DISCLOSURE" if product_type == "FWD" else "EMAIL TRAIL",
        "o2": "PROOF OF DISCLOSURE" if product_type == "Manulife" else "",
        "o3": "SPECIAL DISCLOSURE" if product_type == "Manulife" else "",
        "namefa": data.get("adviser_name", ""),
        "sourcecode": data.get("fa_source_code", ""),
        "d1": today_ddmmyyyy(),
        "o1": "$",
    }
    cb = {
        "New": "On" if product_type == "Manulife" else "New",
        "Softcopy": "On" if product_type == "Manulife" else "Softcopy",
    }
    if product_type == "Manulife":
        cb.update({"Manulife": "On", "c1": "On", "c2": "On", "c4": "On", "c6": "On", "c9": "On", "c11": "On", "c12": "On", "c13": "On"})
    elif product_type == "FWD":
        cb.update({"Insurer Platform": "Insurer Platform", "FWD": "FWD", "c7": "c7", "c11": "c11"})
    return {k: v for k, v in fields.items() if v != ""}, cb


def special_disclosure_manulife(
    data: dict[str, Any],
    output: Path,
    client_sig: Path | None,
    fa_sig: Path | None,
) -> Path:
    fields = {
        "fa_name": data.get("adviser_name", ""),
        "client_name": data.get("client_name", ""),
        "date_today_1": today_ddmmyyyy(),
        "date_today_2": today_ddmmyyyy(),
    }
    tmp = output.with_suffix(".fields.pdf")
    fill_pdf(TEMPLATE_DIR / "special_disclosure_manulife.pdf", tmp, fields, {})
    stamp_signatures(tmp, output, client_sig, fa_sig, kind="special")
    try:
        tmp.unlink()
    except Exception:
        pass
    return output


def build_special_disclosure_simple(
    data: dict[str, Any],
    output: Path,
    product_type: str,
    client_sig: Path | None,
    fa_sig: Path | None,
) -> Path:
    """Legacy simple FWD disclosure; product facts remain sourced from BI/Product Summary."""
    c = canvas.Canvas(str(output), pagesize=A4)
    _w, h = A4
    text = c.beginText(25 * mm, h - 25 * mm)
    text.setFont("Helvetica-Bold", 14)
    text.textLine("SPECIAL DISCLOSURE")
    text.setFont("Helvetica", 10)
    body = [
        "(Investment-Linked Plan)",
        "",
        "About ILPs",
        "An ILP is a life insurance policy that provides a combination of protection and investment.",
        "",
        "Returns",
        "Fund prices may go down and up depending upon investment performance. Past performance is not an indication of future performance.",
        "You may get back less than you have paid in.",
        "",
        "Fees and Charges",
        "Fees and charges may apply. Please refer to the Policy Illustration and Product Summary for the exact product-specific details.",
        "",
        "Premium Payment",
        "Please refer to the Product Summary for premium requirements, premium-holiday conditions, deductions and lapse consequences.",
        "",
        "Surrender / Withdrawal",
        "Please refer to the Product Summary for the applicable surrender, withdrawal and minimum investment period conditions.",
        "",
        "Free-look Period",
        "Please refer to the insurer's policy documents for the applicable free-look terms and refund adjustments.",
    ]
    for line in body:
        chunks = re.findall(r".{1,96}(?:\s+|$)", line) or [""]
        for sub in chunks:
            text.textLine(sub.strip())
    c.drawText(text)
    c.showPage()
    c.setFont("Helvetica-Bold", 12)
    c.drawString(25 * mm, h - 25 * mm, "CLIENT ACKNOWLEDGEMENT")
    c.setFont("Helvetica", 10)
    ack = (
        "I/we confirm that I/we have read the relevant product documents about the product structure, "
        "benefits, premiums, premium term, policy term, flexibility, fees and charges and investment funds."
    )
    y = h - 40 * mm
    for sub in re.findall(r".{1,100}(?:\s+|$)", ack):
        c.drawString(25 * mm, y, sub.strip())
        y -= 6 * mm
    y -= 10 * mm
    c.rect(25 * mm, y - 38 * mm, 160 * mm, 38 * mm)
    for x in [65 * mm, 105 * mm, 145 * mm]:
        c.line(x, y, x, y - 38 * mm)
    for yy in [y - 10 * mm, y - 24 * mm]:
        c.line(25 * mm, yy, 185 * mm, yy)
    c.drawString(30 * mm, y - 7 * mm, "Signature:")
    c.drawString(30 * mm, y - 20 * mm, "Name:")
    c.drawString(30 * mm, y - 33 * mm, "Date:")
    c.drawString(76 * mm, y - 7 * mm, "Advisor")
    c.drawString(114 * mm, y - 7 * mm, "PolicyHolder 1")
    c.drawString(152 * mm, y - 7 * mm, "PolicyHolder 2")
    c.acroform.textfield(name="fa_name", x=66 * mm, y=y - 23 * mm, width=38 * mm, height=8 * mm, value=data.get("adviser_name", ""), borderWidth=0, fontSize=8)
    c.acroform.textfield(name="client_name", x=106 * mm, y=y - 23 * mm, width=38 * mm, height=8 * mm, value=data.get("client_name", ""), borderWidth=0, fontSize=8)
    c.acroform.textfield(name="date_today_1", x=66 * mm, y=y - 36 * mm, width=38 * mm, height=8 * mm, value=today_ddmmyyyy(), borderWidth=0, fontSize=8)
    c.acroform.textfield(name="date_today_2", x=106 * mm, y=y - 36 * mm, width=38 * mm, height=8 * mm, value=today_ddmmyyyy(), borderWidth=0, fontSize=8)
    c.save()
    stamped = output.with_suffix(".stamped.pdf")
    stamp_signatures(output, stamped, client_sig, fa_sig, kind="special")
    shutil.move(stamped, output)
    return output


def nftf_map(data: dict[str, Any]) -> dict[str, Any]:
    name = data.get("client_name", "")
    return {
        "Name": name,
        "Name_2": name,
        "NRIC  Passport Number": data.get("nric", ""),
        "NRIC  Passport Number_2": data.get("nric", ""),
        "Plan Name": data.get("plan_name", ""),
        "I confirm and declare that the Representative": data.get("adviser_name", ""),
        "Date1": today_human(),
        "Date3": today_human(),
    }
