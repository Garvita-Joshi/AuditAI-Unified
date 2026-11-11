"""Sourcing graph: company catalog -> public discovery -> ranked shortlist -> RFQ drafts."""
import re
from decimal import Decimal
from typing import TypedDict
from urllib.parse import quote_plus
from langgraph.graph import END, START, StateGraph
from backend.app.sourcing.catalog import load_catalog, search_catalog
from backend.app.sourcing.requirements import Requirements
from backend.app.agentic_ai.gemini import rank_candidates
from backend.app.agentic_ai.discovery import discover_public_vendors


class SourcingState(TypedDict, total=False):
    requirements: dict
    offers: list
    matches: list
    shortlist: list
    drafts: list
    matched_vendor_count: int
    excluded_offer_count: int
    ranking_method: str
    web_discovery: dict


def _catalog_search(state: SourcingState) -> dict:
    req = Requirements.model_validate(state['requirements'])
    offers = load_catalog()
    matched = search_catalog(req, offers)
    return {
        'offers': offers,
        'matches': matched,
        'matched_vendor_count': len({item['offer']['vendor_id'] for item in matched if item['status'] != 'excluded'}),
        'excluded_offer_count': sum(item.get('status') == 'excluded' for item in matched),
    }


def _public_discovery(state: SourcingState) -> dict:
    req = Requirements.model_validate(state['requirements'])
    known = list({offer.vendor_name for offer in state.get('offers', []) if getattr(offer, 'vendor_name', None)})
    return {'web_discovery': discover_public_vendors(req.model_dump(mode='json'), known)}


