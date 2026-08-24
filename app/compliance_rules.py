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
        # IFAST is a platform and may be used for lump-sum or regular investing.
        # Determine the transaction mode from the actual case rather than the platform name.
        premium_mode="unknown",
        requires_cka=True,
        disclosure_checklist="unit_trust",
        product_feature_text=(
            "IFAST provides access to investment products such as unit trusts and other supported investment solutions."
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
    # Once a case has already been enriched, preserve that explicit classification.
    # This is important when pdf_fill.py receives the enriched case without the original
    # source-text blob (for example IFAST, where the platform name may live in Page 13).
    explicit_key = clean(data.get("product_profile_key"))
    explicit_category = clean(data.get("product_category"))
    explicit_mode = clean(data.get("premium_mode"))
    if explicit_key in PRODUCT_PROFILES:
        base = PRODUCT_PROFILES[explicit_key]
        overrides = dict(base.__dict__)
        if explicit_category:
            overrides["category"] = explicit_category
        if explicit_mode in {"annual", "single", "unknown"}:
            overrides["premium_mode"] = explicit_mode
        if isinstance(data.get("requires_cka"), bool):
            overrides["requires_cka"] = data["requires_cka"]
        if clean(data.get("disclosure_checklist")):
            overrides["disclosure_checklist"] = clean(data.get("disclosure_checklist"))
        return ProductProfile(**overrides)
    if explicit_key == "generic_ilp" or (explicit_category == "ilp" and data.get("requires_cka") is True):
        return ProductProfile(
            key="generic_ilp",
            label=clean(data.get("plan_name")) or "Investment-linked plan",
            company=clean(data.get("insurer_name") or data.get("insurer") or product_type),
            category="ilp",
            premium_mode=explicit_mode if explicit_mode in {"annual", "single"} else "unknown",
            requires_cka=True,
            disclosure_checklist=clean(data.get("disclosure_checklist")) or "life",
            product_feature_text="Investment-linked plan; use the insurer Product Summary for exact benefits and terms.",
            limitation_text="Investment values fluctuate and returns are not guaranteed. Use the Product Summary for surrender and withdrawal terms.",
            charges_text="Use the Product Summary for the exact ongoing fees and charges.",
        )

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
    """Return the CLIENT'S investment horizon only.

    Do not substitute a policy term (for example "Up to age 99") when the
    client's investment horizon is missing. The missing horizon belongs in
    Needs Attention instead of being silently converted into a Page-13 answer.
    """
    return _field(fields, "Text38") or clean(data.get("investment_time_horizon"))


def _horizon_from_risk_taking(risk_taking: str) -> str:
    code = clean(risk_taking).upper()[:1]
    # Page-10 bands. Bryan's approved examples display >10 years for High.
    return {"H": ">10 years", "M": "3 to <10 years", "L": "<3 years"}.get(code, "")

def _extract_funds(fields: dict[str, Any], data: dict[str, Any], source_text: str) -> list[dict[str, str]]:
    funds: list[dict[str, str]] = []

    # Preserve structured multi-fund data when the caller has it, including a
    # per-fund risk classification. This lets the lower-risk rule apply if ANY
    # selected fund is below the client's profile.
    supplied = data.get("funds")
    if isinstance(supplied, list):
        for item in supplied[:7]:
            if not isinstance(item, dict):
                continue
            name = clean(item.get("name"))
            if not name:
                continue
            funds.append({
                "name": name,
                "asset_class": clean(item.get("asset_class")),
                "amount": clean(item.get("amount") or item.get("invested_amount")),
                "risk_profile": normalise_risk(item.get("risk_profile") or item.get("fund_risk_profile")),
            })
        if funds:
            return funds

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
            fund = {"name": name, "asset_class": asset, "amount": amount}
            if i == 1 and normalise_risk(data.get("fund_risk_profile")):
                fund["risk_profile"] = normalise_risk(data.get("fund_risk_profile"))
            funds.append(fund)
    if not funds and clean(data.get("fund_name")):
        funds.append({
            "name": clean(data.get("fund_name")),
            "asset_class": clean(data.get("asset_class")) or _extract_asset_class_from_text(source_text),
            "amount": clean(data.get("fund_invested_amount")),
            "risk_profile": normalise_risk(data.get("fund_risk_profile")),
        })
    return funds

def extract_compliance_facts(
    data: dict[str, Any],
    fields: dict[str, Any] | None = None,
    source_text: str = "",
) -> dict[str, Any]:
    fields = fields or {}
    facts: dict[str, Any] = {}

    # Page 3 - adviser authorisation is an adviser-specific fact. The product
    # selected does not prove that the adviser is authorised for that category.
    fa_auth: list[str] = []
    for code, field_name in (
        ("health", "Health Insurance"),
        ("life_ilp", "Life Insurance  InvestmentLinked ILP"),
        ("collective_investment", "Collective Investment"),
        ("group", "Group Insurance"),
        ("general", "General Insurance"),
        ("other", "Others please specify"),
    ):
        if _checked(fields, field_name):
            fa_auth.append(code)
    supplied_auth = data.get("fa_authorization_categories")
    if isinstance(supplied_auth, (list, tuple, set)):
        for item in supplied_auth:
            code = clean(item).lower().replace(" ", "_")
            if code and code not in fa_auth:
                fa_auth.append(code)
    facts["fa_authorization_categories"] = fa_auth

    # Pages 6-7 - explicit portfolio / dependant / health choices. These are
    # questions to the client, so a blank response is never converted into No.
    facts["dependants_included"] = (
        data.get("dependants_included") if isinstance(data.get("dependants_included"), bool)
        else _explicit_yes_no(fields, "Check Box32", "Check Box33")
    )
    insurance_choice = clean(data.get("insurance_portfolio_choice"))
    if not insurance_choice:
        if _checked(fields, "yes p"):
            insurance_choice = "provide_details"
        elif _checked(fields, "yes refer"):
            insurance_choice = "promiseland_only"
        elif _checked(fields, "No Existing Insurance Policy with"):
            insurance_choice = "none_or_not_disclosed"
    facts["insurance_portfolio_choice"] = insurance_choice

    investment_choice = clean(data.get("investment_portfolio_choice"))
    if not investment_choice:
        if _checked(fields, "No Existing ILPCIS PolicyPortfolio2"):
            investment_choice = "provide_details"
        elif _checked(fields, "No Existing ILPCIS PolicyPortfolio3"):
            investment_choice = "promiseland_only"
        elif _checked(fields, "No Existing ILPCIS PolicyPortfolio1"):
            investment_choice = "none_or_not_disclosed"
    facts["investment_portfolio_choice"] = investment_choice
    facts["health_condition"] = (
        data.get("health_condition") if isinstance(data.get("health_condition"), bool)
        else _explicit_yes_no(fields, "y4", "n4")
    )

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
    facts["cashflow_included"] = (
        data.get("cashflow_included") if isinstance(data.get("cashflow_included"), bool)
        else _explicit_yes_no(fields, "HV", "1R")
    )
    facts["assets_liabilities_included"] = (
        data.get("assets_liabilities_included") if isinstance(data.get("assets_liabilities_included"), bool)
        else _explicit_yes_no(fields, "HV_4", "1R_4")
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
    )

    # Page 9 retirement FNA and savings/investment FNA. Preserve a completed
    # reference/supporting TFP when these fields are already available.
    facts["retirement_amt"] = _money_or_blank(_field(fields, "fill_27") or data.get("retirement_amt"))
    facts["retirement_income"] = _money_or_blank(_field(fields, "fill_29") or data.get("retirement_income"))
    facts["retirement_shortfall"] = _money_or_blank(_field(fields, "fill_311") or data.get("retirement_shortfall"))
    facts["retirement_years"] = _field(fields, "Text306") or clean(data.get("retirement_years"))
    facts["retirement_total_amt"] = _money_or_blank(_field(fields, "fill_33") or data.get("retirement_total_amt"))
    facts["retirement_other_sources"] = _money_or_blank(_field(fields, "fill_35") or data.get("retirement_other_sources"))
    facts["retirement_amt_plan"] = _money_or_blank(_field(fields, "fill_37") or data.get("retirement_amt_plan"))

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

    # Page 12 CKA acknowledgement path may require more than one tick (for
    # example: DID NOT PASS + proceed + suitable). Preserve all explicit ticks.
    cka_acknowledgements: list[str] = []
    ack_fields = (
        ("pass_no_advice", "Yes8"),
        ("pass_advice", "No8"),
        ("pass_suitable", "Yes9"),
        ("pass_not_suitable", "No9"),
        ("fail_proceed", "Check Box5"),
        ("fail_suitable", "Yes10"),
        ("fail_not_suitable", "No10"),
    )
    for value, field_name in ack_fields:
        if _checked(fields, field_name):
            cka_acknowledgements.append(value)
    supplied_ack = data.get("cka_acknowledgements")
    if isinstance(supplied_ack, (list, tuple, set)):
        for item in supplied_ack:
            value = clean(item)
            if value and value not in cka_acknowledgements:
                cka_acknowledgements.append(value)
    elif clean(data.get("cka_acknowledgement")):
        cka_acknowledgements.append(clean(data.get("cka_acknowledgement")))
    facts["cka_acknowledgements"] = cka_acknowledgements

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
    facts["investment_time_horizon"] = _extract_time_horizon(fields, data) or _horizon_from_risk_taking(risk_taking)

    # Page 13 business-trail facts. Keep each choice blank unless it is explicitly
    # present in a supporting form or supplied as structured case data.
    def checked_choice(pairs: tuple[tuple[str, str], ...], supplied_key: str) -> str:
        supplied = clean(data.get(supplied_key))
        if supplied:
            return supplied
        for value, field_name in pairs:
            if _checked(fields, field_name):
                return value
        return ""

    facts["client_source"] = checked_choice((
        ("existing_client", "Existing Client"), ("referred", "Referred by"),
        ("lead", "Lead from"), ("other", "Others"),
    ), "client_source")
    facts["prospecting_method"] = checked_choice((
        ("firm_premises", "At Firms premises"), ("client_premises", "Clients premises"),
        ("roadshow", "Roadshow"), ("retailer", "Retailer"),
        ("street_canvassing", "Street canvassing"), ("seminar", "Seminar"),
        ("phone", "Over the phone"), ("video", "Video conferencing"),
        ("internet_social", "InternetSocialmedia"), ("referral", "Referral"),
        ("unable_recall", "Unable to recall"), ("other", "Others_2"),
    ), "prospecting_method")
    facts["advisory_location"] = checked_choice((
        ("firm_premises", "At Firms premises_2"), ("client_premises", "Clients premises_2"),
        ("roadshow", "Roadshow_2"), ("retailer", "Retailer_2"),
        ("seminar", "Seminar_2"), ("phone", "Over the phone_2"),
        ("video", "Video conferencing_2"), ("unable_recall", "Unable to recall_2"),
        ("other", "Others_3"),
    ), "advisory_location")
    facts["advisory_approach"] = checked_choice((
        ("face_to_face", "Face to Face"), ("non_face_to_face", "Non Face to Face"),
    ), "advisory_approach")
    facts["prospecting_date"] = _field(fields, "Date166_af_date") or clean(data.get("prospecting_date"))
    facts["advisory_date"] = _field(fields, "Date167_af_date") or clean(data.get("advisory_date"))

    # Page 17 AML/CFT and Page 18 affordability acknowledgements. Only explicit
    # answers are promoted; blank declarations remain blank and are flagged.
    facts["replacement_intent"] = (
        data.get("replacement_intent") if isinstance(data.get("replacement_intent"), bool)
        else _explicit_yes_no(fields, "Check Box47", "Check Box48")
    )
    facts["payer_is_client"] = (
        data.get("payer_is_client") if isinstance(data.get("payer_is_client"), bool)
        else _explicit_yes_no(fields, "Check Box63", "Check Box64")
    )
    facts["sole_interest"] = (
        data.get("sole_interest") if isinstance(data.get("sole_interest"), bool)
        else _explicit_yes_no(fields, "Check Box67", "Check Box68")
    )
    facts["pep_self"] = data.get("pep_self") if isinstance(data.get("pep_self"), bool) else _explicit_yes_no(fields, "Check Box71", "Check Box72")
    facts["pep_family"] = data.get("pep_family") if isinstance(data.get("pep_family"), bool) else _explicit_yes_no(fields, "Check Box75", "Check Box76")
    facts["pep_associate"] = data.get("pep_associate") if isinstance(data.get("pep_associate"), bool) else _explicit_yes_no(fields, "Check Box79", "Check Box80")
    facts["affordability_comfortable"] = (
        data.get("affordability_comfortable") if isinstance(data.get("affordability_comfortable"), bool)
        else _explicit_yes_no(fields, "Check Box7_1", "Check Box8")
    )
    facts["disclosure_confirmed"] = bool(
        data.get("disclosure_confirmed") is True or _checked(fields, "Check Box42", "Check Box43")
    )
    facts["next_review_date"] = _field(fields, "date") or clean(data.get("next_review_date"))

    # Client/adviser actions are only treated as facts when explicitly recorded.
    # If this is an already-completed TFP, read the evidence from its BOR field.
    bor_source = ""
    for field_name, field_value in fields.items():
        if "Business Trail and why was the product" in str(field_name):
            bor_source = clean(field_value)
            if bor_source:
                break
    bor_low = bor_source.lower()
    facts["factsheet_presented"] = bool(
        data.get("factsheet_presented") is True
        or (bor_source and re.search(r"fund factsheet(?:\(s\)|s)?[^.\n]{0,24}presented", bor_low, flags=re.I))
    )
    facts["lower_risk_preference"] = bool(
        data.get("lower_risk_preference") is True
        or (bor_source and re.search(r"preference.*lower[- ]risk|lower[- ]risk approach", bor_low, flags=re.I))
    )
    facts["risk_mismatch_acknowledged"] = bool(
        data.get("risk_mismatch_acknowledged") is True
        or (bor_source and re.search(r"acknowledged the mismatch|comfortable proceeding", bor_low, flags=re.I))
    )

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
    """Choose the actual transaction budget/mode before using a product default.

    This matters for platforms and future products that can support either regular or
    lump-sum investing.  Explicit Page-8 budget fields always outrank the product label.
    """
    annual = money_number(facts.get("annual_budget"))
    single = money_number(facts.get("single_budget"))

    if annual and not single:
        return annual, clean(facts.get("annual_budget_source")) or clean(facts.get("source_of_funds")), "annual"
    if single and not annual:
        return single, clean(facts.get("single_budget_source")) or clean(facts.get("source_of_funds")), "single"

    explicit_mode = clean(data.get("premium_mode")).lower()
    if explicit_mode not in {"annual", "single"}:
        frequency_blob = " ".join([clean(data.get("premium_frequency")), clean(data.get("premium_term"))]).lower()
        explicit_mode = _premium_mode_from_text(frequency_blob)

    mode = explicit_mode if explicit_mode in {"annual", "single"} else profile.premium_mode
    if mode == "single":
        amount = single or money_number(data.get("premium"))
        source = clean(facts.get("single_budget_source")) or clean(facts.get("source_of_funds"))
        return amount, source, "single"
    if mode == "annual":
        amount = annual or money_number(data.get("premium"))
        source = clean(facts.get("annual_budget_source")) or clean(facts.get("source_of_funds"))
        return amount, source, "annual"

    # If both budget columns are populated, preserve the product/context default only if
    # it is known; otherwise leave mode unresolved rather than guessing.
    if annual and profile.premium_mode == "annual":
        return annual, clean(facts.get("annual_budget_source")) or clean(facts.get("source_of_funds")), "annual"
    if single and profile.premium_mode == "single":
        return single, clean(facts.get("single_budget_source")) or clean(facts.get("source_of_funds")), "single"
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
    """Compare client risk against all known selected-fund risks.

    Any higher-risk fund returns ``higher``. Otherwise any lower-risk fund
    returns ``lower`` so the required lower-risk disclaimer is triggered.
    ``match`` is returned only when all known selected fund risks match.
    """
    client = normalise_risk(facts.get("risk_profile"))
    if not client:
        return "unknown"
    c = RISK_ORDER.get(client.lower())
    if c is None:
        return "unknown"

    fund_risks: list[str] = []
    for fund in facts.get("funds") or []:
        r = normalise_risk(fund.get("risk_profile") or fund.get("fund_risk_profile"))
        if r:
            fund_risks.append(r)
    single = normalise_risk(facts.get("fund_risk_profile"))
    if single and single not in fund_risks:
        fund_risks.append(single)
    if not fund_risks:
        return "unknown"

    deltas: list[int] = []
    for r in fund_risks:
        f = RISK_ORDER.get(r.lower())
        if f is not None:
            deltas.append(f - c)
    if not deltas:
        return "unknown"
    if any(x > 0 for x in deltas):
        return "higher"
    if any(x < 0 for x in deltas):
        return "lower"
    return "match"

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

    # No explicit Page-5 priority evidence: do not infer a client's personal
    # priorities from the product selected or from the fact that a retirement
    # income figure was entered. Page 5 is left untouched and Needs Attention
    # asks the adviser to confirm the client's actual priorities.
    return {}


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

    def add(code: str, label: str, status: str, detail: str, page: str = "", level: str | None = None) -> None:
        if level is None:
            level = "checked" if status == "PASS" else "please_review"
        checks.append({"code": code, "label": label, "status": status, "detail": detail, "page": page, "level": level})

    # Page 3: do not infer an adviser's authorisation from the product selected.
    expected_auth = "collective_investment" if profile.category == "unit_trust" else ("life_ilp" if profile.category in {"ilp", "life", "participating_life"} else "")
    auth = set(facts.get("fa_authorization_categories") or [])
    if expected_auth and expected_auth in auth:
        add("fa_authorisation", "FA product authorisation", "PASS", "The applicable adviser product-authorisation category is explicitly recorded.", "Page 3")
    elif expected_auth:
        add("fa_authorisation", "FA product authorisation", "REVIEW", "Confirm the FA Representative's applicable product-authorisation category. The selected product alone does not prove adviser authorisation.", "Page 3", "action_required")

    # Pages 6-7: client choices must be explicit rather than defaulting to No.
    if isinstance(facts.get("dependants_included"), bool):
        add("dependants", "Dependants for needs analysis", "PASS", "The client's dependant-inclusion choice is explicitly recorded.", "Page 6")
    else:
        add("dependants", "Dependants for needs analysis", "REVIEW", "Confirm whether dependant(s) should be included in the Needs Analysis.", "Page 6", "action_required")
    if facts.get("insurance_portfolio_choice"):
        add("insurance_portfolio", "Existing insurance portfolio", "PASS", "The client's existing-insurance portfolio choice is explicitly recorded.", "Page 6")
    else:
        add("insurance_portfolio", "Existing insurance portfolio", "REVIEW", "Confirm whether existing insurance policies should be considered and complete the appropriate Page-6 choice.", "Page 6", "action_required")
    if facts.get("investment_portfolio_choice"):
        add("investment_portfolio", "Existing investment portfolio", "PASS", "The client's existing-investment portfolio choice is explicitly recorded.", "Page 7")
    else:
        add("investment_portfolio", "Existing investment portfolio", "REVIEW", "Confirm whether existing investments should be considered and complete the appropriate Page-7 choice.", "Page 7", "action_required")
    if isinstance(facts.get("health_condition"), bool):
        add("health_declaration", "Health condition declaration", "PASS", "The Page-7 health-condition Yes/No response is explicitly recorded.", "Page 7")
    else:
        add("health_declaration", "Health condition declaration", "REVIEW", "Complete the Page-7 health-condition Yes/No declaration; a blank response is not treated as No.", "Page 7", "action_required")

    # Page 8 cash flow and assets/liabilities: distinguish missing data from an
    # explicitly documented partial/non-disclosure.
    cash_decision = facts.get("cashflow_included")
    if cash_decision is True and facts.get("annual_income") and facts.get("annual_expenses"):
        add("cashflow", "Cash flow", "PASS", "Cash-flow inclusion is confirmed and actual income/expenses are available.", "Page 8")
    elif cash_decision is False and facts.get("financial_disclosure_note"):
        add("cashflow", "Cash flow", "REVIEW", "Cash flow is explicitly excluded/partially disclosed with a recorded reason. Review whether sufficient financial data has been collected.", "Page 8", "please_review")
    else:
        add("cashflow", "Cash flow", "REVIEW", "Confirm the Page-8 Cash Flow Yes/No choice and provide actual annual income/expenses if included.", "Page 8", "action_required")

    assets_decision = facts.get("assets_liabilities_included")
    has_assets = bool(facts.get("total_assets") or facts.get("personal_use_assets") or facts.get("investment_assets") or facts.get("cpf_total") or facts.get("other_assets"))
    has_liability_data = bool(facts.get("total_liabilities") or facts.get("loans") or facts.get("other_liabilities"))
    if assets_decision is True and has_assets and (has_liability_data or clean(facts.get("financial_disclosure_note"))):
        add("assets_liabilities", "Assets & liabilities", "PASS", "Assets/liabilities inclusion is confirmed and financial-position data is available.", "Page 8")
    elif assets_decision is False and facts.get("financial_disclosure_note"):
        add("assets_liabilities", "Assets & liabilities", "REVIEW", "Assets/liabilities are explicitly excluded/partially disclosed with a recorded reason. Review concentration assessment carefully.", "Page 8", "please_review")
    else:
        add("assets_liabilities", "Assets & liabilities", "REVIEW", "Confirm the Page-8 Assets & Liabilities Yes/No choice and provide actual figures if included. Do not assume zero liabilities.", "Page 8", "action_required")

    budget = affordability.get("budget_amount") or 0
    source = clean(affordability.get("budget_source"))
    if budget and source:
        substantial = affordability.get("budget_substantial")
        if substantial is False:
            add("budget", "Budget / concentration", "PASS", f"Budget source recorded as {source}; the documented funding-base ratio is below 50%.", "Pages 8 & 19")
        elif substantial is True:
            add("budget", "Budget / concentration", "FAIL", f"Budget source recorded as {source}; the budget exceeds 50% of at least one documented funding base. Review affordability/concentration before submission.", "Pages 8 & 19", "please_review")
        else:
            add("budget", "Budget / concentration", "REVIEW", f"Budget and source ({source}) are available, but the correct surplus/assets funding base cannot be fully verified.", "Pages 8 & 19", "action_required")
    elif budget:
        add("funding_source", "Source of funds / AML", "REVIEW", "The proposed premium/budget is known but its transaction funding source is not confirmed. Complete the actual source on Pages 8 and 17; do not substitute general source of income.", "Pages 8 & 17", "action_required")
    else:
        add("budget", "Budget amount", "REVIEW", "The transaction budget/premium could not be confirmed.", "Page 8", "action_required")

    if budget and affordability.get("budget_substantial") is None:
        add("affordability_basis", "Affordability / concentration basis", "REVIEW", "The 50% affordability/concentration checks cannot be completed until the relevant income/surplus/assets figures are confirmed.", "Pages 8, 18 & 19", "action_required")

    if affordability.get("rsp_to_income") is not None:
        ratio = affordability["rsp_to_income"]
        add("supervisor_affordability", "Regular-premium affordability", "PASS" if ratio < 0.5 else "FAIL", f"RSP / annual income = {_percent(ratio)} (target < 50%).", "Page 19", "checked" if ratio < 0.5 else "please_review")
    if affordability.get("lump_sum_to_assets") is not None:
        ratio = affordability["lump_sum_to_assets"]
        add("supervisor_concentration", "Lump-sum concentration", "PASS" if ratio < 0.5 else "FAIL", f"Lump sum / total assets = {_percent(ratio)} (target < 50%).", "Page 19", "checked" if ratio < 0.5 else "please_review")

    if profile.category in {"ilp", "unit_trust"}:
        if facts.get("investment_goal") and facts.get("investment_duration_years") and facts.get("investment_existing") and facts.get("investment_amount_to_plan"):
            add("fna", "Savings / investment FNA", "PASS", "Target, duration, existing investments and amount-to-plan are recorded for the investment need.", "Page 9")
        elif profile.key == "ilp_10_flex_3" and facts.get("investment_goal") and facts.get("investment_duration_years"):
            add("fna", "Savings / investment FNA", "REVIEW", "The 10-Flex-3 target/duration can be derived from the documented premium, but actual existing investments are still needed before amount-to-plan can be completed.", "Pages 8 & 9", "action_required")
        else:
            add("fna", "Savings / investment FNA", "REVIEW", "Complete the relevant Page-9 savings/investment need (target, duration, existing savings/investments and amount-to-plan). Do not derive a target from premium unless the approved product rule supports it.", "Page 9", "action_required")
    elif profile.key == "singlife_flexi_income":
        if facts.get("retirement_amt") or data.get("retirement_amt"):
            add("fna", "Retirement / savings FNA", "PASS", "Retirement/savings need information is available for the recommendation.", "Page 9")
        else:
            add("fna", "Retirement / savings FNA", "REVIEW", "Confirm and complete the relevant Page-9 retirement/savings needs analysis for this recommendation.", "Page 9", "action_required")

    if facts.get("risk_profile"):
        add("risk_profile", "Client risk profile", "PASS", f"Assigned profile: {facts['risk_profile']}.", "Pages 10 & 13")
    elif profile.category in {"ilp", "unit_trust", "participating_life"}:
        add("risk_profile", "Client risk profile", "REVIEW", "Client risk profile cannot be determined from the uploaded data. Do not assume Balanced/Aggressive or copy a reference case.", "Pages 10 & 13", "action_required")

    if profile.category in {"ilp", "unit_trust"}:
        if facts.get("investment_time_horizon"):
            add("time_horizon", "Investment time horizon", "PASS", f"Investment horizon: {facts['investment_time_horizon']}.", "Pages 10 & 13")
        else:
            add("time_horizon", "Investment time horizon", "REVIEW", "Client investment horizon is missing. The policy term is not used as a substitute.", "Pages 10 & 13", "action_required")
        if facts.get("asset_class"):
            add("asset_class", "Fund asset class", "PASS", f"Asset class captured as {facts['asset_class']}.", "Page 13")
        else:
            add("asset_class", "Fund asset class", "REVIEW", "Asset class is missing. Obtain it from the fund factsheet.", "Page 13", "action_required")
        comparison = risk_comparison(facts)
        if comparison == "match":
            add("fund_risk", "Fund risk vs client", "PASS", "Selected fund risk matches the client's risk profile.", "Pages 13-14")
        elif comparison == "lower":
            add("fund_risk", "Fund risk vs client", "REVIEW", "At least one selected fund is lower risk than the client profile. The lower-risk-fund disclaimer is included without inventing client acknowledgement.", "Page 14", "please_review")
            if not facts.get("lower_risk_preference"):
                add("lower_risk_rationale", "Lower-risk fund rationale", "REVIEW", "Record/confirm the client's actual reason for choosing the lower-risk fund; the system will not invent a lower-risk preference.", "Page 14", "action_required")
            if not facts.get("risk_mismatch_acknowledged"):
                add("risk_ack", "Risk mismatch acknowledgement", "REVIEW", "Confirm that the mismatch and possible lower returns have been explained and acknowledged before submission.", "Page 14", "action_required")
        elif comparison == "higher":
            add("fund_risk", "Fund risk vs client", "FAIL", "At least one selected fund is higher risk than the client profile. Suitability requires review before submission.", "Pages 13-14", "please_review")
        else:
            add("fund_risk", "Fund risk vs client", "REVIEW", "Fund risk rating could not be matched to the client. Use insurer risk rating first, then FSM where appropriate; for Tokio Marine's four-scale ratings, use FSM as guided by Compliance.", "Pages 13-14", "action_required")

        if facts.get("funds"):
            if facts.get("factsheet_presented"):
                add("factsheet", "Fund factsheet", "PASS", "Fund factsheet presentation is explicitly recorded.", "Page 14")
            else:
                add("factsheet", "Fund factsheet", "REVIEW", "Confirm that the applicable fund factsheet(s) were presented to the client. The TFP does not state this unless supported.", "Page 14", "action_required")

    if profile.category in {"ilp", "unit_trust", "participating_life"}:
        if _product_objective(data, facts, profile):
            add("objective", "Investment / insurance objective", "PASS", "Client objective is supported by the uploaded information or stated retirement-income input.", "Page 13")
        else:
            add("objective", "Investment / insurance objective", "REVIEW", "Client-specific objective is missing; the selected product is not used to invent the client's objective.", "Page 13", "action_required")
        if facts.get("expected_rate_of_return"):
            add("expected_return", "Expected rate of return", "PASS", f"Recorded expected rate of return: {facts['expected_rate_of_return']}.", "Page 13")
        else:
            add("expected_return", "Expected rate of return", "REVIEW", "Expected return is not supported by the uploaded information. Do not copy 6-8% or another reference-case figure.", "Page 13", "action_required")

    business_values = [facts.get("client_source"), facts.get("prospecting_method"), facts.get("advisory_location"), facts.get("advisory_approach")]
    if all(clean(v) for v in business_values):
        add("business_trail", "Business Trail details", "PASS", "Client source, prospecting method, advisory location and advisory approach are explicitly recorded.", "Page 13")
    else:
        add("business_trail", "Business Trail details", "REVIEW", "Complete the client source, prospecting method, advisory-session location and Face-to-Face/Non-Face-to-Face details. These are not inferred from the product.", "Page 13", "action_required")

    if profile.requires_cka:
        cka_acks = set(facts.get("cka_acknowledgements") or [])
        if facts.get("cka_met") is True:
            path_complete = ("pass_no_advice" in cka_acks) or ("pass_advice" in cka_acks and bool({"pass_suitable", "pass_not_suitable"} & cka_acks))
            if path_complete:
                level = "please_review" if "pass_not_suitable" in cka_acks else "checked"
                status = "FAIL" if "pass_not_suitable" in cka_acks else "PASS"
                add("cka", "CKA", status, "CKA is met and the applicable Page-12 acknowledgement/advice path is explicitly recorded.", "Pages 11-12", level)
            else:
                add("cka", "CKA", "REVIEW", "CKA is met, but the Page-12 advice/suitability acknowledgement path is incomplete.", "Pages 11-12", "action_required")
        elif facts.get("cka_met") is False:
            path_complete = "fail_proceed" in cka_acks and bool({"fail_suitable", "fail_not_suitable"} & cka_acks)
            if path_complete and "fail_suitable" in cka_acks:
                add("cka", "CKA", "PASS", "CKA is not met; proceed-with-advice and suitable-product acknowledgements are explicitly recorded.", "Pages 11-12")
            elif path_complete and "fail_not_suitable" in cka_acks:
                add("cka", "CKA", "FAIL", "CKA is not met and the client is proceeding with an unsuitable product; Appendix A / Senior Management approval is required.", "Page 12", "action_required")
            else:
                add("cka", "CKA", "REVIEW", "CKA outcome is NOT MET. Complete the proceed-with-advice and suitability acknowledgement path on Page 12.", "Pages 11-12", "action_required")
        else:
            add("cka", "CKA", "REVIEW", "CKA cannot be determined from a general job title or education label alone. Confirm the qualifying CKA criteria.", "Pages 11-12", "action_required")
        if facts.get("is_joint_case"):
            add("joint_cka", "Joint CKA", "REVIEW", "Joint case detected. Complete a separate CKA for the other relevant client/account holder.", "Pages 11-12", "action_required")

    if facts.get("selected_client") is True:
        add("selected_client", "Selected Client", "REVIEW", "Client meets at least 2 of the 3 Selected Client indicators. Trusted Individual requirements must be addressed.", "Page 4", "action_required")
    elif facts.get("selected_client") is None:
        add("selected_client", "Selected Client", "REVIEW", "Selected Client status cannot be fully determined because English proficiency and/or education level is incomplete.", "Page 4", "action_required")

    # Pages 15-16: identify the applicable checklist, but do not automatically
    # tick the client's disclosure acknowledgement.
    if profile.disclosure_checklist == "life":
        add("disclosure_route", "Disclosure checklist route", "PASS", "Life / ILP disclosure checklist applies; Unit Trust checklist does not.", "Page 15")
    elif profile.disclosure_checklist == "unit_trust":
        add("disclosure_route", "Disclosure checklist route", "PASS", "Unit Trust disclosure checklist applies; Life / ILP checklist does not.", "Page 16")
    else:
        add("disclosure_route", "Disclosure checklist route", "REVIEW", "The applicable disclosure checklist could not be determined from the product classification.", "Pages 15-16", "action_required")
    if profile.disclosure_checklist in {"life", "unit_trust"} and not facts.get("disclosure_confirmed"):
        page = "Page 15" if profile.disclosure_checklist == "life" else "Page 16"
        add("disclosure_ack", "Disclosure acknowledgement", "REVIEW", "Confirm that the applicable disclosure documents/information were provided and explained before ticking/signing the checklist acknowledgement.", page, "action_required")

    # Page 17: source is handled together with Page 8 above; separately require
    # the payer, sole-interest and political-exposure declarations.
    aml_answers = (facts.get("payer_is_client"), facts.get("sole_interest"), facts.get("pep_self"), facts.get("pep_family"), facts.get("pep_associate"))
    if all(isinstance(v, bool) for v in aml_answers):
        add("aml_declarations", "AML / CFT declarations", "PASS", "Payer, sole-interest and political-exposure Yes/No declarations are explicitly recorded.", "Page 17")
    else:
        add("aml_declarations", "AML / CFT declarations", "REVIEW", "Complete the Page-17 payer, sole-interest and political-exposure Yes/No declarations. Blank answers are not treated as No.", "Page 17", "action_required")

    if isinstance(facts.get("affordability_comfortable"), bool):
        level = "checked" if facts.get("affordability_comfortable") is True else "please_review"
        status = "PASS" if facts.get("affordability_comfortable") is True else "FAIL"
        add("affordability_ack", "Client affordability acknowledgement", status, "The Page-18 affordability/concentration comfort response is explicitly recorded.", "Page 18", level)
    else:
        add("affordability_ack", "Client affordability acknowledgement", "REVIEW", "Complete the Page-18 Yes/No acknowledgement on whether the premium/investment is affordable and comfortable.", "Page 18", "action_required")

    # Page 18-20 remain human acknowledgements/declarations. Runtime signature
    # checks report exactly which signatures were applied or deliberately held back.
    add("acknowledgements", "Client / FA acknowledgements", "REVIEW", "Review the Page 18 client authorization, Page 19 supervisor suitability items and Page 20 FA declaration before submission; these are not inferred from the product selected.", "Pages 18-20", "please_review")
    priorities_source = clean(facts.get("priorities_source"))
    if priorities_source in {"existing", "explicit"}:
        add("priorities", "Personal priorities", "PASS", "Page-5 priorities are explicitly supported by the case data; verify before submission.", "Page 5")
    else:
        add("priorities", "Personal priorities", "REVIEW", "Page-5 priorities were not explicitly provided. Confirm the client's actual priorities before submission.", "Page 5", "action_required")

    return checks

def _page13_defaults(profile: ProductProfile) -> dict[str, str]:
    if profile.key == "ilp_10_flex_3":
        return {
            "features": "A whole-life, regular-premium investment-linked plan (ILP) providing investment opportunities together with insurance protection.",
            "limitations": "Past performance, returns, distributions/dividends and capital are not guaranteed. Investment carries risk.",
            "charges": "Administrative charges, cost of insurance and other policy/fund charges: refer to the Product Summary.",
            "investment_risk": "Liquidity risk and market risk",
            "other_limitations": "Past performance, returns, distributions/dividends and capital are not guaranteed. Long-term investment.",
        }
    if profile.key == "goelite":
        return {
            "features": "A whole-life, single-premium investment-linked plan (ILP) providing investment opportunities together with insurance protection.",
            "limitations": "Past performance, returns, distributions/dividends and capital are not guaranteed. Investment carries risk.",
            "charges": "Administrative, establishment/insurance and other policy/fund charges: refer to the Product Summary.",
            "investment_risk": "Liquidity risk and market risk",
            "other_limitations": "Past performance, returns, distributions/dividends and capital are not guaranteed.",
        }
    if profile.key == "ifast_unit_trust":
        return {
            "features": "IFAST provides access to a range of investment products and services, including unit trusts.",
            "limitations": "Past performance, returns, distributions/dividends and capital are not guaranteed. Investment carries risk.",
            "charges": "Wrap fee and platform fee: refer to the applicable IFAST documents.",
            "investment_risk": "Market risk",
            "other_limitations": "Past performance, returns, distributions/dividends and capital are not guaranteed.",
        }
    if profile.key == "singlife_flexi_income":
        return {
            "features": "A participating whole-life insurance plan for wealth accumulation and income, with death and terminal-illness benefits. Refer to the Policy Illustration/Product Summary for exact guaranteed and non-guaranteed benefits.",
            "limitations": "Liquidity risk, early-surrender risk and non-guaranteed returns/benefits.",
            "charges": "Refer to the Product Summary and Policy Illustration.",
            "investment_risk": "Some returns/benefits of the product are not guaranteed",
            "other_limitations": "Liquidity risk, early-surrender risk and non-guaranteed returns/benefits.",
        }
    if profile.key == "fwd_invest_flexi_elite":
        return {
            "features": "An investment-linked life plan providing investment opportunities together with insurance protection. Refer to the FWD Product Summary for exact benefits and terms.",
            "limitations": "Investment values fluctuate and returns/capital are not guaranteed. Refer to the Product Summary for surrender and withdrawal terms.",
            "charges": "Refer to the FWD Product Summary for the exact charge names and rates.",
            "investment_risk": "Liquidity risk and market/investment risk",
            "other_limitations": "Past performance is not indicative of future performance. Investment returns and capital are not guaranteed.",
        }
    if profile.key == "hsbc_life":
        if profile.category == "ilp":
            return {
                "features": "An HSBC Life investment-linked plan. Refer to the Benefit Illustration/Product Summary for the exact benefits and policy terms.",
                "limitations": "Investment values fluctuate and returns/capital are not guaranteed. Refer to the Product Summary for product-specific limitations.",
                "charges": "Refer to the HSBC Product Summary for the exact fees and charges.",
                "investment_risk": "Market / investment risk",
                "other_limitations": "Refer to the HSBC Product Summary for surrender, withdrawal and non-guaranteed elements.",
            }
        return {
            "features": "Refer to the HSBC Benefit Illustration/Product Summary for the exact plan structure, benefits and policy term.",
            "limitations": "Refer to the HSBC Product Summary for surrender terms and non-guaranteed elements.",
            "charges": "Refer to the HSBC Product Summary for the exact fees and charges.",
            "investment_risk": "",
            "other_limitations": "Refer to the HSBC Product Summary for product-specific risks and limitations.",
        }
    if profile.category == "unit_trust":
        return {
            "features": "Unit trust investment; use the platform/product documents and fund factsheet(s) for the exact features.",
            "limitations": "Past performance and investment returns/capital are not guaranteed.",
            "charges": "Refer to the platform/product documents for applicable fees and charges.",
            "investment_risk": "Market risk",
            "other_limitations": "Investment carries risk and past performance is not indicative of future performance.",
        }
    if profile.category == "ilp":
        return {
            "features": "Investment-linked life plan; use the insurer Product Summary for exact benefits and terms.",
            "limitations": "Investment values fluctuate and returns/capital are not guaranteed. Refer to the Product Summary for surrender and withdrawal terms.",
            "charges": "Refer to the insurer Product Summary for the exact fees and charges.",
            "investment_risk": "Liquidity risk and market/investment risk",
            "other_limitations": "Investment carries risk and past performance is not indicative of future performance.",
        }
    return {
        "features": profile.product_feature_text,
        "limitations": profile.limitation_text,
        "charges": profile.charges_text,
        "investment_risk": "",
        "other_limitations": profile.limitation_text,
    }


def _product_objective(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> str:
    explicit = clean(data.get("primary_objective")) or clean(facts.get("investment_objective_text"))
    if explicit:
        return explicit
    if money_number(data.get("expected_retirement_income")) > 0:
        return "Retirement planning / wealth accumulation"
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
    """Build a clean Page-14 BOR without in-document review markers."""
    age = clean(data.get("age_next") or data.get("age_last_birthday"))
    age_text = f" (ANB age {age})" if age else ""
    plan = clean(data.get("plan_name")) or profile.label
    objective = _product_objective(data, facts, profile)
    paragraphs: list[str] = []

    if objective:
        objective_sentence = objective.strip().rstrip(" .;:")
        # Preserve the adviser/client wording instead of forcing it into a
        # grammatical construction such as "objective of client looking...".
        paragraphs.append(f"Client{age_text} stated the following objective: {objective_sentence}.")

    if plan:
        if profile.category == "unit_trust":
            prefix = f"{plan} / the selected investment is recommended"
        else:
            prefix = f"{plan} is recommended" if objective else f"The recommended product is {plan}."
        if objective:
            prefix += " for the stated objective."
        paragraphs.append(f"{prefix} {profile.product_feature_text}".strip())

    fund_sentence = _fund_sentence(facts, profile)
    if fund_sentence:
        paragraphs.append(fund_sentence)
        if facts.get("factsheet_presented"):
            paragraphs.append("The applicable fund factsheet(s) were presented to the client.")

    comparison = risk_comparison(facts)
    if comparison == "match":
        paragraphs.append("The selected fund risk rating matches the client's documented risk profile.")
    elif comparison == "lower":
        text = (
            "At least one selected fund is lower risk than the client's documented risk profile. "
            "A lower-risk fund may result in lower potential returns and the client may not achieve the intended financial objective within the desired timeframe."
        )
        if facts.get("lower_risk_preference"):
            text = "Based on the client's expressed preference to adopt a lower-risk approach, lower-risk fund(s) were recommended. " + text
        if facts.get("risk_mismatch_acknowledged"):
            text += " The mismatch and possible lower-return outcome were explained and acknowledged by the client."
        paragraphs.append(text)
    # Higher/unknown comparisons go to Needs Attention, not [REVIEW REQUIRED] in the PDF.

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

    if facts.get("investment_goal") and facts.get("investment_amount_to_plan"):
        existing = facts.get("investment_existing") or "0"
        paragraphs.append(
            f"For savings/investment needs analysis, the target is ${facts['investment_goal']} over {facts.get('investment_duration_years') or 'the stated'} years, "
            f"less existing savings/investments of ${existing}, leaving ${facts['investment_amount_to_plan']} to plan for."
        )

    if facts.get("future_changes") is False:
        paragraphs.append("No material change in income, expenses, assets or liabilities within the next 12 months has been declared that is expected to affect affordability.")
    elif facts.get("future_changes") is True and clean(facts.get("future_changes_reason")):
        paragraphs.append(f"A material financial change within the next 12 months has been declared: {clean(facts.get('future_changes_reason'))}.")

    if objective:
        strategy = "retirement strategy" if "retirement" in objective.lower() else "overall investment strategy"
        paragraphs.append(f"This recommendation forms part of the client's {strategy}.")

    return "\n\n".join(clean(p) for p in paragraphs if clean(p))

def page13_texts(data: dict[str, Any], facts: dict[str, Any], profile: ProductProfile) -> dict[str, str]:
    defaults = _page13_defaults(profile)
    return {
        "objective": _product_objective(data, facts, profile),
        "time_horizon": clean(facts.get("investment_time_horizon")),
        "features": clean(data.get("page13_features")) or defaults.get("features", ""),
        "limitations": clean(data.get("page13_limitations")) or defaults.get("limitations", ""),
        "expected_return": clean(facts.get("expected_rate_of_return")),
        "charges": clean(facts.get("sales_charges")) or defaults.get("charges", ""),
        "investment_risk": clean(facts.get("investment_risk_text")) or defaults.get("investment_risk", ""),
        "other_limitations": clean(facts.get("other_product_limitations")) or defaults.get("other_limitations", ""),
    }

def needs_attention_summary(checks: list[dict[str, str]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, str]]] = {"action_required": [], "please_review": [], "checked": []}
    for item in checks:
        level = clean(item.get("level")) or ("checked" if item.get("status") == "PASS" else "please_review")
        if level not in groups:
            level = "please_review"
        groups[level].append(item)
    attention_count = len(groups["action_required"]) + len(groups["please_review"])
    return {
        **groups,
        "counts": {k: len(v) for k, v in groups.items()},
        "attention_count": attention_count,
        "headline": "No items need attention" if attention_count == 0 else f"{attention_count} item(s) need attention",
    }


def enrich_case(
    data: dict[str, Any],
    product_type: str,
    source_text: str = "",
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich one extracted case without inventing unsupported client facts."""
    fields = fields or {}
    # Include actual form values in product classification. Some platform names (for
    # example IFAST) can appear in Page-13 fields later than the first chunk of PDF text.
    field_blob = " ".join(clean(v) for v in fields.values() if clean(v))
    profile = classify_product(data, product_type, source_text + " " + field_blob)
    facts = extract_compliance_facts(data, fields, source_text)
    apply_product_fna(data, facts, profile)
    facts["affordability"] = affordability_assessment(data, facts, profile)
    facts["risk_comparison"] = risk_comparison(facts)

    if facts.get("priorities_existing"):
        facts["priorities"] = facts["priorities_existing"]
        facts["priorities_source"] = "existing"
    elif isinstance(data.get("priorities"), dict) and data.get("priorities"):
        facts["priorities"] = priority_selections(data, profile)
        facts["priorities_source"] = "explicit"
    else:
        facts["priorities"] = priority_selections(data, profile)
        facts["priorities_source"] = "derived"

    facts["page13"] = page13_texts(data, facts, profile)
    facts["preflight"] = preflight_checks(data, facts, profile)
    facts["needs_attention"] = needs_attention_summary(facts["preflight"])

    promoted = (
        "annual_income", "annual_expenses", "annual_surplus", "personal_use_assets",
        "investment_assets", "cpf_total", "other_assets", "total_assets", "loans",
        "other_liabilities", "total_liabilities", "net_assets", "financial_disclosure_note",
        "financial_disclosure_partial", "annual_budget", "annual_budget_source", "single_budget",
        "single_budget_source", "source_of_funds", "retirement_amt", "retirement_income",
        "retirement_shortfall", "retirement_years", "retirement_total_amt", "retirement_other_sources",
        "retirement_amt_plan", "investment_goal", "investment_duration_years",
        "investment_existing", "investment_amount_to_plan", "risk_return_preference",
        "risk_taking_preference", "risk_profile", "fund_risk_profile", "asset_class",
        "expected_rate_of_return", "sales_charges", "investment_risk_text",
        "other_product_limitations", "investment_time_horizon", "distribution_fund",
        "is_joint_case", "cka_education", "cka_professional_qualification",
        "cka_investment_experience", "cka_work_experience", "cka_met", "selected_client",
        "future_changes", "future_changes_reason", "factsheet_presented", "lower_risk_preference",
        "risk_mismatch_acknowledged", "cka_acknowledgements", "fa_authorization_categories", "dependants_included",
        "insurance_portfolio_choice", "investment_portfolio_choice", "health_condition",
        "cashflow_included", "assets_liabilities_included", "client_source", "prospecting_method",
        "advisory_location", "advisory_approach", "prospecting_date", "advisory_date",
        "replacement_intent", "payer_is_client", "sole_interest", "pep_self", "pep_family",
        "pep_associate", "affordability_comfortable", "disclosure_confirmed", "next_review_date",
    )
    for key in promoted:
        value = facts.get(key)
        if value not in (None, "", [], {}):
            data[key] = value
        elif isinstance(value, bool) or value is None:
            data[key] = value

    data["funds"] = facts.get("funds") or []
    data["product_profile_key"] = profile.key
    data["product_category"] = profile.category
    data["insurer_name"] = clean(data.get("insurer_name")) or profile.company
    assessed_mode = clean((facts.get("affordability") or {}).get("budget_mode")).lower()
    data["premium_mode"] = assessed_mode if assessed_mode in {"annual", "single"} else profile.premium_mode
    data["requires_cka"] = profile.requires_cka
    data["disclosure_checklist"] = profile.disclosure_checklist
    data["affordability"] = facts["affordability"]
    data["priorities"] = facts["priorities"]
    data["priorities_source"] = facts["priorities_source"]
    data["page13"] = facts["page13"]
    data["preflight"] = facts["preflight"]
    data["needs_attention"] = facts["needs_attention"]
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
    "needs_attention_summary",
    "preflight_checks",
    "priority_selections",
    "risk_comparison",
]
