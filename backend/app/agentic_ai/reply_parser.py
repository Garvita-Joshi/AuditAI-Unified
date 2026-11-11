"""Commercial quotation email reply parser.

Uses Gemini 2.5 Flash for accurate natural language extraction of commercial terms
(prices, delivery lead times, payment terms, and warranty coverage) from incoming vendor
quotation replies, with a deterministic regex fallback.
"""
import os
import re
import json


def _clean_number(val) -> float | None:
    if val is None:
        return None
    try:
        s = str(val).replace(',', '').replace(' ', '').strip()
        f = float(s)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_with_gemini(reply_text: str, quantity: int = 1, currency: str = 'INR') -> dict | None:
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = (
            f"You are a commercial procurement auditor. Extract the quoted terms from this vendor email reply.\n"
            f"Target requested quantity is {quantity} and currency is {currency}.\n\n"
            f"Vendor Email Reply:\n\"\"\"\n{reply_text[:4000]}\n\"\"\"\n"
        )

        schema = {
            'type': 'OBJECT',
            'properties': {
                'total_price': {'type': 'NUMBER'},
                'unit_price': {'type': 'NUMBER'},
                'currency': {'type': 'STRING'},
                'lead_time_days': {'type': 'INTEGER'},
                'payment_terms': {'type': 'STRING'},
                'warranty': {'type': 'STRING'},
                'summary': {'type': 'STRING'},
            },
            'required': ['total_price', 'currency', 'lead_time_days', 'payment_terms', 'warranty', 'summary'],
        }

        resp = client.models.generate_content(
            model=os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'),
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'response_json_schema': schema,
                'temperature': 0.1,
            },
        )

        if not resp.text:
            return None

        data = json.loads(resp.text)
        total_p = _clean_number(data.get('total_price'))
        unit_p = _clean_number(data.get('unit_price'))

        if total_p and not unit_p and quantity > 0:
            unit_p = round(total_p / quantity, 2)
        elif unit_p and not total_p and quantity > 0:
            total_p = round(unit_p * quantity, 2)

        lead_days = data.get('lead_time_days')
        if lead_days is not None:
            try:
                lead_days = int(lead_days)
            except (ValueError, TypeError):
                lead_days = None

        return {
            'total_price': total_p,
            'unit_price': unit_p,
            'currency': data.get('currency') or currency,
            'lead_time_days': lead_days,
            'payment_terms': data.get('payment_terms') or 'Net 30',
            'warranty': data.get('warranty') or 'Standard warranty',
            'summary': data.get('summary') or 'Vendor quotation received.',
        }
    except Exception:
        return None


def _parse_with_regex(reply_text: str, quantity: int = 1, currency: str = 'INR') -> dict:
    text = reply_text.replace('\r', '\n')

    # 1. Total Price search
    total_price = None
    # Pattern matching lines like: *Total Price...:* INR 109,150 or Total: INR 1,71,100
    tot_match = re.search(
        r'(?:total\s+price|grand\s+total|all[\s-]inclusive)[^\n\d]*?(?:INR|Rs\.?|₹|\$)?\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)',
        text, re.IGNORECASE
    )
    if tot_match:
        total_price = _clean_number(tot_match.group(1))

    # 2. Unit Price search
    unit_price = None
    unit_match = re.search(
        r'(?:unit\s+price|per\s+unit|each|rate\s+per\s+item)[^\n\d]*?(?:INR|Rs\.?|₹|\$)?\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)',
        text, re.IGNORECASE
    )
    if unit_match:
        unit_price = _clean_number(unit_match.group(1))

    # Derive missing price
    if total_price and not unit_price and quantity > 0:
        unit_price = round(total_price / quantity, 2)
    elif unit_price and not total_price and quantity > 0:
        total_price = round(unit_price * quantity, 2)

    # Fallback to largest figure in text if still none
    if not total_price:
        candidates = []
        for m in re.finditer(r'(?:INR|Rs\.?|₹|\$)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{2})?|[0-9]{4,}(?:\.[0-9]{2})?)', text, re.IGNORECASE):
            val = _clean_number(m.group(1))
            if val and val > 100:  # ignore tiny numbers like taxes or list numbers
                candidates.append(val)
        if candidates:
            total_price = max(candidates)
            if quantity > 0:
                unit_price = round(total_price / quantity, 2)

    # 3. Delivery Lead time in days
    lead_days = None
    # Match: *Delivery Lead Time:* 5 business days or delivery in 4 days
    lead_match = re.search(
        r'(?:lead\s*time|delivery(?:\s*lead\s*time)?|ships?\s*in|delivered?\s*in)[^\n\d]*?(\d+)\s*(?:business\s*days|working\s*days|days|weeks)',
        text, re.IGNORECASE
    )
    if lead_match:
        try:
            lead_days = int(lead_match.group(1))
            if 'week' in lead_match.group(0).lower():
                lead_days *= 7
        except ValueError:
            pass

    if lead_days is None:
        lead_match2 = re.search(r'(\d+)\s*(?:business\s*days|working\s*days)', text, re.IGNORECASE)
        if lead_match2:
            try:
                lead_days = int(lead_match2.group(1))
            except ValueError:
                pass

    # 4. Payment terms
    terms_match = re.search(r'(Net\s*\d+|PIA|Advance|Payment\s+in\s+advance|Immediate|50%\s*advance)', text, re.IGNORECASE)
    terms = terms_match.group(1) if terms_match else 'Net 30'

    # 5. Warranty
    warranty_match = re.search(
        r'(\d+[- ]*(?:year|yr|month|mo)[^\n\.,;]*?(?:warranty|support|onsite|coverage)[^\n\.,;]*)',
        text, re.IGNORECASE
    )
    warranty = warranty_match.group(1).strip() if warranty_match else 'Standard warranty included'

    summary_parts = []
    if total_price:
        summary_parts.append(f"Quoted {currency} {total_price:,.2f}")
        if unit_price:
            summary_parts.append(f"({currency} {unit_price:,.2f}/unit)")
    if lead_days:
        summary_parts.append(f"in {lead_days} days")
    if terms:
        summary_parts.append(f"with {terms}")
    if warranty:
        summary_parts.append(f"({warranty})")

    summary = ' '.join(summary_parts) if summary_parts else 'Vendor response received.'

    return {
        'total_price': total_price,
        'unit_price': unit_price,
        'currency': currency,
        'lead_time_days': lead_days,
        'payment_terms': terms,
        'warranty': warranty,
        'summary': summary,
    }