def _rank_offers(state: SourcingState) -> dict:
    req = Requirements.model_validate(state['requirements'])
    tokens = {part.casefold() for part in (req.product or '').split() if len(part) > 2}
    ranked, seen = [], set()

    for match in state.get('matches', []):
        offer = match['offer']
        if match.get('status') == 'excluded' or offer['vendor_id'] in seen:
            continue
        seen.add(offer['vendor_id'])

        text = f"{offer['product']} {offer.get('description') or ''} {offer.get('category') or ''}".casefold()
        keyword_count = sum(token in text for token in tokens)
        cost = float(match['estimated_total']) if match.get('estimated_total') else None
        budget = float(req.budget) if req.budget is not None else None

        reasons = list(match.get('reasons') or [f"Approved catalog match for {offer['product']}"])
        score = min(40, keyword_count * 15)

        if match.get('preference_match'):
            score += 25
            if 'Matches your preferred supplier' not in reasons:
                reasons.append('Matches your preferred supplier')

        if cost is not None and budget and budget > 0:
            if cost <= budget:
                score += 25
                if not any('within budget' in r for r in reasons):
                    reasons.append(f"Estimated catalog total {req.currency} {cost:,.2f} is within budget")
            else:
                score += 10
                if not any('exceeds target budget' in r for r in reasons):
                    reasons.append(f"Catalog list price {req.currency} {cost:,.2f} exceeds target budget; volume discount can be requested in RFQ")

        if offer.get('lead_time_days') is not None:
            score += 10
            reasons.append(f"Catalog lists an estimated {offer['lead_time_days']}-day lead time; confirm with supplier")
        if offer.get('avg_delivery_days') is not None:
            score += 5
            reasons.append(f"Company vendor record lists {offer['avg_delivery_days']} average delivery days")
        if offer.get('rating') is not None:
            score += round(float(offer['rating']) * 2)
            reasons.append(f"Company vendor record rating: {offer['rating']}/5")
        if cost is not None and not any('supplier quote' in r for r in reasons):
            reasons.append('Current price, shipping, tax, stock and terms require a supplier quote')

        ranked.append({**match, 'score': score, 'reasons': reasons})

    ranked.sort(key=lambda item: (
        not item.get('preference_match', False) if req.vendor_preference == 'prioritize' else False,
        -item['score'],
        float(item['estimated_total']) if item.get('estimated_total') else float('inf')
    ))

    # If no catalog offers matched, promote public web & LinkedIn discovery leads into the shortlist
    if not ranked:
        web_discovery = state.get('web_discovery') or {}
        public_leads = web_discovery.get('results') or []
        for idx, lead in enumerate(public_leads[:5], start=1):
            vendor_name = lead['name']
            lead_url = lead.get('website_url') or lead.get('source_url') or f"https://www.google.com/search?q={quote_plus(vendor_name)}"
            linkedin_url = lead.get('linkedin_url') or f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(vendor_name)}"
            google_url = lead.get('google_search_url') or f"https://www.google.com/search?q={quote_plus(vendor_name + ' ' + (req.product or ''))}"

            lead_offer = {
                'vendor_id': f"PUB_{idx:03d}",
                'vendor_name': vendor_name,
                'email': lead.get('contact_email') or f"contact@{re.sub(r'[^a-zA-Z0-9]', '', vendor_name).lower()}.com",
                'product': req.product or 'Requested Product / Service',
                'sku': f"LEAD-{idx:03d}",
                'currency': req.currency or 'INR',
                'unit_price': None,
                'shipping': '0.00',
                'tax': '0.00',
                'synthetic': False,
                'category': req.category,
                'is_external': True,
                'website_url': lead_url,
                'linkedin_url': linkedin_url,
                'google_search_url': google_url,
                'source_reference': f"Discovered via {lead.get('platform', 'Google/LinkedIn')}: {lead_url}",
            }

            _, lead_rfq_body = format_detailed_rfq(
                req,
                vendor_name=lead_offer['vendor_name'],
                contact_name=lead_offer.get('contact_name'),
                offer=lead_offer,
            )
            ranked.append({
                'offer': lead_offer,
                'score': 65 - (idx * 5),
                'reasons': [
                    f"Discovered via {lead.get('platform', 'Google / LinkedIn')} for '{req.product}'",
                    lead.get('fit_reason') or lead.get('offering') or 'Supplier identified from external market search',
                    'External vendor: click Open in Google / LinkedIn to review profile and credentials',
                ],
                'status': 'public_lead',
                'estimated_total': None,
                'unverified': ['Delivery deadline and location', 'Pricing and terms', 'Vendor verification'],
                'rfq_draft': lead_rfq_body,
            })

        ranking_method = 'AI Public Web & LinkedIn Discovery (External Suppliers)' if ranked else 'No vendors found'
        return {
            'shortlist': ranked[:10],
            'ranking_method': ranking_method,
            'matched_vendor_count': len(ranked),
        }

    # If catalog offers exist, use Gemini to re-order if available
    llm_order = rank_candidates(state['requirements'], ranked)
    if llm_order:
        order = {vendor_id: index for index, vendor_id in enumerate(llm_order['ranked_vendor_ids'])}
        ranked.sort(key=lambda item: (
            order.get(item['offer']['vendor_id'], len(order) + 100),
            -item['score'],
            float(item['estimated_total']) if item.get('estimated_total') else float('inf')
        ))
        for item in ranked:
            reason = llm_order['reason_by_vendor'].get(item['offer']['vendor_id'])
            if reason and reason not in item['reasons']:
                item['reasons'].insert(0, 'Gemini: ' + reason)

    return {
        'shortlist': ranked[:10],
        'ranking_method': 'Gemini + eligibility rules' if llm_order else 'Eligibility rules + price ordering',
        'matched_vendor_count': len(ranked),
    }


def _clean_form_text(value: object, default: str = '') -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {'none', 'null', 'n/a', 'na', '-'}:
        return default
    return text


