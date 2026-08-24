from __future__ import annotations

"""Deterministic compliance helpers for the Ai TFP Form Filler.

This module intentionally contains no OpenAI calls.  Compliance calculations, CKA
outcome, risk-profile mapping, budget/concentration checks and product-specific BOR
clauses are rule driven so that narrative generation cannot silently invent facts.

The rules here are based on the Nov-2025 PromiseLand TFP structure and the internal
Simple Guide / completed TFP examples supplied by Compliance.  Product-specific
terms are only used for the named reference products below.  Unknown products fall
back to source-document wording instead of guessed terms.
"""

import re
from dataclasses import dataclass
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def money_number(value: Any) -> float:
    """Parse common TFP money formats, including values such as '100k SP'."""
    text = clean(value).lower().replace("s$", "").replace("$", "").replace(",", "").strip()
    if not text or text in {"na", "n/a", "nil", "none", "not disclosed", "not disclose"}:
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


def fmt_money(value: Any, compact: bool = False) -> str:
    n = money_number(value) if not isinstance(value, (int, float)) else float(value)
    if not n:
        return ""
    if compact:
        if n >= 1_000_000 and n % 1_000_000 == 0:
            return f"{int(n / 1_000_000)}MIL"
        if n >= 1_000 and n % 1_000 == 0:
            return f"{int(n / 1_000)}K"
    return f"{n:,.0f}"


def _field(fields: dict[str, Any], *names: str) -> str:
    for name in names:
        value = clean(fields.get(name))
        if value and value.lower() not in {"off", "/off"}:
            return value.lstrip("/")
    return ""


def _checked(fields: dict[str, Any], *names: str) -> bool:
    for name in names:
        value = clean(fields.get(name)).lower().lstrip("/")
        if value and value not in {"off", "false", "0", "no"}:
            return True
    return False


def _explicit_yes_no(fields: dict[str, Any], yes_name: str, no_name: str) -> bool | None:
    yes = _checked(fields, yes_name)
    no = _checked(fields, no_name)
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None


def _money_or_blank(value: Any) -> str:
    text = clean(value)
    if not text or text.lower() in {"na", "n/a", "not disclose", "not disclosed"}:
        return ""
    return text


def _ratio(numerator: float, denominator: float) -> float | None:
    if numerator <= 0 or denominator <= 0:
        return None
    return numerator / denominator


def _percent(value: float | None) -> str:
    return "" if value is None else f"{value * 100:.1f}%"


# ---------------------------------------------------------------------------
# Product rule library
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductProfile:
    key: str
    label: str
    company: str
    category: str  # ilp | unit_trust | participating_life | life | unknown
    premium_mode: str  # annual | single | unknown
    requires_cka: bool
    disclosure_checklist: str  # life | unit_trust | none
    fna_investment_years: int | None = None
    death_benefit_text: str = ""
    product_feature_text: str = ""
    limitation_text: str = ""
    charges_text: str = ""


PRODUCT_PROFILES: dict[str, ProductProfile] = {
    "ifast_unit_trust": ProductProfile(
        key="ifast_unit_trust",
        label="IFAST Unit Trust",
        company="IFAST",
        category="unit_trust",
        premium_mode="single",
        requires_cka=True,
        disclosure_checklist="unit_trust",
        product_feature_text=(
            "IFAST provides access to investment products such as unit trusts. "
            "The selected fund(s), allocation and asset class should follow the applicable fund factsheet(s)."
        ),
        limitation_text="Market risk applies. Returns, distributions and capital are not guaranteed.",
        charges_text="Net returns are reduced by applicable ongoing fees and charges, including wrap/platform fees where applicable. Refer to the IFAST documents.",
    ),
    "ilp_10_flex_3": ProductProfile(
        key="ilp_10_flex_3",
        label="ILP 10 Flex 3",
        company="Manulife",
        category="ilp",
        premium_mode="annual",
        requires_cka=True,
        disclosure_checklist="life",
        fna_investment_years=10,
        death_benefit_text=(
            "Death benefit: 101% of total basic premiums paid plus any top-up premium less withdrawals, "
            "or account value, less any amount owing to the insurer, subject to the Product Summary."
        ),
        product_feature_text=(
            "A regular-premium investment-linked plan providing investment opportunities together with insurance protection."
        ),
        limitation_text=(
            "Surrender and partial-withdrawal charges may apply during the first 10 policy years. "
            "After the first 3 years a premium holiday may be available without premium shortfall charge, "
            "but ongoing deductions continue and the policy may lapse if account value becomes insufficient."
        ),
        charges_text=(
            "Ongoing charges may include cost of insurance, administrative/policy charges and fund management charges. "
            "Refer to the Product Summary for the exact charge names and rates."
        ),
    ),
    "goelite": ProductProfile(
        key="goelite",
        label="#goElite",
        company="Tokio Marine",
        category="ilp",
        premium_mode="single",
        requires_cka=True,
        disclosure_checklist="life",
        death_benefit_text="Death benefit: 105% of policy value less indebtedness while the policy is in force, subject to the Product Summary.",
        product_feature_text="A whole-life single-premium investment-linked plan offering investment options and insurance protection.",
        limitation_text="A surrender charge applies during the first 5 years; partial-withdrawal charges may also apply.",
        charges_text=(
            "Ongoing charges may include cost of insurance, administrative/policy charges and fund management charges. "
            "Refer to the Product Summary for exact charge names and rates."
        ),
    ),
    "singlife_flexi_income": ProductProfile(
        key="singlife_flexi_income",
        label="Singlife Flexi Income",
        company="Singlife",
        category="participating_life",
        premium_mode="single",
        requires_cka=False,
        disclosure_checklist="life",
        product_feature_text=(
            "A participating whole-life insurance plan intended for wealth accumulation and income, with death/terminal-illness coverage. "
            "Guaranteed and non-guaranteed benefits must follow the Policy Illustration and Product Summary."
        ),
        limitation_text="Participating-fund risk, non-guaranteed benefit risk and early-surrender/liquidity risk apply.",
        charges_text="Refer to the Product Summary and Policy Illustration for charges, surrender terms and benefit details.",
    ),
    "fwd_invest_flexi_elite": ProductProfile(
        key="fwd_invest_flexi_elite",
        label="FWD Invest Flexi Elite",
        company="FWD",
        category="ilp",
        premium_mode="annual",
        requires_cka=True,
        disclosure_checklist="life",
        product_feature_text="An investment-linked life plan. Product features and insurance benefits must follow the FWD Product Summary.",
        limitation_text="Investment values fluctuate and returns are not guaranteed. Refer to the Product Summary for surrender, withdrawal and premium-flexibility terms.",
        charges_text="Use the exact FWD charge names and rates stated in the Product Summary; do not substitute generic insurer terms.",
    ),
    "hsbc_life": ProductProfile(
        key="hsbc_life",
        label="HSBC Life plan",
        company="HSBC Life",
        category="life",
        premium_mode="unknown",
        requires_cka=False,
        disclosure_checklist="life",
        product_feature_text="Use the HSBC Benefit Illustration / Product Summary for the exact plan structure, benefits and policy term.",
        limitation_text="Use the HSBC Product Summary for surrender terms, non-guaranteed elements and product-specific risks.",
        charges_text="Use the HSBC Product Summary for the exact fees and charges.",
    ),
    "generic_life": ProductProfile(
        key="generic_life",
        label="Life insurance plan",
        company="",
        category="life",
        premium_mode="unknown",
        requires_cka=False,
        disclosure_checklist="life",
        product_feature_text="Product features must be taken from the Benefit Illustration / Product Summary.",
        limitation_text="Product limitations and risks must be taken from the Product Summary.",
        charges_text="Fees and charges must be taken from the Product Summary.",
    ),
    "unknown": ProductProfile(
        key="unknown",
        label="Recommended product",
        company="",
        category="unknown",
        premium_mode="unknown",
        requires_cka=False,
        disclosure_checklist="none",
    ),
}