def validate_quotation(parsed: dict, reply_text: str = '') -> dict:
    """Stage 4 Validation Engine:
    Detects missing, inconsistent, and ambiguous commercial values.
    Returns completeness validation and signals whether clarification is required.
    """
    text = reply_text or ''
    missing_fields = []
    ambiguity_notes = []

    # Check if supplier explicitly declined or is unable to quote
    decline_patterns = [
        r'unable to supply', r'cannot supply', r'not available',
        r'cannot confirm pricing', r'unavailable at this time',
        r'regret to inform', r'agreement is under renewal'
    ]
    is_declined = any(re.search(pat, text, re.IGNORECASE) for pat in decline_patterns)

    if is_declined and not parsed.get('total_price'):
        return {
            **parsed,
            'is_declined': True,
            'is_valid': False,
            'needs_clarification': False,
            'validation_status': 'declined',
            'missing_fields': ['Commercial Pricing'],
            'ambiguity_notes': ['Vendor explicitly stated they are unable to quote or supply at this time.'],
        }

    # Evaluate missing critical commercial parameters
    if parsed.get('total_price') is None and parsed.get('unit_price') is None:
        missing_fields.append('Commercial Pricing (Unit or Total Price)')
    if parsed.get('lead_time_days') is None:
        if not re.search(r'\b(?:ready stock|immediate|ex[\s-]stock)\b', text, re.IGNORECASE):
            missing_fields.append('Delivery Lead Time (Days)')
    if not parsed.get('warranty') or parsed.get('warranty') == 'Standard warranty included':
        if not re.search(r'\b(?:warranty|guarantee|onsite|support package)\b', text, re.IGNORECASE):
            missing_fields.append('Written Warranty Period & Coverage')

    # Detect ambiguity in tax, shipping, and scope
    if re.search(r'(?:shipping|freight|transport)[^\n.]*?(?:calculated separately|extra|at actuals|tbd|to be determined)', text, re.IGNORECASE):
        ambiguity_notes.append('Freight / Shipping costs quoted separately or unconfirmed')
    if re.search(r'(?:tax|taxes|gst|vat)[^\n.]*?(?:calculated separately|extra|applicable extra|at actuals)', text, re.IGNORECASE):
        ambiguity_notes.append('Applicable GST / Taxes not factored into all-inclusive price')

    is_valid = len(missing_fields) == 0 and parsed.get('total_price') is not None
    needs_clarification = not is_declined and (len(missing_fields) > 0 or len(ambiguity_notes) > 0)

    return {
        **parsed,
        'is_declined': is_declined,
        'is_valid': is_valid,
        'needs_clarification': needs_clarification,
        'validation_status': 'valid' if is_valid else ('declined' if is_declined else 'incomplete'),
        'missing_fields': missing_fields,
        'ambiguity_notes': ambiguity_notes,
    }