def format_detailed_rfq(
    req_data: Requirements | dict,
    vendor_name: str = 'Supplier',
    contact_name: str | None = None,
    offer: dict | None = None,
) -> tuple[str, str]:
    """Build a comprehensive, executive RFQ subject and body containing all form details and vendor instructions."""
    req = req_data if isinstance(req_data, Requirements) else Requirements.model_validate(req_data)
    offer = offer or {}

    raw_vendor = _clean_form_text(vendor_name or offer.get('vendor_name'), 'Valued Supplier')
    raw_contact = _clean_form_text(contact_name or offer.get('contact_name'), '')
    if raw_contact and raw_contact.lower() != raw_vendor.lower():
        salutation = f"Dear {raw_contact} ({raw_vendor}),"
    else:
        salutation = f"Dear {raw_vendor} Commercial & Sales Team,"

    line_items = list(req.line_items or [])
    first_line = line_items[0] if line_items else None

    product_title = (
        _clean_form_text(req.product)
        or (first_line and _clean_form_text(first_line.description))
        or _clean_form_text(offer.get('product'))
        or 'Commercial Procurement Requirement'
    )
    purchase_type = _clean_form_text(req.purchase_type) or (
        'Services' if (first_line and _clean_form_text(first_line.line_type).lower() == 'service') else 'Goods & Commercial Supply'
    )
    category = (
        _clean_form_text(req.category)
        or (first_line and _clean_form_text(first_line.item_category))
        or purchase_type
    )
    department = (
        _clean_form_text(req.department)
        or (first_line and _clean_form_text(first_line.department))
        or 'Enterprise Operations'
    )
    project = (
        (first_line and _clean_form_text(first_line.project))
        or 'Core Departmental Initiative'
    )
    quantity = req.quantity or (sum(int(li.quantity or 1) for li in line_items) if line_items else 1)
    currency = _clean_form_text(req.currency, 'INR').upper()
    budget_str = (
        f"{currency} {float(req.budget):,.2f}"
        if req.budget is not None
        else f"Please propose best competitive rate in {currency}"
    )
    payment_terms = _clean_form_text(req.payment_terms, 'Net 30 Days from Invoice & Acceptance')
    delivery_location = (
        _clean_form_text(req.delivery_location)
        or (first_line and _clean_form_text(first_line.location))
        or 'Jaipur, India'
    )
    delivery_deadline = (
        str(req.delivery_deadline)
        if req.delivery_deadline
        else (str(first_line.contract_end) if first_line and first_line.contract_end else 'Immediate / Please propose earliest date')
    )

    c_start = req.contract_start or (first_line.contract_start if first_line else None)
    c_end = req.contract_end or (first_line.contract_end if first_line else None)
    if c_start and c_end:
        contract_window = f"{c_start} to {c_end}"
    elif c_start:
        contract_window = f"Starting {c_start}"
    elif c_end:
        contract_window = f"Through {c_end}"
    else:
        contract_window = f"Target completion by {delivery_deadline}"

    explicit_purpose = _clean_form_text(req.business_purpose)
    if explicit_purpose:
        sole_purpose = (
            f"{explicit_purpose} This requisition is initiated by the {department} department "
            f"(Project: {project}) to fulfill our operational requirement for {product_title} "
            f"at {delivery_location} on or before {delivery_deadline}."
        )
    else:
        sole_purpose = (
            f"The sole purpose of this procurement is to source and deploy {quantity} unit(s) of {product_title} "
            f"({category}) for our {department} department under project '{project}'. "
            f"We require a reliable commercial partner capable of delivering full scope compliance to "
            f"{delivery_location} by {delivery_deadline} within our approved budget parameters."
        )

    line_rows = []
    if line_items:
        for idx, li in enumerate(line_items, start=1):
            desc = _clean_form_text(li.description, product_title)
            l_type = _clean_form_text(li.line_type, 'Item')
            l_cat = _clean_form_text(li.item_category, category)
            l_qty = int(li.quantity or 1)
            l_unit = f"{currency} {float(li.unit_price):,.2f}" if li.unit_price is not None else 'To be quoted'
            l_total = (
                f"{currency} {(float(li.unit_price) * l_qty):,.2f}"
                if li.unit_price is not None
                else 'To be quoted'
            )
            l_dept = _clean_form_text(li.department, department)
            l_proj = _clean_form_text(li.project, project)
            l_loc = _clean_form_text(li.location, delivery_location)
            l_method = _clean_form_text(li.purchasing_method, 'Quote request (RFQ)')
            l_verify = _clean_form_text(li.verification_method, 'Goods receipt / Service acceptance')

            row_lines = [
                f"  Line {idx}: {desc}",
                f"    - Classification & Category : {l_type} | {l_cat}",
                f"    - Quantity & Target Rate    : {l_qty} unit(s) | Est. Unit Rate: {l_unit} | Est. Line Ceiling: {l_total}",
                f"    - Department & Project      : {l_dept} | Project: {l_proj}",
                f"    - Delivery Site & Method    : {l_loc} | Buying Method: {l_method}",
                f"    - Acceptance & Verification : {l_verify}",
            ]
            s_unit = _clean_form_text(li.service_unit)
            s_level = _clean_form_text(li.service_level)
            s_owner = _clean_form_text(li.acceptance_owner)
            if l_type.lower() == 'service' or s_unit or s_level or s_owner:
                row_lines.append(
                    f"    - Service SLA & Sign-Off    : Unit: {s_unit or 'Milestone/Fixed'} | "
                    f"SLA: {s_level or 'Standard enterprise SLA'} | Owner: {s_owner or l_dept}"
                )
            line_rows.append('\n'.join(row_lines))
    else:
        line_rows.append(
            f"  Line 1: {product_title}\n"
            f"    - Classification & Category : {purchase_type} | {category}\n"
            f"    - Quantity & Target Budget  : {quantity} unit(s) | Target Ceiling: {budget_str}\n"
            f"    - Department & Project      : {department} | Project: {project}\n"
            f"    - Delivery Site             : {delivery_location} (Target Date: {delivery_deadline})"
        )

    specs_text = _clean_form_text(
        req.specifications,
        f"Enterprise commercial grade matching '{product_title}' scope; full OEM/service quality compliance required.",
    )
    conditions_text = _clean_form_text(
        req.mandatory_conditions,
        f"All-inclusive landed pricing in {currency}, confirmed delivery schedule to {delivery_location}, "
        "minimum 12-month standard commercial warranty/SLA, and adherence to agreed payment terms.",
    )

    if req.shares_personal_data or req.data_sharing_choice == 'yes':
        d_types = ', '.join(req.data_types) if req.data_types else 'Corporate / Operational Data'
        d_usage = _clean_form_text(req.data_usage, 'Strictly limited to contracted service delivery and support.')
        data_governance_line = (
            f"Data & Security Compliance Required (Yes) — Data Types: {d_types}. "
            f"Authorized Usage Scope: {d_usage} Vendor must confirm confidentiality and data protection compliance."
        )
    else:
        data_governance_line = "No personal or regulated customer data sharing is required for this engagement."

    subject = f"Formal Request for Quotation (RFQ): {product_title} — {department} [{quantity} Unit(s)]"

    body = (
        f"{salutation}\n\n"
        f"AuditAI Enterprise Procurement invites {raw_vendor} to submit a formal commercial quotation for the "
        f"requisition detailed below. Please review our operational objective, intake form specifications, and "
        f"the required quotation submission checklist so we can evaluate your bid promptly.\n\n"
        f"1. MAIN PURPOSE & BUSINESS OBJECTIVE\n"
        f"------------------------------------------------------------------------\n"
        f"{sole_purpose}\n\n"
        f"2. PROCUREMENT REQUISITION SUMMARY (FROM INTAKE FORM)\n"
        f"------------------------------------------------------------------------\n"
        f"  - Primary Requirement / Scope : {product_title}\n"
        f"  - Purchase Classification     : {purchase_type} ({category})\n"
        f"  - Requesting Department       : {department} (Project: {project})\n"
        f"  - Total Quantity Required     : {quantity} unit(s)\n"
        f"  - Approved Budget Ceiling     : {budget_str} (Inclusive of taxes & freight)\n"
        f"  - Preferred Payment Terms     : {payment_terms}\n"
        f"  - Contract / Engagement Window: {contract_window}\n"
        f"  - Required Delivery Date      : {delivery_deadline}\n"
        f"  - Designated Delivery Location: {delivery_location}\n\n"
        f"3. DETAILED LINE-ITEM SCHEDULE\n"
        f"------------------------------------------------------------------------\n"
        + '\n\n'.join(line_rows)
        + "\n\n"
        f"4. TECHNICAL SPECIFICATIONS, MANDATORY CONDITIONS & GOVERNANCE\n"
        f"------------------------------------------------------------------------\n"
        f"  - Technical Specifications    : {specs_text}\n"
        f"  - Mandatory Conditions        : {conditions_text}\n"
        f"  - Data & Privacy Governance   : {data_governance_line}\n\n"
        f"5. ACTION REQUIRED: WHAT YOU MUST INCLUDE IN YOUR QUOTATION REPLY\n"
        f"------------------------------------------------------------------------\n"
        f"To ensure your quotation is automatically validated by our procurement engine, please reply directly "
        f"to this email with the following 5 mandatory commercial details:\n"
        f"  1. All-Inclusive Pricing ({currency}): State your Unit Price and Total Landed Price in {currency}, "
        f"explicitly breaking down applicable GST/taxes and shipping/delivery charges to {delivery_location}.\n"
        f"  2. Confirmed Delivery Lead Time: State your exact delivery or implementation timeline in calendar days "
        f"(confirming whether you can meet the target date of {delivery_deadline}).\n"
        f"  3. Warranty & Support SLA: State the warranty duration (in months) and post-delivery support/SLA terms.\n"
        f"  4. Payment & Commercial Terms: Confirm acceptance of '{payment_terms}' and state quote validity (minimum 30 days).\n"
        f"  5. Scope & Compliance Confirmation: Confirm full compliance with the line-item schedule and specifications above, "
        f"or clearly state any commercial exceptions.\n\n"
        f"HOW TO SUBMIT:\n"
        f"Simply reply directly to this email thread (keeping the subject line unchanged) with your quotation figures "
        f"in the email body or attached PDF quotation. Please note that this correspondence is a formal Request for "
        f"Quotation (RFQ) for commercial evaluation and does not constitute a binding Purchase Order commitment.\n\n"
        f"Sincerely,\n"
        f"Enterprise Procurement & Autonomous Sourcing Desk\n"
        f"Department: {department} | Location: {delivery_location}"
    )

    return subject, body


