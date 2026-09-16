from __future__ import annotations

"""Compliance guideline bridge shared with the AI TFP Checker rulebook.

The Form Filler already has detailed deterministic filling logic in compliance_rules.py.
This module adds the latest Checker rulebook guardrails to the generated case review
without replacing insurer/template-specific behaviour.

Source: MWM-Ai-TFP-Checker/rules.json (TFP-001 to TFP-044).
"""

from typing import Any


RULEBOOK_VERSION = "AI TFP Checker V1 / TFP-001..TFP-044"
RULE_IDS = tuple(f"TFP-{i:03d}" for i in range(1, 45))

# Full coverage map, kept deliberately concise here because the Form Filler's detailed
# deterministic checks already live in compliance_rules.py.  This makes it auditable
# that all Checker rule areas are recognised by the Form Filler.
RULE_AREAS: dict[str, str] = {
    "TFP-001": "Sales advisory dates",
    "TFP-002": "Selected client suitability",
    "TFP-003": "Budget & source of funds",
    "TFP-004": "Needs & shortfall",
    "TFP-005": "CKA completion",
    "TFP-006": "Fund risk alignment – higher risk",
    "TFP-007": "Basis of recommendation",
    "TFP-008": "Replacement section",
    "TFP-009": "Projection source",
    "TFP-010": "Projection disclaimer",
    "TFP-011": "Personal priorities",
    "TFP-012": "Selected-client questions",
    "TFP-013": "Trusted individual / accompaniment",
    "TFP-014": "Dependants",
    "TFP-015": "Existing portfolio",
    "TFP-016": "Cash flow",
    "TFP-017": "Net worth / assets & liabilities",
    "TFP-018": "FNA assumption – income replacement",
    "TFP-019": "FNA assumption – rate of return",
    "TFP-020": "Shortfall calculation accuracy",
    "TFP-021": "Premium vs budget",
    "TFP-022": "Budget utilisation",
    "TFP-023": "Substantial budget declaration",
    "TFP-024": "Need indicated but shortfall absent",
    "TFP-025": "Shortfall not fully met",
    "TFP-026": "Rider relevance",
    "TFP-027": "Risk profiling completion",
    "TFP-028": "Fund selection & allocation",
    "TFP-029": "Sum assured vs shortfall",
    "TFP-030": "Product/rider details",
    "TFP-031": "Time horizon alignment",
    "TFP-032": "Budget maximisation when shortfall unmet",
    "TFP-033": "Benefits, features & limitations",
    "TFP-034": "Misleading comparative claims",
    "TFP-035": "Policy term / MIP / premium term accuracy",
    "TFP-036": "Fund risk alignment – lower risk",
    "TFP-037": "ILP premium flexibility / shorter-payment narrative",
    "TFP-038": "Ongoing policy charges accuracy",
    "TFP-039": "CKA fail handling / fund recommendation wording",
    "TFP-040": "Source of funds / affordability consistency",
    "TFP-041": "Product feature accuracy",
    "TFP-042": "Compulsory completion – client/rep details",
    "TFP-043": "Compulsory completion – declarations/questions",
    "TFP-044": "Signatures and dates present",
}


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return str(value or "").strip()


def _num(value: Any) -> float:
    text = str(value or "").lower().replace("s$", "").replace("$", "").replace(",", "").strip()
    if not text:
        return 0.0
    mult = 1.0
    if text.endswith("k"):
        mult, text = 1_000.0, text[:-1]
    elif text.endswith("m"):
        mult, text = 1_000_000.0, text[:-1]
    try:
        return float(text) * mult
    except Exception:
        return 0.0