def compose_clarification_request(vendor_name: str, product: str, missing_fields: list[str], ambiguity_notes: list[str], ref_token: str) -> str:
    """Generate a high-grade, professional Request for Commercial Clarification."""
    missing_items = "\n".join([f"  • {m}" for m in missing_fields]) if missing_fields else "  • All-inclusive pricing breakdown"
    ambiguity_items = "\n".join([f"  • {a}" for a in ambiguity_notes]) if ambiguity_notes else ""

    body = (
        f"Dear {vendor_name} Commercial & Sales Team,\n\n"
        f"Thank you for your response regarding our Request for Quotation for {product} [Ref: {ref_token}].\n\n"
        f"Our procurement committee has reviewed your proposal submission. To complete our formal commercial evaluation and qualify your bid alongside shortlisted competitors, we kindly request clarification on the following pending points:\n\n"
    )
    if missing_fields:
        body += f"Missing Commercial Requirements:\n{missing_items}\n\n"
    if ambiguity_notes:
        body += f"Clarification Items:\n{ambiguity_items}\n(Please confirm DDP all-inclusive terms including delivery freight and applicable GST/taxes).\n\n"

    body += (
        f"Please reply directly to this email with the requested details so we can finalize our supplier ranking and proceed to contract award.\n\n"
        f"We appreciate your prompt assistance and cooperation.\n\n"
        f"Sincerely,\n"
        f"Procurement Operations & Commercial Quality Audit\n"
        f"AuditAI Autonomous Procurement System"
    )
    return body


def parse_commercial_reply(reply_text: str, quantity: int = 1, currency: str = 'INR') -> dict:
    """Parse vendor quotation reply text with Gemini 2.5 Flash + regex fallback,
    and run Stage 4 Validation Engine to detect missing/ambiguous terms."""
    if not reply_text:
        return {
            'total_price': None,
            'unit_price': None,
            'currency': currency,
            'lead_time_days': None,
            'payment_terms': None,
            'warranty': None,
            'summary': 'No reply text provided.',
            'is_valid': False,
            'is_declined': False,
            'needs_clarification': True,
            'validation_status': 'incomplete',
            'missing_fields': ['Commercial Quotation Text'],
            'ambiguity_notes': [],
        }

    gemini_result = _parse_with_gemini(reply_text, quantity=quantity, currency=currency)
    raw_parsed = gemini_result if (gemini_result and gemini_result.get('total_price')) else _parse_with_regex(reply_text, quantity=quantity, currency=currency)
    return validate_quotation(raw_parsed, reply_text)