def _prepare_rfq(state: SourcingState) -> dict:
    req = Requirements.model_validate(state['requirements'])
    drafts = []
    for rank, item in enumerate(state.get('shortlist', []), start=1):
        offer = item['offer']
        is_external = bool(offer.get('is_external'))
        rfq_subject, rfq_body = format_detailed_rfq(
            req,
            vendor_name=offer.get('vendor_name') or 'Supplier',
            contact_name=offer.get('contact_name'),
            offer=offer,
        )

        drafts.append({
            **item,
            'rank': rank,
            'status': 'public_lead' if is_external else item.get('status', 'draft_ready'),
            'rfq_subject': rfq_subject,
            'rfq_body': rfq_body,
        })
    return {'drafts': drafts}


def build_sourcing_graph():
    graph = StateGraph(SourcingState)
    graph.add_node('search_company_catalog', _catalog_search)
    graph.add_node('public_web_discovery', _public_discovery)
    graph.add_node('rank_eligible_offers', _rank_offers)
    graph.add_node('prepare_rfq_drafts', _prepare_rfq)

    graph.add_edge(START, 'search_company_catalog')
    graph.add_edge('search_company_catalog', 'public_web_discovery')
    graph.add_edge('public_web_discovery', 'rank_eligible_offers')
    graph.add_edge('rank_eligible_offers', 'prepare_rfq_drafts')
    graph.add_edge('prepare_rfq_drafts', END)
    return graph.compile()


def run_sourcing_agent(requirements: dict) -> dict:
    return build_sourcing_graph().invoke({'requirements': requirements})