def classify_product(data: dict[str, Any], product_type: str = "", source_text: str = "") -> ProductProfile:
    blob = " ".join(
        [
            clean(data.get("plan_name")),
            clean(data.get("mip")),
            clean(data.get("benefit_type")),
            clean(product_type),
            clean(source_text)[:200_000],
        ]
    ).lower()

    if "ifast" in blob:
        return PRODUCT_PROFILES["ifast_unit_trust"]
    if "#goelite" in blob or "goelite" in blob or "go elite" in blob:
        return PRODUCT_PROFILES["goelite"]
    if "singlife flexi" in blob or "flexi life income" in blob:
        return PRODUCT_PROFILES["singlife_flexi_income"]
    if (
        "10 flex 3" in blob
        or "10 flexi 3" in blob
        or "10 years flexi 3" in blob
        or (("investready" in blob or "invest ready" in blob) and ("flexi 3" in blob or "10 year" in blob or "10 flex" in blob))
    ):
        return PRODUCT_PROFILES["ilp_10_flex_3"]
    if "invest flexi elite" in blob or ("fwd" in blob and "investment-linked" in blob):
        return PRODUCT_PROFILES["fwd_invest_flexi_elite"]
    if "hsbc" in blob:
        # Do not automatically call every HSBC life policy an ILP / SIP.
        # CKA applicability must be supported by the actual product documents.
        if "investment-linked" in blob or re.search(r"\bilp\b", blob):
            p = PRODUCT_PROFILES["hsbc_life"]
            return ProductProfile(
                **{**p.__dict__, "category": "ilp", "requires_cka": True, "premium_mode": _premium_mode_from_text(blob)}
            )
        return PRODUCT_PROFILES["hsbc_life"]
    if "investment-linked" in blob or re.search(r"\bilp\b", blob):
        company = clean(data.get("insurer")) or clean(product_type)
        return ProductProfile(
            key="generic_ilp",
            label=clean(data.get("plan_name")) or "Investment-linked plan",
            company=company,
            category="ilp",
            premium_mode=_premium_mode_from_text(blob),
            requires_cka=True,
            disclosure_checklist="life",
            product_feature_text="Investment-linked plan; use the insurer Product Summary for exact benefits and terms.",
            limitation_text="Investment values fluctuate and returns are not guaranteed. Use the Product Summary for surrender and withdrawal terms.",
            charges_text="Use the Product Summary for the exact ongoing fees and charges.",
        )
    if any(k in blob for k in ("whole life", "endowment", "participating", "life insurance")):
        p = PRODUCT_PROFILES["generic_life"]
        return ProductProfile(**{**p.__dict__, "company": clean(product_type), "premium_mode": _premium_mode_from_text(blob)})
    return PRODUCT_PROFILES["unknown"]


def _premium_mode_from_text(blob: str) -> str:
    if any(x in blob for x in ("single premium", "lump sum", "lump-sum", " sp ")):
        return "single"
    if any(x in blob for x in ("annual premium", "regular premium", "annually", "yearly")):
        return "annual"
    return "unknown"


# ---------------------------------------------------------------------------
# TFP field extraction and deterministic calculations
# ---------------------------------------------------------------------------


RISK_ORDER = {
    "conservative": 1,
    "moderately conservative": 2,
    "balanced": 3,
    "moderately aggressive": 4,
    "aggressive": 5,
}


def normalise_risk(value: Any) -> str:
    text = clean(value).lower().replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    aliases = {
        "conservative": "Conservative",
        "moderately conservative": "Moderately Conservative",
        "balanced": "Balanced",
        "moderately aggressive": "Moderately Aggressive",
        "aggressive": "Aggressive",
    }
    return aliases.get(text, "")


def assigned_risk_profile(risk_return: str, risk_taking: str) -> str:
    rr = clean(risk_return).upper()[:1]
    rt = clean(risk_taking).upper()[:1]
    matrix = {
        ("L", "L"): "Conservative",
        ("L", "M"): "Conservative",
        ("L", "H"): "Moderately Conservative",
        ("M", "L"): "Conservative",
        ("M", "M"): "Balanced",
        ("M", "H"): "Moderately Aggressive",
        ("H", "L"): "Moderately Conservative",
        ("H", "M"): "Moderately Aggressive",
        ("H", "H"): "Aggressive",
    }
    return matrix.get((rr, rt), "")