def analyze_email_negotiation_intelligence(
    reply_text: str,
    parsed_quote: dict,
    budget: float = 0.0,
    currency: str = 'INR',
    benchmark_price: float | None = None,
    benchmark_vendor: str | None = None
) -> dict:
    """Intelligently analyze vendor email replies to evaluate:
    1. What is incomplete (missing parameters, terms, SLAs)
    2. What is wrong / non-compliant (advance payment, over budget, extended lead time)
    3. Specific grounds for negotiation (policy basis, benchmark basis, risk basis)
    """
    text = (reply_text or '').lower()
    quoted_price = parsed_quote.get('total_price') or parsed_quote.get('unit_price') or 0.0
    lead_time = parsed_quote.get('lead_time_days')
    payment_terms = str(parsed_quote.get('payment_terms') or '').lower()
    warranty = str(parsed_quote.get('warranty') or '').lower()

    # 1. WHAT IS INCOMPLETE
    incomplete_items = []
    if not quoted_price:
        incomplete_items.append({
            'term': 'Commercial Pricing Breakdown',
            'detail': 'Itemized pricing / total commercial quote not clearly stated',
            'severity': 'critical'
        })
    if lead_time is None and not any(k in text for k in ['immediate', 'stock', 'days', 'weeks']):
        incomplete_items.append({
            'term': 'Delivery Lead Time',
            'detail': 'Specific delivery schedule in business days not defined',
            'severity': 'high'
        })
    if not any(k in text for k in ['net 30', 'net 45', 'net 60', 'credit', 'payment', 'terms', 'milestone']):
        incomplete_items.append({
            'term': 'Payment Schedule & Credit Terms',
            'detail': 'Explicit payment credit terms (e.g. Net 30/45) omitted',
            'severity': 'medium'
        })
    if not any(k in text for k in ['warranty', 'guarantee', 'support', 'sla', 'replacement']):
        incomplete_items.append({
            'term': 'Written Warranty & Support SLA',
            'detail': 'Warranty duration and on-site support coverage not specified',
            'severity': 'medium'
        })
    if any(k in text for k in ['tax extra', 'taxes extra', 'gst extra', 'plus gst', 'vat extra']):
        incomplete_items.append({
            'term': 'All-Inclusive Tax (GST) Terms',
            'detail': 'Taxes quoted separately instead of all-inclusive DDP price',
            'severity': 'medium'
        })
    if any(k in text for k in ['freight extra', 'shipping extra', 'at actuals', 'ex-works']):
        incomplete_items.append({
            'term': 'Freight & Delivery Logistics (DDP)',
            'detail': 'Logistics quoted at actuals instead of Door-to-Door Delivery (DDP)',
            'severity': 'low'
        })

    # 2. WHAT IS WRONG / NON-COMPLIANT
    wrong_items = []
    # Payment term compliance check
    if any(k in payment_terms or k in text for k in ['100% advance', 'advance payment', 'full advance', 'upfront', 'immediate payment', 'pia']):
        wrong_items.append({
            'violation': 'Non-Compliant Advance Payment Demand',
            'policy': 'Corporate Working Capital Policy mandates credit terms (Net 30/45) or milestone-based disbursements; 100% upfront is strictly prohibited.',
            'severity': 'critical'
        })
    elif any(k in payment_terms or k in text for k in ['50% advance', 'advance 50%', 'deposit required']):
        wrong_items.append({
            'violation': 'Excessive Advance Payment Requirement',
            'policy': 'Advance payments exceeding 20% require executive board waiver. Policy standard is milestone 30-30-40 or Net 45.',
            'severity': 'high'
        })

    # Budget compliance check
    if budget > 0 and quoted_price > budget:
        overrun = quoted_price - budget
        overrun_pct = round((overrun / budget) * 100, 1)
        wrong_items.append({
            'violation': f'Budget Ceiling Overrun (+{overrun_pct}%)',
            'policy': f"Quoted price ({currency} {quoted_price:,.2f}) exceeds approved department allocation ({currency} {budget:,.2f}) by {currency} {overrun:,.2f}.",
            'severity': 'critical' if overrun_pct > 15 else 'medium'
        })

    # Lead time compliance check
    if lead_time and lead_time > 21:
        wrong_items.append({
            'violation': f'Extended Delivery Lead Time ({lead_time} days)',
            'policy': 'Standard project delivery SLA requires fulfillment within 14-21 days.',
            'severity': 'medium'
        })

    # Short warranty check
    if any(k in warranty or k in text for k in ['30 days', 'no warranty', 'as-is', 'as is', '90 days']):
        wrong_items.append({
            'violation': 'Sub-standard Warranty Coverage',
            'policy': 'Company procurement quality standard mandates minimum 12-24 months commercial warranty.',
            'severity': 'high'
        })

    # 3. SPECIFIC GROUNDS FOR NEGOTIATION
    grounds = []
    if wrong_items:
        for w in wrong_items:
            grounds.append({
                'ground_type': 'Compliance & Policy Enforcement',
                'title': w['violation'],
                'rationale': w['policy'],
                'counter_action': 'Enforce standard company policy terms in counteroffer.'
            })

    if benchmark_price and quoted_price > benchmark_price:
        diff_bench = quoted_price - benchmark_price
        grounds.append({
            'ground_type': 'Competitive Market Benchmark',
            'title': f'Market Competitive Bid Gap ({currency} {diff_bench:,.2f})',
            'rationale': f'Competing supplier {benchmark_vendor or ""} submitted a verified quotation at {currency} {benchmark_price:,.2f} with equivalent scope.',
            'counter_action': f'Counter at {currency} {benchmark_price * 0.98:,.2f} to match market leading rate.'
        })
    elif budget > 0 and quoted_price <= budget:
        grounds.append({
            'ground_type': 'Volume & Preferred Partner Discount',
            'title': 'Preferred Award Volume Concession',
            'rationale': f'Proposal qualifies for top single-source preference; standard volume adjustment of 5-8% requested to finalize immediate contract.',
            'counter_action': f'Counter at {currency} {quoted_price * 0.94:,.2f} with Net 45 days and priority delivery.'
        })

    if incomplete_items:
        grounds.append({
            'ground_type': 'Scope & SLA Completeness',
            'title': f"{len(incomplete_items)} Missing Commercial Parameter(s)",
            'rationale': 'To mitigate downstream delivery risk, counteroffer contract must mandate written SLA and DDP freight terms.',
            'counter_action': 'Incorporate mandatory SLA, all-inclusive GST, and penalty clauses.'
        })

    return {
        'what_is_incomplete': incomplete_items,
        'what_is_wrong': wrong_items,
        'negotiation_grounds': grounds,
        'summary': f"Identified {len(incomplete_items)} incomplete parameter(s), {len(wrong_items)} non-compliant term(s), and established {len(grounds)} concrete negotiation ground(s)."
    }
