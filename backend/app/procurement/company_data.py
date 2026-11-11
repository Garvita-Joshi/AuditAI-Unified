"""Read the user-provided company workflow workbook's curated JSON export."""
from functools import lru_cache
import json
from pathlib import Path
import re
from decimal import Decimal, InvalidOperation


DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "company_workflow_data.json"


TEST_AUTHORIZER_EMAIL = "prepares23@gmail.com"


@lru_cache(maxsize=1)
def company_data():
    if not DATA_PATH.exists():
        return {"company": "", "sheets": {}}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _records(sheet):
    return company_data().get("sheets", {}).get(sheet, [])


def _money(value):
    """Normalize spreadsheet money cells before Pydantic catalog validation.

    Numbers may serialize formula results as binary floats (for example
    448.40000000000003). Converting through ``str`` and quantizing to cents
    avoids treating floating-point representation noise as real precision.
    """
    if value is None or value == "":
        return None
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError, TypeError):
        return value


def employee_for_email(email):
    """Match only a complete normalized company email; never guess by name."""
    normalized = (email or "").strip().casefold()
    if not normalized:
        return None
    return next((row for row in _records("Employees")
                 if str(row.get("email", "")).strip().casefold() == normalized), None)


def requester_summary(user):
    employee = employee_for_email(getattr(user, "email", ""))
    return {
        "id": getattr(user, "id", None),
        "name": (employee or {}).get("full_name") or getattr(user, "full_name", None) or getattr(user, "email", "Unknown requester"),
        "email": getattr(user, "email", None),
        "employee_id": (employee or {}).get("employee_id"),
        "department": (employee or {}).get("department_name"),
        "designation": (employee or {}).get("designation"),
    }


def _department_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


_DEPARTMENT_ALIASES = {
    "sales": "sales and marketing",
    "it": "information technology",
    "hr": "human resources",
    "admin": "administration and facilities",
}


def department_head_for(user, requested_department=None):
    employee = employee_for_email(getattr(user, "email", ""))
    department = (employee or {}).get("department_name") or requested_department
    if not department:
        return None
    key = _department_key(_DEPARTMENT_ALIASES.get(str(department).strip().casefold(), department))
    head = next((row for row in _records("Department_Heads")
                 if _department_key(row.get("department_name")) == key), None)
    if not head and requested_department and employee:
        key = _department_key(_DEPARTMENT_ALIASES.get(str(requested_department).strip().casefold(), requested_department))
        head = next((row for row in _records("Department_Heads")
                     if _department_key(row.get("department_name")) == key), None)
    if not head:
        return None

    head_employee = next((row for row in _records("Employees")
                          if row.get("employee_id") == head.get("head_employee_id")), None)
    head_status = (head_employee or {}).get("status") or head.get("head_status")
    use_backup = str(head_status or "").casefold() != "active"
    if use_backup:
        person = {
            "employee_id": head.get("backup_employee_id"),
            "name": head.get("backup_name"),
            "email": TEST_AUTHORIZER_EMAIL,
            "original_email": head.get("backup_email"),
            "status": "Active",
            "is_backup": True,
        }
    else:
        person = {
            "employee_id": head.get("head_employee_id"),
            "name": head.get("head_name"),
            "email": TEST_AUTHORIZER_EMAIL,
            "original_email": head.get("head_email"),
            "status": head_status,
            "is_backup": False,
        }
    return {
        **person,
        "department": head.get("department_name"),
        "cost_center": head.get("cost_center"),
        "annual_budget_inr": head.get("annual_budget_inr"),
        "budget_used_inr": head.get("budget_used_inr"),
        "budget_remaining_inr": head.get("budget_remaining_inr"),
        "requester_department_matched": bool(employee),
    }