def _preference_from_fields(fields: dict[str, Any], names: dict[str, str]) -> str:
    for code, name in names.items():
        if _checked(fields, name):
            return code
    return ""


def _extract_asset_class_from_text(text: str) -> str:
    # Only accept an explicit asset-class label.  Do not infer from a fund name.
    patterns = [
        r"Asset\s*Class\s*[:\-]\s*([^\n]{2,60})",
        r"Asset\s*class\s*\n\s*([^\n]{2,60})",
    ]
    allowed = (
        "equity",
        "fixed income",
        "bond",
        "multi-asset",
        "multi asset",
        "balanced",
        "money market",
        "cash",
        "alternatives",
        "property",
        "real estate",
    )
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if not m:
            continue
        candidate = clean(m.group(1)).split("|")[0].strip(" .;:")
        low = candidate.lower()
        for token in allowed:
            if token in low:
                if token == "multi asset":
                    return "Multi-Asset"
                if token == "fixed income":
                    return "Fixed Income"
                return token.title()
    return ""


def _extract_fund_risk_from_text(text: str) -> str:
    # "Risk Profile" on a completed TFP normally refers to the CLIENT, not the fund.
    # Accept only labels that are sufficiently fund/factsheet-specific.
    for pattern in (
        r"Fund\s+Risk\s+(?:Rating|Profile|Classification)\s*[:\-]\s*(Conservative|Moderately Conservative|Balanced|Moderately Aggressive|Aggressive)",
        r"Risk\s+(?:Rating|Classification)\s*[:\-]\s*(Conservative|Moderately Conservative|Balanced|Moderately Aggressive|Aggressive)",
    ):
        m = re.search(pattern, text, flags=re.I)
        if m:
            return normalise_risk(m.group(1))
    return ""


def _extract_time_horizon(fields: dict[str, Any], data: dict[str, Any]) -> str:
    value = _field(fields, "Text38") or clean(data.get("investment_time_horizon"))
    if value:
        return value
    term = clean(data.get("policy_term"))
    return term


def _extract_funds(fields: dict[str, Any], data: dict[str, Any], source_text: str) -> list[dict[str, str]]:
    funds: list[dict[str, str]] = []
    for i in range(1, 8):
        name_field = f"Name of Fund Manager  Investment Product{i}"
        asset_field = "Asset Class" if i == 1 else f"Asset Class_{i}"
        name = _field(fields, name_field)
        if not name and i == 1:
            name = clean(data.get("fund_name"))
        asset = _field(fields, asset_field)
        if not asset and i == 1:
            asset = clean(data.get("asset_class")) or _extract_asset_class_from_text(source_text)
        amount = _field(fields, f"RSP {i}")
        if not amount and i == 1:
            amount = clean(data.get("fund_invested_amount"))
        if name:
            funds.append({"name": name, "asset_class": asset, "amount": amount})
    if not funds and clean(data.get("fund_name")):
        funds.append(
            {
                "name": clean(data.get("fund_name")),
                "asset_class": clean(data.get("asset_class")) or _extract_asset_class_from_text(source_text),
                "amount": clean(data.get("fund_invested_amount")),
            }
        )
    return funds


