"""Company-owned catalog and extended approved offers for procurement sourcing."""
import json
import os
import re
from pathlib import Path
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict
from rapidfuzz import fuzz


class CatalogOffer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vendor_id: str = Field(min_length=1, max_length=100)
    vendor_name: str = Field(min_length=1, max_length=200)
    email: str = Field(pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    phone: str | None = Field(None, max_length=40)
    contact_name: str | None = Field(None, max_length=200)
    address: str | None = Field(None, max_length=1000)
    country: str | None = Field(None, max_length=100)
    category: str | None = Field(None, max_length=100)
    approved: bool
    synthetic: bool = False
    product: str = Field(min_length=1, max_length=500)
    sku: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=5000)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    unit_price: Decimal | None = Field(None, ge=0, max_digits=15, decimal_places=2)
    shipping: Decimal | None = Field(None, ge=0, max_digits=15, decimal_places=2)
    tax: Decimal | None = Field(None, ge=0, max_digits=15, decimal_places=2)
    available_quantity: int | None = Field(None, ge=0)
    unit: str | None = Field(None, max_length=100)
    lead_time_days: int | None = Field(None, ge=0)
    warranty_months: int | None = Field(None, ge=0)
    payment_terms: str | None = Field(None, max_length=200)
    rating: float | None = Field(None, ge=0, le=5)
    avg_delivery_days: int | None = Field(None, ge=0)
    minimum_order_quantity: int | None = Field(None, ge=1)
    return_policy: str | None = Field(None, max_length=1000)
    price_valid_until: str | None = Field(None, max_length=30)
    service_regions: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    onboarding_status: str | None = Field(None, max_length=100)
    last_updated: str | None = Field(None, max_length=30)
    tax_registration: None = None
    bank_account: None = None
    source_reference: str = Field(min_length=1, max_length=1000)


SYNONYMS = {
    'laptop': ['laptop', 'notebook', 'macbook', 'pc', 'computer', 'probook', 'thinkpad', 'hardware', 'dell', 'hp', 'lenovo'],
    'computer': ['computer', 'pc', 'desktop', 'tower', 'workstation', 'laptop', 'hardware'],
    'pc': ['pc', 'computer', 'desktop', 'tower', 'laptop'],
    'monitor': ['monitor', 'display', 'screen', 'it hardware'],
    'chair': ['chair', 'seating', 'furniture', 'ergonomic'],
    'desk': ['desk', 'table', 'workstation', 'furniture'],
    'cabinet': ['cabinet', 'drawer', 'filing', 'furniture'],
    'paper': ['paper', 'stationery', 'copier', 'office supplies'],
    'pen': ['pen', 'stationery', 'office supplies'],
    'whiteboard': ['whiteboard', 'board', 'office supplies'],
    'light': ['light', 'led', 'lamp', 'panel', 'electrical'],
    'ups': ['ups', 'power', 'backup', 'electrical'],
    'ac': ['ac', 'air conditioner', 'cooling', 'electrical'],
    'software': ['software', 'licence', 'license', 'app', 'saas', 'endpoint', 'it'],
    'cloud': ['cloud', 'server', 'hosting', 'it services', 'aws', 'azure'],
    'support': ['support', 'amc', 'maintenance', 'service', 'it services'],
    'website': ['website', 'web', 'design', 'maintenance', 'portal', 'it services'],
    'security': ['security', 'guard', 'facility services', 'cctv', 'surveillance', 'endpoint'],
    'cleaning': ['housekeeping', 'cleaning', 'hygiene', 'facility services', 'pest'],
    'courier': ['courier', 'logistics', 'shipping', 'freight', 'transport'],
    'audit': ['audit', 'accounting', 'tax', 'compliance', 'professional services'],
    'training': ['training', 'workshop', 'staffing', 'recruitment'],
    'cab': ['cab', 'taxi', 'car', 'travel', 'transport'],
    'hotel': ['hotel', 'room', 'stay', 'venue', 'conference', 'travel'],
    'print': ['print', 'printing', 'brochure', 'cards', 'banner', 'marketing'],
}

EXCHANGE_RATES = {
    ('INR', 'USD'): 0.012,
    ('USD', 'INR'): 83.5,
    ('EUR', 'INR'): 90.0,
    ('INR', 'EUR'): 0.011,
    ('GBP', 'INR'): 108.0,
    ('INR', 'GBP'): 0.0092,
}


def normalize_token(t: str) -> str:
    t = t.lower().strip()
    if len(t) > 3 and t.endswith('ies'):
        return t[:-3] + 'y'
    if len(t) > 3 and t.endswith('es'):
        return t[:-2]
    if len(t) > 3 and t.endswith('s'):
        return t[:-1]
    return t


def convert_currency(amount: Decimal | None, from_curr: str, to_curr: str) -> Decimal | None:
    if not amount or from_curr == to_curr:
        return amount
    rate = EXCHANGE_RATES.get((from_curr, to_curr))
    if rate:
        return Decimal(str(round(float(amount) * rate, 2)))
    return amount