def apply_checker_guidelines(data: dict[str, Any]) -> dict[str, Any]:
    """Add Checker-rulebook guardrails to the Form Filler review output.

    This is intentionally conservative: it never invents client facts or silently
    ticks declarations. Existing compliance_rules.py remains the source of detailed
    page-level filling decisions.
    """
    data["compliance_rulebook_version"] = RULEBOOK_VERSION
    data["compliance_rule_ids"] = list(RULE_IDS)

    review = data.get("needs_attention") if isinstance(data.get("needs_attention"), dict) else {}
    groups = {
        "action_required": list(review.get("action_required") or []),
        "please_review": list(review.get("please_review") or []),
        "checked": list(review.get("checked") or []),
    }

    existing_codes = {
        str(item.get("code"))
        for items in groups.values()
        for item in items
        if isinstance(item, dict) and item.get("code")
    }

    def add(group: str, code: str, label: str, detail: str, page: str = "", rule_id: str = "") -> None:
        if code in existing_codes:
            return
        groups[group].append({
            "code": code,
            "label": label,
            "status": "PASS" if group == "checked" else "REVIEW",
            "detail": detail,
            "page": page,
            "level": group,
            "rule_id": rule_id,
        })
        existing_codes.add(code)

    # TFP-003 / 021 / 040: affordability and source-of-funds consistency.
    employment = _text(data, "employment_status").lower()
    source_of_funds = _text(data, "source_of_funds")
    premium = _num(data.get("premium"))
    budget = _num(data.get("budget")) or _num(data.get("client_budget"))
    if any(x in employment for x in ("retired", "unemployed", "housewife", "student")) and not source_of_funds:
        add("action_required", "checker_source_of_funds", "Source of funds / affordability", "For a non-gainfully employed client, record the source of funds and how the premium can be sustained.", "Pages 8, 18–19", "TFP-003")
    if premium > 0 and budget > 0 and premium > budget:
        add("action_required", "checker_premium_budget", "Premium vs budget", "Recommended premium exceeds the stated budget. Recheck affordability and document the reason if proceeding.", "Pages 8, 13, 18–19", "TFP-021")

    # TFP-004 / 011 / 024 / 025 / 032: recommendation must be supported by a need/shortfall.
    bor = _text(data, "recommendation_text")
    shortfall = _num(data.get("retirement_shortfall")) or _num(data.get("shortfall"))
    if not bor:
        add("action_required", "checker_bor", "Basis of Recommendation", "The recommendation needs a meaningful basis tied to the client's actual needs, circumstances and product/fund selected.", "Page 13", "TFP-007")
    if _text(data, "plan_name") and not shortfall and not _text(data, "fna_justification") and not _text(data, "primary_objective"):
        add("please_review", "checker_need_shortfall", "Need / shortfall linkage", "Confirm that the recommendation is supported by a documented need/shortfall or a clear client-specific justification.", "Pages 5, 9, 13", "TFP-004")

    # TFP-005 / 027 / 028: investment suitability completeness.
    category = _text(data, "product_category").lower()
    if category in {"ilp", "unit_trust"}:
        if not _text(data, "risk_profile"):
            add("action_required", "checker_risk_profile", "Financial Risk Profiling", "Complete the client's financial risk profile for the investment/life-policy recommendation.", "Page 10", "TFP-027")
        if not _text(data, "fund_name"):
            add("action_required", "checker_fund_selection", "Fund selection / allocation", "State the recommended fund(s) and respective allocation where an ILP/investment recommendation includes funds.", "Pages 13–14", "TFP-028")

    # TFP-009 / 010 / 034: projections and performance wording must be sourced and qualified.
    projection_fields = " ".join(_text(data, k) for k in ("expected_rate_of_return", "projection", "projected_return", "recommendation_text"))
    has_projection = any(token in projection_fields.lower() for token in ("projected", "projection", "% return", "expected return", "performance"))
    if has_projection:
        add("please_review", "checker_projection_source", "Projection / performance source", "Verify every projection or performance figure against an official PI/PS/PHS/Fund Factsheet/prospectus source; do not rely on own-calculation figures.", "Page 13", "TFP-009")
        add("please_review", "checker_projection_disclaimer", "Projection disclaimer", "Ensure projection/performance wording clearly states the applicable non-guaranteed/past-performance caution and does not imply certainty.", "Page 13", "TFP-010")

    # TFP-035 / 037 / 038 / 041: official product terms control.
    if _text(data, "plan_name"):
        add("please_review", "checker_product_terms", "Product terms / features", "Verify policy term, premium-payment term, MIP, product features, limitations and charges against the official insurer/product documents. Keep these terms distinct.", "Page 13", "TFP-035")
    if category == "ilp":
        add("please_review", "checker_ilp_flexibility", "ILP premium flexibility", "If shorter-payment/premium-holiday flexibility is described, also disclose ongoing charges, sustainability/lapse risk, impact on objectives and any possible need for additional contributions/top-ups.", "Page 13", "TFP-037")

    # TFP-042 / 043: compulsory fields/questions are not silently treated as complete.
    missing_core = [label for key, label in (("client_name", "client name"), ("nric", "NRIC/ID"), ("adviser_name", "FA representative"), ("plan_name", "product/plan")) if not _text(data, key)]
    if missing_core:
        add("action_required", "checker_core_fields", "Compulsory client / representative details", "Complete the mandatory fields: " + ", ".join(missing_core) + ".", "Applicable TFP pages", "TFP-042")

    # TFP-044 is handled at runtime after signature files are known; flag rule coverage here.
    add("checked", "checker_rulebook_synced", "Compliance guideline set", f"Form Filler is using the {RULEBOOK_VERSION} guideline set alongside its deterministic page-level checks.", "", "TFP-001–TFP-044")

    groups["counts"] = {k: len(groups[k]) for k in ("action_required", "please_review", "checked")}
    data["needs_attention"] = groups
    return data