def workflow_owner_for(owner_group, label, user, requested_department=None):
    """Resolve preview assignees from the company workbook, never from the LLM."""
    text = f"{owner_group or ''} {label or ''}".casefold()
    if any(word in text for word in ("department", "manager", "budget owner")):
        return department_head_for(None, requested_department) or department_head_for(user, requested_department)
    role_name = None
    if "procurement" in text or "purchasing" in text:
        role_name = "Procurement Head"
    elif "finance" in text or "accounts payable" in text or "invoice" in text or "payment" in text:
        role_name = "Accounts Payable Lead" if any(word in text for word in ("accounts payable", "invoice", "payment")) else "Finance Head"
    elif "legal" in text or "contract" in text or "msa" in text or "sow" in text:
        role_name = "Legal Head"
    elif "security" in text or "privacy" in text or "data protection" in text:
        role_name = "Information Security Head"
    elif "it " in f"{text} " or "technology" in text or "technical" in text:
        # IT reviewer is resolved from the workbook's Information Technology department.
        return department_head_for(None, "Information Technology")
    elif "ceo" in text or "executive" in text or "final approval" in text:
        role_name = "CEO"
    if not role_name:
        return None

    role = next((row for row in _records("Workflow_Roles")
                 if str(row.get("role_name", "")).casefold() == role_name.casefold()), None)
    if not role:
        return None
    holder_id = role.get("holder_employee_id")
    holder = next((row for row in _records("Employees") if row.get("employee_id") == holder_id), None)
    active = str((holder or {}).get("status") or "Active").casefold() == "active"
    if active:
        return {"employee_id": holder_id, "name": role.get("holder_name"),
                "email": TEST_AUTHORIZER_EMAIL, "original_email": role.get("holder_email"),
                "status": "Active", "is_backup": False,
                "role": role_name}
    backup_id = role.get("backup_employee_id")
    backup = next((row for row in _records("Employees") if row.get("employee_id") == backup_id), None)
    return {"employee_id": backup_id, "name": role.get("backup_name"),
            "email": TEST_AUTHORIZER_EMAIL, "original_email": (backup or {}).get("email"),
            "status": "Active", "is_backup": True,
            "role": role_name} if role.get("backup_name") else None


def workbook_catalog():
    """Convert approved company offers to the sourcing catalog contract."""
    vendors = {row.get("vendor_id"): row for row in _records("Vendors")}
    result = []
    for offer in _records("Offers"):
        vendor = vendors.get(offer.get("vendor_id"))
        if not vendor:
            continue
        price_with_gst = offer.get("price_with_gst_inr")
        unit_price = _money(price_with_gst if price_with_gst is not None else offer.get("unit_price_inr"))
        if unit_price is None:
            continue
        valid = vendor.get("status") == "Approved" and vendor.get("account_verified") == "Yes"
        details = [offer.get("specifications"), offer.get("sla_terms")]
        result.append({
            "vendor_id": vendor.get("vendor_id"),
            "vendor_name": vendor.get("vendor_name"),
            "email": vendor.get("email"),
            "phone": vendor.get("phone"),
            "contact_name": vendor.get("contact_person"),
            "address": ", ".join(x for x in [vendor.get("city"), vendor.get("state")] if x),
            "country": "India",
            "category": offer.get("category") or vendor.get("category"),
            "approved": valid,
            "synthetic": str(vendor.get("is_synthetic", "Yes")).casefold() == "yes",
            "product": offer.get("item_name"),
            "sku": offer.get("brand_model") or offer.get("offer_id"),
            "description": ". ".join(str(value) for value in details if value),
            "currency": "INR",
            "unit_price": unit_price,
            "shipping": _money(offer.get("shipping_cost_inr")) or "0.00",
            "tax": "0.00",
            "available_quantity": offer.get("available_qty"),
            "unit": offer.get("unit"),
            "lead_time_days": offer.get("delivery_days"),
            "warranty_months": offer.get("warranty_months"),
            "payment_terms": f"Net {vendor.get('payment_terms_days')}" if vendor.get("payment_terms_days") is not None else None,
            "rating": vendor.get("rating"),
            "avg_delivery_days": vendor.get("avg_delivery_days"),
            "minimum_order_quantity": offer.get("min_order_qty") or 1,
            "return_policy": offer.get("sla_terms"),
            "price_valid_until": offer.get("price_valid_till"),
            "service_regions": [vendor.get("state")] if vendor.get("state") else [],
            "certifications": [],
            "onboarding_status": vendor.get("status"),
            "last_updated": None,
            "tax_registration": None,
            "bank_account": None,
            "source_reference": f"Company workbook Offers!{offer.get('offer_id')} / Vendors!{vendor.get('vendor_id')} (price includes GST)",
        })
    return result