def extract_compliance_facts(
    data: dict[str, Any],
    fields: dict[str, Any] | None = None,
    source_text: str = "",
) -> dict[str, Any]:
    fields = fields or {}
    facts: dict[str, Any] = {}

    # Page 8 - only use actual disclosed values.  Never invent expenses/liabilities.
    facts["annual_income"] = _money_or_blank(_field(fields, "Text119") or data.get("annual_income"))
    facts["annual_expenses"] = _money_or_blank(_field(fields, "Text25") or data.get("annual_expenses"))
    facts["annual_surplus"] = _money_or_blank(_field(fields, "Text27") or data.get("annual_surplus"))
    if not facts["annual_surplus"] and facts["annual_income"] and facts["annual_expenses"]:
        income = money_number(facts["annual_income"])
        expenses = money_number(facts["annual_expenses"])
        facts["annual_surplus"] = fmt_money(max(income - expenses, 0)) if income >= expenses else f"-{fmt_money(expenses - income)}"

    facts["personal_use_assets"] = _money_or_blank(_field(fields, "Text121") or data.get("personal_use_assets"))
    facts["investment_assets"] = _money_or_blank(_field(fields, "Text123") or data.get("investment_assets"))
    facts["cpf_total"] = _money_or_blank(_field(fields, "Text125") or data.get("cpf_total"))
    facts["other_assets"] = _money_or_blank(_field(fields, "Text127") or data.get("other_assets"))
    facts["total_assets"] = _money_or_blank(_field(fields, "Text129") or data.get("total_assets"))
    facts["loans"] = _money_or_blank(_field(fields, "Text131") or data.get("loans"))
    facts["other_liabilities"] = _money_or_blank(_field(fields, "Text133") or data.get("other_liabilities"))
    facts["total_liabilities"] = _money_or_blank(_field(fields, "Text135") or data.get("total_liabilities"))
    facts["net_assets"] = _money_or_blank(_field(fields, "Text137") or data.get("net_assets"))

    if not facts["total_assets"]:
        components = [
            money_number(facts["personal_use_assets"]),
            money_number(facts["investment_assets"]),
            money_number(facts["cpf_total"]),
            money_number(facts["other_assets"]),
        ]
        if any(components):
            facts["total_assets"] = fmt_money(sum(components))
    if not facts["total_liabilities"]:
        liabs = [money_number(facts["loans"]), money_number(facts["other_liabilities"])]
        if any(liabs):
            facts["total_liabilities"] = fmt_money(sum(liabs))
    if not facts["net_assets"] and facts["total_assets"]:
        # Only subtract liabilities if there is an actual disclosed liability figure.
        total = money_number(facts["total_assets"])
        liabilities = money_number(facts["total_liabilities"])
        if facts["total_liabilities"]:
            facts["net_assets"] = fmt_money(max(total - liabilities, 0))

    disclosure_note = _field(fields, "Text118", "Text115") or clean(data.get("financial_disclosure_note"))
    facts["financial_disclosure_note"] = disclosure_note
    low_note = disclosure_note.lower()
    facts["financial_disclosure_partial"] = bool(
        disclosure_note
        and any(x in low_note for x in ("partial", "not disclose", "not disclosed", "do not want to factor", "exclude property", "not factor"))
    )

    # Budget / funding source.  Keep annual and single budget separate.
    facts["annual_budget"] = _money_or_blank(_field(fields, "Text150") or data.get("annual_budget"))
    facts["annual_budget_source"] = _field(fields, "Text152") or clean(data.get("annual_budget_source"))
    facts["single_budget"] = _money_or_blank(_field(fields, "Text154") or data.get("single_budget"))
    facts["single_budget_source"] = _field(fields, "Text156") or clean(data.get("single_budget_source"))
    facts["source_of_funds"] = (
        facts["annual_budget_source"]
        or facts["single_budget_source"]
        or clean(data.get("source_of_funds"))
        or clean(data.get("source_of_income"))
    )

    # Page 9 savings/investment FNA (reference case fields).
    facts["investment_goal"] = _money_or_blank(_field(fields, "fill_39") or data.get("investment_goal"))
    facts["investment_duration_years"] = _field(fields, "Text308") or clean(data.get("investment_duration_years"))
    facts["investment_existing"] = _money_or_blank(_field(fields, "fill_41") or data.get("investment_existing"))
    facts["investment_amount_to_plan"] = _money_or_blank(_field(fields, "fill_43") or data.get("investment_amount_to_plan"))

    # Page 10 risk profiling.
    risk_return = clean(data.get("risk_return_preference")) or _preference_from_fields(
        fields, {"H": "Check Box37", "M": "Check Box38", "L": "Check Box39"}
    )
    risk_taking = clean(data.get("risk_taking_preference")) or _preference_from_fields(
        fields, {"H": "Check Box433", "M": "Check Box455", "L": "Check Box466"}
    )
    assigned = normalise_risk(_field(fields, "S  L  JO", "5 Clients Risk Profile") or data.get("risk_profile"))
    if not assigned and risk_return and risk_taking:
        assigned = assigned_risk_profile(risk_return, risk_taking)
    facts["risk_return_preference"] = risk_return
    facts["risk_taking_preference"] = risk_taking
    facts["risk_profile"] = assigned
    facts["fund_risk_profile"] = normalise_risk(data.get("fund_risk_profile")) or _extract_fund_risk_from_text(source_text)

    # Page 11 CKA - outcome is deterministic if the four question answers are explicit.
    cka_edu = _explicit_yes_no(fields, "Yes3", "No3")
    cka_prof = _explicit_yes_no(fields, "Yes4", "No4")
    cka_txn = _explicit_yes_no(fields, "Yes5", "No5")
    cka_work = _explicit_yes_no(fields, "Yes6", "No6")
    for key, data_key in (
        ("cka_education", "cka_education"),
        ("cka_professional_qualification", "cka_professional_qualification"),
        ("cka_investment_experience", "cka_investment_experience"),
        ("cka_work_experience", "cka_work_experience"),
    ):
        if data_key in data and isinstance(data[data_key], bool):
            locals_map = {
                "cka_education": cka_edu,
                "cka_professional_qualification": cka_prof,
                "cka_investment_experience": cka_txn,
                "cka_work_experience": cka_work,
            }
            locals_map[key] = data[data_key]
            cka_edu = locals_map["cka_education"]
            cka_prof = locals_map["cka_professional_qualification"]
            cka_txn = locals_map["cka_investment_experience"]
            cka_work = locals_map["cka_work_experience"]
    facts["cka_education"] = cka_edu
    facts["cka_professional_qualification"] = cka_prof
    facts["cka_investment_experience"] = cka_txn
    facts["cka_work_experience"] = cka_work
    answers = [cka_edu, cka_prof, cka_txn, cka_work]
    if any(v is True for v in answers):
        facts["cka_met"] = True
    elif all(v is False for v in answers):
        facts["cka_met"] = False
    else:
        # If a completed TFP explicitly records the outcome, use that.
        if _checked(fields, "Yes7"):
            facts["cka_met"] = True
        elif _checked(fields, "No7"):
            facts["cka_met"] = False
        else:
            facts["cka_met"] = None

    # Selected-client indicators.  Unknown values remain unknown; do not assume.
    facts["english_proficient"] = _english_value(data, fields)
    facts["education_level"] = clean(data.get("education")) or _field(fields, "Highest Education Level")
    facts["selected_client"] = selected_client_status(data, facts)

    # Joint case detection uses actual populated fields, not labels in source text.
    joint_values = [
        _field(fields, "Client 2", "NRICS", "Clientnames", "Joint Proposer", "Joint Applicant"),
        clean(data.get("joint_client_name")),
        clean(data.get("joint_nric")),
    ]
    facts["is_joint_case"] = any(v and v.upper() not in {"N/A", "NA", "X"} for v in joint_values)

    facts["future_changes"] = data.get("future_changes") if isinstance(data.get("future_changes"), bool) else None
    if _checked(fields, "HV_2"):
        facts["future_changes"] = True
    elif _checked(fields, "1R_2"):
        facts["future_changes"] = False
    facts["future_changes_reason"] = _field(fields, "Text116") or clean(data.get("future_changes_reason"))

    # Page 13 product/fund facts.
    facts["funds"] = _extract_funds(fields, data, source_text)
    facts["asset_class"] = (
        (facts["funds"][0].get("asset_class") if facts["funds"] else "")
        or clean(data.get("asset_class"))
        or _extract_asset_class_from_text(source_text)
    )
    facts["expected_rate_of_return"] = _field(fields, "6 Clients Expected Rate of Return") or clean(data.get("expected_rate_of_return"))
    facts["sales_charges"] = _field(fields, "7 Sales Charges  WRAP  Platform Fee", "7 Sales Charges WRAP Platform Fee") or clean(data.get("sales_charges"))
    facts["investment_risk_text"] = _field(fields, "8 The Nature of Product  Investment Risk", "8 The Nature of Product Investment Risk") or clean(data.get("investment_risk_text"))
    facts["other_product_limitations"] = _field(fields, "Text41") or clean(data.get("other_product_limitations"))
    facts["investment_objective_text"] = _field(fields, "Text37") or clean(data.get("investment_objective_text"))
    facts["investment_time_horizon"] = _extract_time_horizon(fields, data)

    # Distribution wording must be supported by actual text; do not infer solely from "Income" in a fund name.
    facts["distribution_fund"] = bool(
        re.search(r"\b(distribut(?:e|es|ing|ion)|dividend(?:s)?|monthly distribution|income distribution)\b", source_text, flags=re.I)
        or data.get("distribution_fund") is True
    )

    # Preserve Page-5 choices when this engine is run against a completed TFP/reference case.
    facts["priorities_existing"] = extract_existing_priorities(fields)

    return facts