def load_catalog():
    configured = os.getenv('COMPANY_VENDOR_CATALOG')
    if configured:
        path = Path(configured)
        if path.exists() and path.stat().st_size <= 5 * 1024 * 1024:
            raw = json.loads(path.read_text())
            if isinstance(raw, list) and len(raw) <= 10000:
                return [CatalogOffer.model_validate(item) for item in raw]

    root = Path(__file__).resolve().parents[3]
    offers = []
    seen_keys = set()

    # 1. Primary: Load curated company workflow dataset
    company_data_path = root / 'data' / 'company_workflow_data.json'
    if company_data_path.exists():
        from backend.app.procurement.company_data import workbook_catalog
        raw = workbook_catalog()
        for item in raw:
            key = (item.get('vendor_id'), item.get('sku'))
            if key not in seen_keys:
                seen_keys.add(key)
                offers.append(CatalogOffer.model_validate(item))

    # 2. Secondary: Load extended synthetic catalog (provides USD offers and broader product SKUs)
    synth_path = root / 'data' / 'vendors' / 'synthetic_catalog_full.json'
    if synth_path.exists() and synth_path.stat().st_size <= 5 * 1024 * 1024:
        try:
            raw_synth = json.loads(synth_path.read_text())
            if isinstance(raw_synth, list):
                for item in raw_synth:
                    key = (item.get('vendor_id'), item.get('sku'))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        offers.append(CatalogOffer.model_validate(item))
        except Exception:
            pass

    return offers


def search_catalog(req, offers):
    raw_query = f"{req.product or ''} {getattr(req, 'category', '') or ''}"
    preferred = {part.strip().casefold() for part in re.split(r'[,;\n]+', req.preferred_vendors or '') if part.strip()}

    tokens = [normalize_token(w) for w in re.findall(r'\w+', raw_query.lower())
              if len(w) > 1 and w not in {'a', 'an', 'the', 'for', 'of', 'and', 'with', 'need', 'buy', 'in', 'to', 'at', 'is', 'it'}]
    expanded_tokens = set(tokens)
    for t in tokens:
        for k, syns in SYNONYMS.items():
            if t == k or t in syns:
                expanded_tokens.update(syns)

    results = []
    for offer in offers:
        if not offer.approved:
            continue

        offer_text = f"{offer.product} {offer.description} {offer.category or ''} {offer.vendor_name} {offer.sku}".lower()
        offer_tokens = [normalize_token(w) for w in re.findall(r'\w+', offer_text)]

        token_hits = sum(1 for e in expanded_tokens if e in offer_tokens or any(e in ot for ot in offer_tokens))
        fuzz_score = fuzz.token_set_ratio(raw_query.lower(), offer_text)
        preferred_match = any(name in offer.vendor_name.casefold() for name in preferred)

        is_match = (token_hits > 0) or (fuzz_score >= 50) or preferred_match
        if not is_match:
            continue

        match_score = token_hits * 15 + (fuzz_score // 3) + (25 if preferred_match else 0)
        reasons = [f"Approved catalog match for {offer.product}"]
        if preferred_match:
            reasons.append('Matches your preferred supplier')

        # Currency handling & estimated total
        unit_price = offer.unit_price
        shipping = offer.shipping or Decimal('0.00')
        tax = offer.tax or Decimal('0.00')
        converted = False

        if offer.currency != req.currency and req.currency:
            converted_unit = convert_currency(unit_price, offer.currency, req.currency)
            converted_ship = convert_currency(shipping, offer.currency, req.currency)
            converted_tax = convert_currency(tax, offer.currency, req.currency)
            converted = True
            reasons.append(f"Catalog currency is {offer.currency} (~{req.currency} {converted_unit:,.2f}/unit)")
        else:
            converted_unit, converted_ship, converted_tax = unit_price, shipping, tax

        total = None
        over_budget = False
        if all(v is not None for v in (converted_unit, converted_ship, converted_tax)):
            total = converted_unit * req.quantity + converted_ship + converted_tax
            if req.budget is not None and total > req.budget:
                over_budget = True
                reasons.append(f"Catalog list total {req.currency} {total:,.2f} exceeds target budget {req.currency} {req.budget:,.2f}; pricing can be negotiated in RFQ")
            elif req.budget is not None:
                reasons.append(f"Estimated total {req.currency} {total:,.2f} is within budget")

        if offer.available_quantity is not None and offer.available_quantity < req.quantity:
            reasons.append(f"Catalog lists {offer.available_quantity} available units; custom delivery quote needed for {req.quantity} units")

        status = 'needs_vendor_confirmation'
        results.append({
            'offer': offer.model_dump(mode='json'),
            'estimated_total': str(total) if total is not None else None,
            'status': status,
            'over_budget': over_budget,
            'reasons': reasons,
            'match_score': match_score,
            'preference_match': preferred_match,
            'unverified': ['Delivery deadline and location', 'Preferences and mandatory conditions', 'Current pricing and availability'],
            'rfq_draft': (
                f"Please quote {req.quantity} units of {req.product} ({offer.sku}), delivered to "
                f"{req.delivery_location or 'Jaipur, India'} by {req.delivery_deadline or 'convenient date'}. "
                f"Include shipping and tax in {req.currency}. Preferences: {req.specifications}. "
                f"Mandatory conditions: {req.mandatory_conditions}. Please confirm availability, warranty and payment terms. "
                "This inquiry is not an order."
            ),
        })

    # Sort: Preferred vendors first if prioritized, then within-budget before over-budget, then highest match score
    results.sort(key=lambda item: (
        not item['preference_match'] if req.vendor_preference == 'prioritize' else False,
        item['over_budget'],
        -item['match_score'],
        float(item['estimated_total']) if item.get('estimated_total') else float('inf')
    ))
    return results[:50]
