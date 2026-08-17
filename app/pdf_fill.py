from __future__ import annotations

import io
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import fitz
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject, TextStringObject
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from .settings import TEMPLATE_DIR
from .extractor import money_number, fmt_money, norm_money


def today_ddmmyyyy() -> str:
    return date.today().strftime("%d/%m/%Y")


def today_human() -> str:
    return date.today().strftime("%-d %B %Y") if hasattr(date.today(), 'strftime') else date.today().strftime("%d %B %Y")


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


def _widget_checkbox_on_state(widget) -> str:
    try:
        states = widget.button_states() or {}
        normal = states.get("normal") or []
        for state in normal:
            if str(state).lstrip("/").lower() != "off":
                return str(state).lstrip("/")
    except Exception:
        pass
    return "On"


def _fit_widget_font_size(widget, value: str) -> float | None:
    """Choose a conservative font size while keeping the field itself editable."""
    try:
        rect = widget.rect
        width = max(rect.width, 1.0)
        height = max(rect.height, 1.0)
        value = str(value or "")
        if not value:
            return None
        multiline = bool(widget.field_flags & 4096)
        current = float(widget.text_fontsize or 0)
        if multiline:
            # Approximate characters that fit at a given size; preserve line breaks.
            fs = current if current > 0 else 8.0
            fs = min(fs, 8.0)
            while fs > 5.2:
                chars_per_line = max(int(width / (fs * 0.52)), 10)
                lines_available = max(int(height / (fs * 1.25)), 1)
                explicit_lines = sum(max(1, (len(line) + chars_per_line - 1) // chars_per_line) for line in value.splitlines() or [value])
                if explicit_lines <= lines_available:
                    break
                fs -= 0.3
            return max(fs, 5.2)
        fs = current if current > 0 else min(10.0, height * 0.62)
        if len(value) > 1:
            fs = min(fs, max(5.5, width / (len(value) * 0.55)))
        return max(5.5, min(fs, 10.0))
    except Exception:
        return None


def fill_pdf(template: Path, output: Path, field_values: dict[str, Any], checkbox_values: dict[str, str] | None = None) -> Path:
    """Fill AcroForm widgets with regenerated appearance streams while preserving editability."""
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, output)
    checkbox_values = checkbox_values or {}
    text_values = {k: str(v) for k, v in field_values.items() if v not in (None, "")}
    checkbox_names = {k for k, v in checkbox_values.items() if v not in (None, "", "Off", "/Off")}

    doc = fitz.open(str(output))
    try:
        for page in doc:
            widget = page.first_widget
            while widget:
                name = widget.field_name or ""
                try:
                    if name in checkbox_names and widget.field_type in (2, 5):
                        widget.field_value = _widget_checkbox_on_state(widget)
                        widget.update()
                    elif name in text_values and widget.field_type not in (2, 5, 6):
                        value = text_values[name]
                        widget.field_value = value
                        fs = _fit_widget_font_size(widget, value)
                        if fs:
                            widget.text_fontsize = fs
                        widget.update()
                except Exception:
                    pass
                widget = widget.next
        doc.saveIncr()
    finally:
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
    if not values:
        return
    try:
        doc = fitz.open(str(pdf_path))
        for name, page_index, height, rect, ft in _field_widgets(template) or []:
            if name not in values:
                continue
            value = str(values.get(name, "") or "")
            if not value or value in ("Off", "/Off"):
                continue
            if page_index >= len(doc):
                continue
            page = doc[page_index]
            x0, y0, x1, y1 = rect
            fitz_rect = fitz.Rect(x0, height - y1, x1, height - y0)
            if ft == "/Btn":
                # Simple X mark. Do not rely on PDF checkbox appearance dictionaries.
                page.insert_text((fitz_rect.x0 + 1.2, fitz_rect.y0 + 7.4), "X", fontsize=7.5, fontname="helv", overlay=True)
            else:
                # Most text fields render correctly from their form value. Overlay only repeated/parent fields
                # whose appearances commonly fail in browser/PDF renderers.
                TEXT_OVERLAY = {
                    "Clientname", "FAname", "NRIC",
                    "Name of Products", "Company1", "fill_22_2", "fill_23",
                    "Name of Fund Manager  Investment Product1", "Asset Class", "5 Clients Risk Profile",
                    "Business Trail and why was the products andor funds selected Cont If the client has any deviation from your recommendations please also note down the reason here Please include any factors which may significantly increase or decrease the clients income and expense  assets and liabilities in the next 12 months that may impact the clients affordability eg inheritance proceeds from the sale of a property or planning to purchase of a property",
                }
                if name not in TEXT_OVERLAY:
                    continue
                text = value
                fs = _text_font_size(text, rect)
                if (fitz_rect.y1 - fitz_rect.y0) <= 18:
                    page.insert_text((fitz_rect.x0 + 2.0, fitz_rect.y0 + min(10.0, (fitz_rect.y1 - fitz_rect.y0) - 2)), text, fontsize=fs, fontname="helv", overlay=True)
                else:
                    box = fitz.Rect(fitz_rect.x0 + 1.5, fitz_rect.y0 + 1.0, fitz_rect.x1 - 1.5, fitz_rect.y1 - 1.0)
                    page.insert_textbox(box, text, fontsize=fs, fontname="helv", align=0, overlay=True)
        tmp = pdf_path.with_suffix(".overlay.pdf")
        doc.save(str(tmp), garbage=4, deflate=True)
        doc.close()
        shutil.move(str(tmp), str(pdf_path))
    except Exception:
        try:
            doc.close()
        except Exception:
            pass


def _clean_image(path: Path) -> Path:
    # Make transparent/white background signatures easier to stamp.
    if not path or not path.exists():
        return path
    try:
        im = Image.open(path).convert("RGBA")
        datas = im.getdata()
        new = []
        for r, g, b, a in datas:
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


def stamp_signatures(pdf_path: Path, output: Path, client_sig: Path | None = None, fa_sig: Path | None = None, kind: str = "tfp") -> Path:
    shutil.copyfile(pdf_path, output)
    doc = fitz.open(str(output))
    c_sig = _clean_image(client_sig) if client_sig else None
    f_sig = _clean_image(fa_sig) if fa_sig else None
    def put(page_idx: int, img: Path | None, rect):
        if img and img.exists() and page_idx < len(doc):
            doc[page_idx].insert_image(fitz.Rect(*rect), filename=str(img), keep_proportion=True, overlay=True)
    if kind == "tfp":
        # Page 8, 12, 15 client acknowledgement/signature areas.
        put(7, c_sig, (70, 720, 180, 770))
        put(11, c_sig, (70, 700, 180, 750))
        put(14, c_sig, (70, 700, 180, 750))
    elif kind == "checklist":
        put(0, f_sig, (260, 650, 340, 710))
    elif kind == "special":
        put(1, f_sig, (170, 700, 250, 755))
        put(1, c_sig, (310, 700, 410, 755))
    elif kind == "nftf":
        put(0, c_sig, (70, 675, 170, 745))
        put(0, f_sig, (435, 675, 535, 745))
    doc.saveIncr()
    doc.close()
    return output


def check(cb: str) -> str:
    return cb


def tfp_field_map(data: dict[str, Any], product_type: str) -> tuple[dict[str, Any], dict[str, str]]:
    name = data.get("client_name", "")
    nric = data.get("nric", "")
    fa = data.get("adviser_name", "")
    premium = norm_money(data.get("premium", ""))
    if not premium and data.get("expected_retirement_income"):
        premium = ""
    annual_income = norm_money(data.get("annual_income", ""))
    income_n = money_number(annual_income)
    expenses_n = 50000 if income_n else 0
    surplus_n = max(income_n - expenses_n, 0)
    cpf_total = money_number(data.get("cpf_total", ""))
    total_assets = cpf_total + money_number(data.get("other_assets", ""))
    retirement = data.get("expected_retirement_income", "")
    plan = data.get("plan_name") or ({
        "Manulife": "Manulife InvestReady (III)",
        "FWD": "FWD Invest Flexi Elite",
        "Tokio Marine": "Tokio Marine investment-linked plan",
    }.get(product_type, product_type))
    insurer = {"Manulife": "Manulife", "FWD": "FWD", "Tokio Marine": "Tokio Marine"}.get(product_type, product_type)
    fund_name = data.get("fund_name", "")
    fund_code = data.get("fund_code", "")
    today = today_ddmmyyyy()
    fields = {
        # cover page / rep declaration
        "Clientname": name,
        "FAname": fa,
        "Client 2": "",
        "FA 2": "",
        "NRIC": nric,
        "NRICS": "",
        # personal particulars
        "undefined_2": data.get("nationality", "SINGAPORE CITIZEN"),
        "Date of Birth  GG PPP": data.get("dob", ""),
        "undefined_4": data.get("birthplace", "SINGAPORE"),
        "Age Next Birthday ANB": data.get("age_next", ""),
        "Residential Address": data.get("residential_address", ""),
        "Postal Code": data.get("postal", ""),
        "undefined_7": data.get("mobile", ""),
        "undefined_8": data.get("client_email", ""),
        "undefined_9": data.get("occupation", ""),
        "undefined_10": data.get("employer", ""),
        "if retired  unemployed": data.get("source_of_income", "SAVINGS"),
        "Highest Education Level": data.get("education", ""),
        # cashflow/assets/budget
        "Text119": fmt_money(income_n) if income_n else "",
        "Text25": fmt_money(expenses_n) if expenses_n else "",
        "Text27": fmt_money(surplus_n) if income_n else "",
        "Text118": "CLIENT WISH TO DISCLOSE ONLY PARTIAL OF ASSETS AND LIABILITIES, AND HE IS AWARE THIS MAY AFFECT THE RECOMMENDATION.",
        "Text125": fmt_money(cpf_total, compact=True) if cpf_total else "",
        "Text129": fmt_money(max(total_assets, cpf_total), compact=True) if (total_assets or cpf_total) else "",
        "Text137": fmt_money(max(total_assets, cpf_total), compact=True) if (total_assets or cpf_total) else "",
        "Text131": "0",
        "Text133": "0",
        "Text135": "0",
        "Text150": fmt_money(money_number(premium), compact=True) if premium else "",
        "Text152": data.get("source_of_income", "SAVINGS") or "SAVINGS",
        # financial assumptions / retirement page
        "Text3000": "3",
        "Text3111": "3",
        "Text3222": "NA",
        "Text322": "0",
        "fill_27": data.get("retirement_amt", ""),
        "fill_29": data.get("retirement_income", ""),
        "fill_311": data.get("retirement_shortfall", ""),
        "Text306": data.get("retirement_years", ""),
        "fill_33": data.get("retirement_total_amt", ""),
        "fill_37": data.get("retirement_amt_plan", ""),
        # product/recommendation page
        "Name of Products": plan,
        "Company1": insurer,
        "fill_23": fmt_money(money_number(premium), compact=True) + ("/YEAR" if premium else ""),
        "UT 1": "ILP",
        "RSP 1": "100%" if fund_name else "",
        "Name of Fund Manager  Investment Product1": fund_name or ("Selected ILP fund(s)" if product_type == "FWD" else ""),
        "Asset Class": "B" if product_type == "Manulife" else "MIXED",
        "Text37": "Saving and investing to achieve capital gains and potentially higher returns.",
        "Text38": "Up to 99 years" if product_type == "Manulife" else "Till Age 100",
        "Text39": f"{plan} is an investment-linked plan designed to provide investment opportunities with insurance coverage and flexibility to meet changing financial needs.",
        "Text40": "Insurance cover is 101% of total premiums paid or account value, whichever is higher. All investments carry risk and returns are not guaranteed.",
        "5 Clients Risk Profile": "B",
        "Business Trail and why was the products andor funds selected Cont If the client has any deviation from your recommendations please also note down the reason here Please include any factors w": data.get("recommendation_text", ""),
        "Business Trail and why was the products andor funds selected Cont If the client has any deviation from your recommendations please also note down the reason here Please include any factors which may significantly increase or decrease the clients income and expense  assets and liabilities in the next 12 months that may impact the clients affordability eg inheritance proceeds from the sale of a property or planning to purchase of a property": data.get("recommendation_text", ""),
        "date": today.replace("/", "/"),
    }
    cb = {
        # FA representative declaration categories
        "Health Insurance": "Health Insurance",
        "Life Insurance  InvestmentLinked ILP": "Life Insurance  InvestmentLinked ILP",
        "Collective Investment": "Collective Investment",
        "Group Insurance": "Group Insurance",
        "General Insurance": "General Insurance",
        # personal particulars
        "Male": "Male" if data.get("gender", "").lower().startswith("m") else "Off",
        "Female": "Female" if data.get("gender", "").lower().startswith("f") else "Off",
        "No": "No",  # smoker no
        "Not Applicable": "Not Applicable",
        "Single": "Single" if data.get("marital_status", "").lower() == "single" else "Off",
        "Married": "Married" if data.get("marital_status", "").lower() == "married" else "Off",
        "Widowed": "Widowed" if data.get("marital_status", "").lower() == "widowed" else "Off",
        "FullTime": "FullTime" if data.get("employment_status", "").lower().startswith("full") else "Off",
        "Retired": "Retired" if data.get("employment_status", "").lower().startswith("retired") else "Off",
        "yes1": "yes1", # English proficiency yes
        "no3": "no3", # trusted individual no
        # priorities: match common examples
        "Check Box1003": "Check Box1003",  # death low
        "Check Box1012": "Check Box1012",  # TPD low
        "Check Box1020": "Check Box1020",  # CI low
        "Check Box1025": "Check Box1025",  # retirement high
        "Check Box1034": "Check Box1034",  # investment low
        "Check Box1045": "Check Box1045",  # children low
        "Check Box1077": "Check Box1077",  # medical low
        "Check Box1085": "Check Box1085",  # monthly income low
        "Check Box33": "Check Box33", # no dependants
        "No Existing Insurance Policy with": "No Existing Insurance Policy with",
        "No Existing ILPCIS PolicyPortfolio1": "No Existing ILPCIS PolicyPortfolio1",
        "n4": "n4", # health no
        "HV": "HV", # cashflow yes
        "1R_4": "1R_4", # assets yes
        "N11": "N11", # substantial no
        "1R_2": "1R_2", # no future changes
        # CKA / risk profile / business trail defaults
        "Check Box37": "Check Box37",
        "Check Box433": "Check Box433",
        "No3": "No3",
        "No4": "No4",
        "No5": "No5",
        "No6": "No6",
        "No7": "No7",
        "Check Box5": "Check Box5",
        "Yes10": "Yes10",
        "Existing Client": "Existing Client",
        "Video conferencing": "Video conferencing",
        "Video conferencing_2": "Video conferencing_2",
        "Non Face to Face": "Non Face to Face",
        "Check Box42": "Check Box42",
        "Check Box43": "Check Box43",
        "Check Box48": "Check Box48",
        "Check Box63": "Check Box63",
        "Savings": "Savings",
        "Check Box67": "Check Box67",
        "Check Box72": "Check Box72",
        "Check Box76": "Check Box76",
        "Check Box80": "Check Box80",
        "Text messagesSMS": "Text messagesSMS",
        "Check Box7_1": "Check Box7_1",
        "Check Box99": "Check Box99",
        "Check Box94": "Check Box94",
        "Check Box95": "Check Box95",
        "Check Box101": "Check Box101",
        "Check Box103": "Check Box103",
        "Check Box96": "Check Box96",
        "Check Box97": "Check Box97",
        "Check Box105": "Check Box105",
        "Check Box98": "Check Box98",
        "Check Box107": "Check Box107",
        "Check Box110": "Check Box110",
        "Check Box111": "Check Box111",
        "Check Box113": "Check Box113",
        "Check Box114": "Check Box114",
        "Check Box116": "Check Box116",
        "Check Box118": "Check Box118",
        "Check Box117": "Check Box117",
        "Check Box119": "Check Box119",
        "Check Box122": "Check Box122",
        "Check Box123": "Check Box123",
        "Check Box126": "Check Box126",
        "Check Box127": "Check Box127",
        "Check Box130": "Check Box130",
        "Check Box131": "Check Box131",
        "Check Box133": "Check Box133",
        "Check Box136": "Check Box136",
        "Check Box134": "Check Box134",
        "Check Box137": "Check Box137",
        "Check Box135": "Check Box135",
        "Check Box138": "Check Box138",
        "Check Box146": "Check Box146",
        "Check Box145": "Check Box145",
        "Check Box84": "Check Box84",
        "Check Box85": "Check Box85",
        "Check Box148": "Check Box148",
        "Check Box149": "Check Box149",
    }
    if product_type == "Tokio Marine":
        case_date = data.get("case_date", "") or today
        try:
            d, m, y = case_date.split("/")
            case_date_us = f"{int(m):02d}/{int(d):02d}/{y}"
        except Exception:
            case_date_us = case_date

        # Replace generic / inferred values with Tokio source-derived values only.
        expenses = money_number(data.get("cashflow_expenses", ""))
        total_assets_tm = money_number(data.get("total_assets", ""))
        net_assets_tm = money_number(data.get("net_assets", ""))
        if not net_assets_tm and total_assets_tm:
            net_assets_tm = total_assets_tm - money_number(data.get("total_liabilities", ""))

        fields.update({
            "if retired  unemployed": "",
            # The blank TFP already prints the standard suggested assumptions.
            # Leave the client-preferred assumption fields blank unless a source
            # document explicitly supplies them.
            "Text3000": "",
            "Text3111": "",
            "Text3222": "",
            "Text322": "",
            "Text119": fmt_money(income_n) if income_n else "",
            "Text25": fmt_money(expenses) if expenses else "",
            "Text27": fmt_money(max(income_n - expenses, 0)) if (income_n and expenses) else "",
            "Text118": data.get("assets_reason", ""),
            "Text121": "",
            "Text123": norm_money(data.get("investment_assets", "")),
            "Text125": norm_money(data.get("cpf_total", "")),
            "Text127": norm_money(data.get("cash_assets", "")),
            "Text129": norm_money(data.get("total_assets", "")),
            "Text131": "",
            "Text133": "",
            "Text135": norm_money(data.get("total_liabilities", "")),
            "Text137": norm_money(data.get("net_assets", "")),
            "Text150": (fmt_money(money_number(premium)) + "/year") if premium else "",
            "Text152": data.get("source_of_funds", ""),
            "fill_27": fmt_money(money_number(data.get("retirement_amt", ""))) if data.get("retirement_amt") else "",
            "fill_29": fmt_money(money_number(data.get("retirement_income", ""))) if data.get("retirement_income") else "",
            "fill_311": fmt_money(money_number(data.get("retirement_shortfall", ""))) if data.get("retirement_shortfall") else "",
            "fill_33": fmt_money(money_number(data.get("retirement_total_amt", ""))) if data.get("retirement_total_amt") else "",
            "fill_37": fmt_money(money_number(data.get("retirement_amt_plan", ""))) if data.get("retirement_amt_plan") else "",
            "S  L  JO": data.get("risk_profile", ""),
            "Name of Products": plan,
            "Company1": "Tokio Marine",
            "fill_23": (fmt_money(money_number(premium)) + "/year") if premium else "",
            "Text37": "A long-term investment-linked plan for wealth accumulation with insurance protection.",
            "Text38": data.get("policy_term", "") or "Life",
            "Text39": f"A regular premium investment-linked plan with {data.get('benefit_type', 'the selected')} death benefit option and a {data.get('mip', '')} minimum investment period.".replace("  ", " ").strip(),
            "Text40": "For the Enhanced Death Benefit option, during the minimum investment period the death benefit is the higher of 101% of non-guaranteed policy value or the guaranteed death benefit based on regular premiums paid; thereafter it is 101% of non-guaranteed policy value." if str(data.get("benefit_type", "")).lower() == "enhanced" else "Investment-linked benefits and account values are subject to the policy terms and are not guaranteed.",
            "5 Clients Risk Profile": data.get("risk_profile", ""),
            "6 Clients Expected Rate of Return": data.get("expected_return", ""),
            "7 Sales Charges  WRAP  Platform Fee": data.get("sales_charges", ""),
            "8 The Nature of Product  Investment Risk": data.get("investment_risk", "") or data.get("risk_profile", ""),
            "Text41": "Capital and investment returns are not guaranteed. Actual benefits depend on fund performance, fees and charges, withdrawals and policy alterations; past performance is not indicative of future performance.",
            "Date21_af_client_2": case_date_us,
            "Date166_af_date": case_date_us,
            "Date167_af_date": case_date_us,
        })

        # Clear generic single-fund row, then fill all Tokio funds from the application / BI.
        for i in range(1, 8):
            fields[f"UT {i}"] = ""
            fields[f"RSP {i}"] = ""
            fields[f"Name of Fund Manager  Investment Product{i}"] = ""
            fields["Asset Class" if i == 1 else f"Asset Class_{i}"] = ""
            fname = data.get(f"fund_{i}_name", "")
            if fname:
                fields[f"UT {i}"] = "ILP"
                fields[f"Name of Fund Manager  Investment Product{i}"] = fname
                amount = data.get(f"fund_{i}_amount", "")
                fields[f"RSP {i}"] = (norm_money(amount) + "/year") if amount else ""
                fields["Asset Class" if i == 1 else f"Asset Class_{i}"] = data.get(f"fund_{i}_asset_class", "")

        # Match the approved Tokio Marine FA declaration categories supplied as the reference.
        cb.pop("Group Insurance", None)
        cb.pop("General Insurance", None)

        # Client-specific answers must not be invented from the insurer alone.
        for unknown_cb in [
            "no3", "yes1",
            "Check Box1003", "Check Box1012", "Check Box1020", "Check Box1025", "Check Box1034", "Check Box1045", "Check Box1077", "Check Box1085",
            "Check Box33", "No Existing ILPCIS PolicyPortfolio1", "n4", "1R_4", "N11", "1R_2",
            "Check Box37", "Check Box433", "No3", "No4", "No5", "No6", "No7", "Check Box5", "Yes10",
            "Existing Client", "Video conferencing", "Video conferencing_2", "Non Face to Face",
            "Check Box42", "Check Box43", "Check Box48", "Check Box63", "Savings", "Check Box67", "Check Box72", "Check Box76", "Check Box80",
            "Text messagesSMS", "Check Box7_1", "Check Box99", "Check Box94", "Check Box95", "Check Box101", "Check Box103", "Check Box96", "Check Box97", "Check Box105", "Check Box98", "Check Box107", "Check Box110", "Check Box111", "Check Box113", "Check Box114", "Check Box116", "Check Box118", "Check Box117", "Check Box119", "Check Box122", "Check Box123", "Check Box126", "Check Box127", "Check Box130", "Check Box131", "Check Box133", "Check Box136", "Check Box134", "Check Box137", "Check Box135", "Check Box138", "Check Box146", "Check Box145", "Check Box84", "Check Box85", "Check Box148", "Check Box149",
        ]:
            cb.pop(unknown_cb, None)

        # Smoker status is explicit in the Tokio BI.
        cb.pop("No", None)
        if str(data.get("smoker", "")).lower() == "no":
            cb["No"] = "On"
        elif str(data.get("smoker", "")).lower() == "yes":
            cb["Yes"] = "On"

        # Income bracket can be determined directly from the application income.
        for income_cb in ("Check Box1", "Check Box2", "Check Box3", "Check Box4", "Check Box6", "Check Box12"):
            cb.pop(income_cb, None)
        if income_n:
            if income_n < 30000: cb["Check Box1"] = "On"
            elif income_n <= 50000: cb["Check Box3"] = "On"
            elif income_n <= 100000: cb["Check Box6"] = "On"
            elif income_n <= 150000: cb["Check Box2"] = "On"
            elif income_n <= 250000: cb["Check Box4"] = "On"
            else: cb["Check Box12"] = "On"

        # Cash flow is included when an annual income was actually extracted.
        if income_n:
            cb["HV"] = "On"
        else:
            cb.pop("HV", None)

        # If a supporting TFP explicitly supplies risk profile, reproduce the corresponding risk preference.
        risk = str(data.get("risk_profile", "")).strip().lower()
        if risk == "aggressive":
            cb["Check Box37"] = "Yes"   # high risk-return preference
            cb["Check Box433"] = "Yes"  # high risk-taking preference

        # Do not claim existing insurance status unless explicitly present in the Tokio application text / supporting document.
        if str(data.get("existing_policy_status", "")).lower() == "no":
            cb["No Existing Insurance Policy with"] = "On"
        else:
            cb.pop("No Existing Insurance Policy with", None)

        # If disclosed assets are available, determine whether the annual budget exceeds 50% of assets.
        if total_assets_tm:
            cb["1R_4"] = "On"
            if premium and money_number(premium) <= total_assets_tm * 0.5:
                cb["N11"] = "On"

    # Remove Off values so existing blank doesn't get set weirdly.
    cb = {k: v for k, v in cb.items() if v != "Off"}
    return fields, cb


def checklist_map(data: dict[str, Any], product_type: str) -> tuple[dict[str, Any], dict[str, str]]:
    name = data.get("client_name", "")
    nric = data.get("nric", "")
    plan = data.get("plan_name") or ("MANULIFE INVESTREADY (III) 10 YEARS FLEXI 3" if product_type == "Manulife" else "FWD INVEST FLEXI ELITE")
    fields = {
        "1": plan.upper(),
        "Name of Proposer": name,
        "NRIC No": nric,
        "Name of Life Assured": name,
        "NRIC No_2": nric,
        "Quantity SubmittedApplication for Life Insurance Proposal Forms": "1",
        "Quantity SubmittedBenefit Illustration and Product Summary": "1",
        "Quantity SubmittedIdentity Card  Driving License  Passport": "1",
        "Quantity SubmittedThe Financial Planner Form for PLD use only": "1",
        "Quantity SubmittedClient Knowledge Assessment Form ILP cases": "1" if product_type == "FWD" else "",
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
        "Insurer Platform": "Insurer Platform" if product_type == "FWD" else "Off",
        "Manulife": "On" if product_type == "Manulife" else "Off",
        "FWD": "FWD" if product_type == "FWD" else "Off",
        "AXA": "AXA" if product_type == "FWD" else "Off",
        "c1": "On" if product_type == "Manulife" else "c1",
        "c2": "On" if product_type == "Manulife" else "c2",
        "c4": "On" if product_type == "Manulife" else "c4",
        "c6": "On" if product_type == "Manulife" else "c6",
        "c7": "c7" if product_type == "FWD" else "Off",
        "c9": "On" if product_type == "Manulife" else "Off",
        "c11": "On" if product_type == "Manulife" else "c11",
        "c12": "On" if product_type == "Manulife" else "Off",
        "c13": "On" if product_type == "Manulife" else "Off",
    }
    return fields, {k: v for k, v in cb.items() if v != "Off"}


def special_disclosure_manulife(data: dict[str, Any], output: Path, client_sig: Path | None, fa_sig: Path | None) -> Path:
    fields = {
        "fa_name": data.get("adviser_name", ""),
        "client_name": data.get("client_name", ""),
        "date_today_1": today_ddmmyyyy(),
        "date_today_2": today_ddmmyyyy(),
    }
    tmp = output.with_suffix(".fields.pdf")
    fill_pdf(TEMPLATE_DIR / "special_disclosure_manulife.pdf", tmp, fields, {})
    stamp_signatures(tmp, output, client_sig, fa_sig, kind="special")
    try: tmp.unlink()
    except: pass
    return output


def build_special_disclosure_simple(data: dict[str, Any], output: Path, product_type: str, client_sig: Path | None, fa_sig: Path | None) -> Path:
    # Used for FWD where no clean fillable blank was supplied. It is editable where key fields are concerned.
    c = canvas.Canvas(str(output), pagesize=A4)
    w, h = A4
    text = c.beginText(25*mm, h-25*mm)
    text.setFont("Helvetica-Bold", 14)
    text.textLine("SPECIAL DISCLOSURE")
    text.setFont("Helvetica", 10)
    body = [
        "(Investment-Linked Plan)", "", "About ILPs", "An ILP is a life insurance policy that provides a combination of protection and investment.", "",
        "Returns", "Fund prices may go down and up depending upon investment performance. Past performance is not an indication of future performance.",
        "You may get back less than you have paid in.", "", "Fees and Charges",
        "Several fees and charges may apply, including policy administration charge, fund management charge, surrender charge, switching fee, mortality and other risk charges.",
        "Please refer to the Policy Illustration and Product Summary for the full details.", "", "Premium Payment",
        "This policy requires premiums to be paid for the applicable premium payment term. Please speak to your Financial Adviser Representative before deciding on premium holiday or surrender.", "",
        "Minimum Investment Period (MIP)", "Withdrawals or surrender during the MIP may reduce policy value and may affect your ability to reach your financial goals.", "",
        "Free-look Period", "You have 14 days to review the policy. If you cancel within the free-look period, the insurer will refund premiums after applicable adjustments.",
    ]
    for line in body:
        for sub in re.findall(r'.{1,96}(?:\s+|$)', line) or [""]:
            text.textLine(sub.strip())
    c.drawText(text)
    c.showPage()
    c.setFont("Helvetica-Bold", 12)
    c.drawString(25*mm, h-25*mm, "CLIENT ACKNOWLEDGEMENT")
    c.setFont("Helvetica", 10)
    ack = "I/we confirm that I/we have read the relevant marketing materials about the product structure, benefits, premiums, premium term, policy term, minimum investment period, flexibility, fees and charges, policy issuance and investment funds."
    y = h-40*mm
    for sub in re.findall(r'.{1,100}(?:\s+|$)', ack):
        c.drawString(25*mm, y, sub.strip()); y -= 6*mm
    # table
    y -= 10*mm
    c.rect(25*mm, y-38*mm, 160*mm, 38*mm)
    for x in [65*mm, 105*mm, 145*mm]:
        c.line(x, y, x, y-38*mm)
    for yy in [y-10*mm, y-24*mm]:
        c.line(25*mm, yy, 185*mm, yy)
    c.drawString(30*mm, y-7*mm, "Signature:")
    c.drawString(30*mm, y-20*mm, "Name:")
    c.drawString(30*mm, y-33*mm, "Date:")
    c.drawString(76*mm, y-7*mm, "Advisor")
    c.drawString(114*mm, y-7*mm, "PolicyHolder 1")
    c.drawString(152*mm, y-7*mm, "PolicyHolder 2")
    c.acroform.textfield(name="fa_name", x=66*mm, y=y-23*mm, width=38*mm, height=8*mm, value=data.get("adviser_name", ""), borderWidth=0, fontSize=8)
    c.acroform.textfield(name="client_name", x=106*mm, y=y-23*mm, width=38*mm, height=8*mm, value=data.get("client_name", ""), borderWidth=0, fontSize=8)
    c.acroform.textfield(name="date_today_1", x=66*mm, y=y-36*mm, width=38*mm, height=8*mm, value=today_ddmmyyyy(), borderWidth=0, fontSize=8)
    c.acroform.textfield(name="date_today_2", x=106*mm, y=y-36*mm, width=38*mm, height=8*mm, value=today_ddmmyyyy(), borderWidth=0, fontSize=8)
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
        "Plan Name": data.get("plan_name", "MANULIFE INVESTREADY (III) 10 YEARS FLEXI 3"),
        "I confirm and declare that the Representative": data.get("adviser_name", ""),
        "Date1": today_human(),
        "Date3": today_human(),
    }