def _english_value(data: dict[str, Any], fields: dict[str, Any]) -> bool | None:
    raw = clean(data.get("english")).lower()
    if raw in {"yes", "y", "true", "proficient"}:
        return True
    if raw in {"no", "n", "false", "not proficient"}:
        return False
    if _checked(fields, "yes1"):
        return True
    # Some template versions use a dedicated No checkbox; do not guess its name.
    return None


def _education_below_on_level(value: str) -> bool | None:
    low = clean(value).lower()
    if not low:
        return None
    higher = ("degree", "diploma", "university", "polytechnic", "a level", "a-level", "gce a", "masters", "master", "phd", "doctorate")
    if any(x in low for x in higher):
        return False
    below = ("primary", "psle", "no formal", "below n", "below o", "secondary 1", "secondary 2", "secondary 3")
    if any(x in low for x in below):
        return True
    if any(x in low for x in ("gce o", "o level", "o-level", "gce n", "n level", "n-level", "secondary 4", "secondary 5")):
        return False
    return None


def selected_client_status(data: dict[str, Any], facts: dict[str, Any]) -> bool | None:
    age_raw = clean(data.get("age_next") or data.get("age_last_birthday"))
    try:
        age = int(float(age_raw)) if age_raw else None
    except Exception:
        age = None
    conditions: list[bool | None] = [
        (age >= 62) if age is not None else None,
        (not facts["english_proficient"]) if facts.get("english_proficient") is not None else None,
        _education_below_on_level(facts.get("education_level", "")),
    ]
    true_count = sum(v is True for v in conditions)
    unknown_count = sum(v is None for v in conditions)
    if true_count >= 2:
        return True
    if true_count + unknown_count < 2:
        return False
    return None


def apply_product_fna(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> None:
    """Populate investment-needs FNA only where the internal guide gives a deterministic rule."""
    # If an existing completed TFP already supplied FNA, preserve it.
    if facts.get("investment_goal") or facts.get("investment_amount_to_plan"):
        return

    premium = money_number(data.get("premium"))
    years = profile.fna_investment_years
    if profile.key == "ilp_10_flex_3" and premium > 0 and years:
        target = premium * years
        facts["investment_goal"] = fmt_money(target, compact=True)
        facts["investment_duration_years"] = str(years)
        existing = money_number(facts.get("investment_assets"))
        if facts.get("investment_assets"):
            facts["investment_existing"] = fmt_money(existing, compact=True) if existing else "0"
            facts["investment_amount_to_plan"] = fmt_money(max(target - existing, 0), compact=True)
        # When Page 8 investment assets are missing, leave existing/plan blank and flag in preflight.


def _choose_budget(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> tuple[float, str, str]:
    if profile.premium_mode == "single":
        amount = money_number(facts.get("single_budget")) or money_number(data.get("premium"))
        source = clean(facts.get("single_budget_source")) or clean(facts.get("source_of_funds"))
        return amount, source, "single"
    if profile.premium_mode == "annual":
        amount = money_number(facts.get("annual_budget")) or money_number(data.get("premium"))
        source = clean(facts.get("annual_budget_source")) or clean(facts.get("source_of_funds"))
        return amount, source, "annual"
    # Unknown product: preserve explicitly filled budget mode if available.
    if money_number(facts.get("annual_budget")):
        return money_number(facts["annual_budget"]), clean(facts.get("annual_budget_source")), "annual"
    if money_number(facts.get("single_budget")):
        return money_number(facts["single_budget"]), clean(facts.get("single_budget_source")), "single"
    return money_number(data.get("premium")), clean(facts.get("source_of_funds")), "unknown"


def affordability_assessment(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> dict[str, Any]:
    amount, source, mode = _choose_budget(data, facts, profile)
    income = money_number(facts.get("annual_income"))
    surplus = money_number(facts.get("annual_surplus"))
    assets = money_number(facts.get("total_assets")) or money_number(facts.get("net_assets"))

    source_low = source.lower()
    source_uses_surplus = any(x in source_low for x in ("income", "surplus", "salary", "trade"))
    source_uses_assets = any(x in source_low for x in ("saving", "cash", "asset", "cpf", "investment"))

    ratio_surplus = _ratio(amount, surplus)
    ratio_assets = _ratio(amount, assets)
    supervisor_risk = _ratio(amount, income) if mode == "annual" else None
    supervisor_concentration = _ratio(amount, assets) if mode == "single" else None

    substantial: bool | None = None
    if amount > 0:
        relevant: list[float] = []
        if source_uses_surplus and ratio_surplus is not None:
            relevant.append(ratio_surplus)
        if source_uses_assets and ratio_assets is not None:
            relevant.append(ratio_assets)
        if not relevant:
            # If source wording is absent/unclear, compute available ratios but do not pretend
            # that the correct funding base is known.
            substantial = None
        else:
            # Budget must be below 50% of the documented source base(s).
            substantial = any(r > 0.5 for r in relevant)

    return {
        "budget_amount": amount,
        "budget_source": source,
        "budget_mode": mode,
        "budget_to_surplus": ratio_surplus,
        "budget_to_assets": ratio_assets,
        "rsp_to_income": supervisor_risk,
        "lump_sum_to_assets": supervisor_concentration,
        "budget_substantial": substantial,
    }


def risk_comparison(facts: dict[str, Any]) -> str:
    client = normalise_risk(facts.get("risk_profile"))
    fund = normalise_risk(facts.get("fund_risk_profile"))
    if not client or not fund:
        return "unknown"
    c = RISK_ORDER.get(client.lower())
    f = RISK_ORDER.get(fund.lower())
    if c is None or f is None:
        return "unknown"
    if f == c:
        return "match"
    if f < c:
        return "lower"
    return "higher"


def priority_selections(data: dict[str, Any], profile: ProductProfile) -> dict[str, str]:
    """Return Page-5 choices: high/medium/low/na for the eight Yourself rows."""
    # Default to N/A, not a made-up Low priority.
    p = {
        "death": "na",
        "tpd": "na",
        "ci": "na",
        "retirement": "na",
        "investment": "na",
        "children": "na",
        "medical": "na",
        "monthly_income": "na",
    }
    explicit = data.get("priorities")
    if isinstance(explicit, dict):
        for key, value in explicit.items():
            val = clean(value).lower()
            if key in p and val in {"high", "medium", "low", "na", "n/a"}:
                p[key] = "na" if val == "n/a" else val
        return p

    retirement_goal = money_number(data.get("expected_retirement_income")) > 0
    if retirement_goal:
        p["retirement"] = "high"
        if profile.category in {"ilp", "unit_trust"}:
            p["investment"] = "medium"
        if profile.category == "ilp":
            p["death"] = "low"
    elif profile.category in {"ilp", "unit_trust"}:
        p["investment"] = "high"
        if profile.category == "ilp":
            p["death"] = "low"
    elif profile.category == "participating_life":
        p["retirement"] = "high" if retirement_goal else "medium"
    return p


# Page 5 exact field map for the Nov-2025 TFP.
PRIORITY_FIELD_MAP: dict[str, dict[str, str]] = {
    "death": {"high": "Check Box1001", "medium": "Check Box1002", "low": "Check Box1003", "na": "Check Box1004"},
    "tpd": {"high": "Check Box1009", "medium": "Check Box1010", "low": "Check Box1011", "na": "Check Box1012"},
    "ci": {"high": "Check Box1017", "medium": "Check Box1018", "low": "Check Box1019", "na": "Check Box1020"},
    "retirement": {"high": "Check Box1025", "medium": "Check Box1026", "low": "Check Box1027", "na": "Check Box1028"},
    "investment": {"high": "Check Box1033", "medium": "Check Box1034", "low": "Check Box1035", "na": "Check Box1036"},
    "children": {"high": "Check Box1042", "medium": "Check Box1043", "low": "Check Box1044", "na": "Check Box1045"},
    "medical": {"high": "Check Box1074", "medium": "Check Box1075", "low": "Check Box1076", "na": "Check Box1077"},
    "monthly_income": {"high": "Check Box1082", "medium": "Check Box1083", "low": "Check Box1084", "na": "Check Box1085"},
}


def extract_existing_priorities(fields: dict[str, Any]) -> dict[str, str]:
    """Read Page-5 priority choices from an already-completed TFP, if present."""
    out: dict[str, str] = {}
    for row, levels in PRIORITY_FIELD_MAP.items():
        for level, field_name in levels.items():
            if _checked(fields, field_name):
                out[row] = level
                break
    return out


def preflight_checks(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> list[dict[str, str]]:
    affordability = facts.get("affordability") or {}
    checks: list[dict[str, str]] = []

    def add(code: str, label: str, status: str, detail: str) -> None:
        checks.append({"code": code, "label": label, "status": status, "detail": detail})

    # Financial data / budget source.
    if facts.get("annual_income") and facts.get("annual_expenses"):
        add("cashflow", "Cash flow", "PASS", "Actual income and expenses are available; no default expense has been invented.")
    else:
        add("cashflow", "Cash flow", "REVIEW", "Income and/or expenses are not supported by uploaded data. Leave missing figures blank and obtain the client's actual data.")

    budget = affordability.get("budget_amount") or 0
    source = clean(affordability.get("budget_source"))
    if budget and source:
        substantial = affordability.get("budget_substantial")
        if substantial is False:
            add("budget", "Budget / concentration", "PASS", f"Budget source recorded as {source}; the documented funding-base ratio is below 50%.")
        elif substantial is True:
            add("budget", "Budget / concentration", "FAIL", f"Budget source recorded as {source}; the budget exceeds 50% of a documented funding base.")
        else:
            add("budget", "Budget / concentration", "REVIEW", f"Budget is available and source is {source}, but the correct surplus/assets funding base cannot be fully verified.")
    elif budget:
        add("budget", "Budget / concentration", "REVIEW", "Proposed premium/budget is available but source of funds is missing.")
    else:
        add("budget", "Budget / concentration", "REVIEW", "Budget amount is missing.")

    if affordability.get("rsp_to_income") is not None:
        ratio = affordability["rsp_to_income"]
        add("supervisor_affordability", "Supervisor affordability", "PASS" if ratio < 0.5 else "FAIL", f"RSP / annual income = {_percent(ratio)} (target < 50%).")
    if affordability.get("lump_sum_to_assets") is not None:
        ratio = affordability["lump_sum_to_assets"]
        add("supervisor_concentration", "Supervisor concentration", "PASS" if ratio < 0.5 else "FAIL", f"Lump sum / total assets = {_percent(ratio)} (target < 50%).")

    # FNA.
    if profile.key == "ilp_10_flex_3":
        if facts.get("investment_goal") and facts.get("investment_existing") and facts.get("investment_amount_to_plan"):
            add("fna", "Savings / investment FNA", "PASS", "10-Flex-3 target, Page-8 existing investments and amount-to-plan are reconciled.")
        else:
            add("fna", "Savings / investment FNA", "REVIEW", "10-Flex-3 FNA needs Page-8 existing investment data before the amount-to-plan can be completed.")

    # Risk and fund factsheet.
    if facts.get("risk_profile"):
        add("risk_profile", "Client risk profile", "PASS", f"Assigned profile: {facts['risk_profile']}.")
    elif profile.category in {"ilp", "unit_trust"}:
        add("risk_profile", "Client risk profile", "REVIEW", "Client risk profile is not supported by the uploaded data; do not hardcode Balanced/B.")

    if profile.category in {"ilp", "unit_trust"}:
        if facts.get("asset_class"):
            add("asset_class", "Fund asset class", "PASS", f"Asset class captured as {facts['asset_class']}.")
        else:
            add("asset_class", "Fund asset class", "REVIEW", "Asset class is missing. Obtain it from the fund factsheet.")
        comparison = risk_comparison(facts)
        if comparison == "match":
            add("fund_risk", "Fund risk vs client", "PASS", "Fund risk matches the client's risk profile.")
        elif comparison == "lower":
            add("fund_risk", "Fund risk vs client", "REVIEW", "At least one selected fund is lower risk than the client profile; include the lower-risk-fund disclaimer.")
        elif comparison == "higher":
            add("fund_risk", "Fund risk vs client", "FAIL", "Selected fund risk is higher than the client profile; suitability requires review.")
        else:
            add("fund_risk", "Fund risk vs client", "REVIEW", "Fund risk rating could not be matched to the client. Use insurer rating first, then FSM where appropriate.")

    # CKA.
    if profile.requires_cka:
        if facts.get("cka_met") is True:
            add("cka", "CKA", "PASS", "At least one qualifying CKA knowledge/experience criterion is explicitly met.")
        elif facts.get("cka_met") is False:
            add("cka", "CKA", "REVIEW", "CKA outcome is NOT MET. The acknowledgement/advice path on Page 12 must be completed correctly.")
        else:
            add("cka", "CKA", "REVIEW", "CKA cannot be determined from general job title/education level alone. Confirm qualifying education/professional qualification, transaction experience and work experience.")
        if facts.get("is_joint_case"):
            add("joint_cka", "Joint CKA", "REVIEW", "Joint case detected. A separate CKA is required for the other relevant client/account holder.")

    # Selected client / trusted individual.
    if facts.get("selected_client") is True:
        add("selected_client", "Selected Client", "REVIEW", "Client meets at least 2 of the 3 Selected Client indicators. Trusted Individual requirements must be addressed.")
    elif facts.get("selected_client") is None:
        add("selected_client", "Selected Client", "REVIEW", "Selected Client status cannot be fully determined because English proficiency and/or education level is incomplete.")

    # Signatures and priorities are generated/stamped elsewhere but must still be reviewed.
    add("signatures", "Signatures", "REVIEW", "Double-check every applicable signature/date, including Page 8, CKA acknowledgement (if applicable), disclosure checklist, Page 17, Page 18 and FA declaration.")
    add("priorities", "Personal priorities", "PASS", "Page-5 priorities are derived from the stated objective; verify them against the client's actual priorities before submission.")

    return checks


# ---------------------------------------------------------------------------
# BOR / Page-13 narrative assembly
# ---------------------------------------------------------------------------


def _product_objective(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> str:
    explicit = clean(data.get("primary_objective")) or clean(facts.get("investment_objective_text"))
    if explicit:
        return explicit
    if money_number(data.get("expected_retirement_income")) > 0:
        return "Retirement planning / wealth accumulation"
    if profile.category in {"ilp", "unit_trust"}:
        return "Savings / investment and wealth accumulation"
    if profile.category == "participating_life":
        return "Wealth accumulation and income planning"
    return ""


def _fund_sentence(facts: dict[str, Any], profile: ProductProfile) -> str:
    funds = facts.get("funds") or []
    if not funds:
        return ""
    names = [clean(f.get("name")) for f in funds if clean(f.get("name"))]
    if not names:
        return ""
    if len(names) == 1:
        base = f"The selected fund is {names[0]}."
    else:
        base = "The selected funds are " + "; ".join(names) + "."
    if facts.get("distribution_fund"):
        base += " The relevant distribution/dividend is not guaranteed and may vary."
    return base


def build_bor(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> str:
    age = clean(data.get("age_next") or data.get("age_last_birthday"))
    age_text = f" (ANB age {age})" if age else ""
    plan = clean(data.get("plan_name")) or profile.label
    objective = _product_objective(data, facts, profile)
    paragraphs: list[str] = []

    if profile.key == "ifast_unit_trust":
        paragraphs.append(f"Client{age_text} wishes to invest spare cash in the market and has expressed interest in the IFAST platform.")
    elif profile.key in {"ilp_10_flex_3", "goelite"}:
        paragraphs.append(f"Client{age_text} wishes to invest for wealth accumulation using an investment vehicle that also provides insurance protection elements.")
    elif profile.key == "singlife_flexi_income":
        paragraphs.append(f"Client{age_text} is looking for a wealth-accumulation plan with a stream of income and a lower-risk profile than a market-linked growth strategy.")
    elif objective:
        paragraphs.append(f"Client{age_text} has stated the objective of {objective.lower()}.")

    if plan:
        if profile.category == "unit_trust":
            paragraphs.append(f"{plan} / the selected IFAST investment is recommended to address the stated investment objective. {profile.product_feature_text}")
        else:
            paragraphs.append(f"{plan} is recommended based on the stated objective. {profile.product_feature_text}".strip())

    fund_sentence = _fund_sentence(facts, profile)
    if fund_sentence:
        paragraphs.append(fund_sentence + " Fund factsheet(s) should be presented to the client and retained with the case documentation.")

    comparison = risk_comparison(facts)
    if comparison == "match":
        paragraphs.append("The selected fund risk rating matches the client's documented risk profile.")
    elif comparison == "lower":
        paragraphs.append(
            "Based on the client's expressed preference to adopt a lower-risk approach, lower-risk fund(s) were recommended. "
            "It was explained that this may result in lower potential returns and the client may not achieve the intended financial objective within the desired timeframe. "
            "The client acknowledged the mismatch and confirmed comfort with proceeding."
        )
    elif comparison == "higher":
        paragraphs.append("[REVIEW REQUIRED] The selected fund risk appears higher than the client's documented risk profile. Suitability must be resolved before submission.")
    elif profile.category in {"ilp", "unit_trust"}:
        paragraphs.append("[REVIEW REQUIRED] Confirm the selected fund risk rating against the client's risk profile before submission.")

    if profile.death_benefit_text:
        paragraphs.append(profile.death_benefit_text)
    if profile.limitation_text:
        paragraphs.append(profile.limitation_text)
    if profile.charges_text:
        paragraphs.append(profile.charges_text)

    if profile.category in {"ilp", "unit_trust"}:
        paragraphs.append("Investment returns and distributions are not guaranteed. All investments carry risk and past performance is not indicative of future performance.")
    elif profile.category == "participating_life":
        paragraphs.append("Guaranteed and non-guaranteed benefits, participating-fund performance and surrender values should be read together with the Policy Illustration and Product Summary.")

    affordability = facts.get("affordability") or {}
    amount = affordability.get("budget_amount") or 0
    source = clean(affordability.get("budget_source"))
    if amount and source and affordability.get("budget_substantial") is False:
        paragraphs.append(
            f"The proposed {'single' if affordability.get('budget_mode') == 'single' else 'annual'} amount of ${fmt_money(amount)} will be funded from {source}. "
            "Based on the disclosed funding base, the budget is below the 50% concentration threshold."
        )
    elif amount and source:
        paragraphs.append(f"The proposed amount is ${fmt_money(amount)} and the stated source of funds is {source}. [REVIEW REQUIRED] Confirm the <50% affordability/concentration test before submission.")
    elif amount:
        paragraphs.append(f"The proposed amount is ${fmt_money(amount)}. [REVIEW REQUIRED] Record the actual source of funds and verify affordability/concentration before submission.")

    if facts.get("investment_goal") and facts.get("investment_amount_to_plan"):
        existing = facts.get("investment_existing") or "0"
        paragraphs.append(
            f"For savings/investment needs analysis, the target is ${facts['investment_goal']} over {facts.get('investment_duration_years') or 'the stated'} years, "
            f"less existing savings/investments of ${existing}, leaving ${facts['investment_amount_to_plan']} to plan for."
        )

    if facts.get("future_changes") is False:
        paragraphs.append("No material change in income, expenses, assets or liabilities within the next 12 months has been declared that is expected to affect affordability.")
    elif facts.get("future_changes") is True:
        reason = clean(facts.get("future_changes_reason"))
        paragraphs.append("A material financial change within the next 12 months has been declared" + (f": {reason}." if reason else ". [REVIEW REQUIRED] Record the details and impact on affordability."))

    # Keep BOR clean: remove accidental double spaces and empty paragraphs.
    return "\n\n".join(clean(p) for p in paragraphs if clean(p))


def page13_texts(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> dict[str, str]:
    objective = _product_objective(data, facts, profile)
    return {
        "objective": objective,
        "time_horizon": clean(facts.get("investment_time_horizon")) or clean(data.get("policy_term")),
        "features": profile.product_feature_text,
        "limitations": profile.limitation_text,
        "expected_return": clean(facts.get("expected_rate_of_return")),
        "charges": clean(facts.get("sales_charges")) or profile.charges_text,
        "investment_risk": clean(facts.get("investment_risk_text")) or ("Market / investment risk" if profile.category in {"ilp", "unit_trust"} else profile.limitation_text),
        "other_limitations": clean(facts.get("other_product_limitations")) or profile.limitation_text,
    }


def enrich_case(
    data: dict[str, Any],
    product_type: str,
    source_text: str = "",
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich one extracted case without inventing unsupported client facts."""
    fields = fields or {}
    profile = classify_product(data, product_type, source_text)
    facts = extract_compliance_facts(data, fields, source_text)
    apply_product_fna(data, facts, profile)
    facts["affordability"] = affordability_assessment(data, facts, profile)
    facts["risk_comparison"] = risk_comparison(facts)
    facts["priorities"] = facts.get("priorities_existing") or priority_selections(data, profile)
    facts["page13"] = page13_texts(data, facts, profile)
    facts["preflight"] = preflight_checks(data, facts, profile)

    # Promote safe facts to the case dict so the PDF mapper can consume them directly.
    promoted = (
        "annual_income",
        "annual_expenses",
        "annual_surplus",
        "personal_use_assets",
        "investment_assets",
        "cpf_total",
        "other_assets",
        "total_assets",
        "loans",
        "other_liabilities",
        "total_liabilities",
        "net_assets",
        "financial_disclosure_note",
        "financial_disclosure_partial",
        "annual_budget",
        "annual_budget_source",
        "single_budget",
        "single_budget_source",
        "source_of_funds",
        "investment_goal",
        "investment_duration_years",
        "investment_existing",
        "investment_amount_to_plan",
        "risk_return_preference",
        "risk_taking_preference",
        "risk_profile",
        "fund_risk_profile",
        "asset_class",
        "expected_rate_of_return",
        "sales_charges",
        "investment_risk_text",
        "other_product_limitations",
        "investment_time_horizon",
        "distribution_fund",
        "is_joint_case",
        "cka_education",
        "cka_professional_qualification",
        "cka_investment_experience",
        "cka_work_experience",
        "cka_met",
        "selected_client",
        "future_changes",
        "future_changes_reason",
    )
    for key in promoted:
        value = facts.get(key)
        if value not in (None, "", [], {}):
            data[key] = value
        elif isinstance(value, bool) or value is None:
            # Preserve explicit booleans / unknown state for rule evaluation.
            data[key] = value

    data["funds"] = facts.get("funds") or []
    data["product_profile_key"] = profile.key
    data["product_category"] = profile.category
    data["insurer_name"] = clean(data.get("insurer_name")) or profile.company
    data["premium_mode"] = profile.premium_mode
    data["requires_cka"] = profile.requires_cka
    data["disclosure_checklist"] = profile.disclosure_checklist
    data["affordability"] = facts["affordability"]
    data["priorities"] = facts["priorities"]
    data["page13"] = facts["page13"]
    data["preflight"] = facts["preflight"]
    data["recommendation_text"] = build_bor(data, facts, profile)
    return data


__all__ = [
    "PRODUCT_PROFILES",
    "PRIORITY_FIELD_MAP",
    "ProductProfile",
    "affordability_assessment",
    "assigned_risk_profile",
    "build_bor",
    "classify_product",
    "enrich_case",
    "extract_compliance_facts",
    "extract_existing_priorities",
    "fmt_money",
    "money_number",
    "normalise_risk",
    "preflight_checks",
    "priority_selections",
    "risk_comparison",
]
