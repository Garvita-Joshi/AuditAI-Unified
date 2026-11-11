import re
"""Gemini LLM helpers: vendor ranking, RFQ email composition, and response analysis."""
import json
import os
from backend.app.config import GEMINI_MODEL

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gemini_client():
    from google import genai
    from google.genai import types  # noqa: F401 (imported for callers)
    return genai.Client(api_key=os.environ['GEMINI_API_KEY'])


def rank_candidates(requirements: dict, candidates: list[dict]) -> dict | None:
    if not candidates or not os.getenv('GEMINI_API_KEY'):
        return None
    try:
        from google import genai
        from google.genai import types
        schema = {'type':'OBJECT', 'properties':{
            'ranked_vendor_ids':{'type':'ARRAY','items':{'type':'STRING'}},
            'reason_by_vendor':{'type':'OBJECT','additionalProperties':{'type':'STRING'}},
        },'required':['ranked_vendor_ids','reason_by_vendor']}
        prompt = {
            'requirements': {key:requirements.get(key) for key in ('product','quantity','budget','currency','delivery_deadline','delivery_location','specifications','mandatory_conditions','preferred_vendors')},
            'eligible_candidates': [{
                'vendor_id':item['offer']['vendor_id'], 'vendor_name':item['offer']['vendor_name'],
                'product':item['offer']['product'], 'description':item['offer'].get('description'),
                'currency':item['offer']['currency'], 'estimated_total':item.get('estimated_total'),
                'lead_time_days':item['offer'].get('lead_time_days'), 'warranty_months':item['offer'].get('warranty_months'),
                'vendor_rating_out_of_5':item['offer'].get('rating'), 'average_delivery_days':item['offer'].get('avg_delivery_days'),
                'payment_terms':item['offer'].get('payment_terms'), 'preference_match':item.get('preference_match',False),
            } for item in candidates],
        }
        instruction = (
            'Rank the supplied eligible company catalog vendors for this request. Return at most ten vendor IDs, '
            'best fit first. Consider requirement fit, total cost, stated lead time, average delivery days, vendor rating, warranty, payment terms and explicit preference. '
            'Use only facts in the candidate data. Do not invent prices, availability, quality history, or guarantees. '
            'Do not change eligibility or budget; only order the already eligible records and provide a concise factual reason per vendor.'
        )
        with genai.Client(api_key=os.environ['GEMINI_API_KEY'], http_options=types.HttpOptions(timeout=30000)) as client:
            response = client.models.generate_content(model=os.getenv('GEMINI_MODEL', GEMINI_MODEL),
                contents=json.dumps(prompt), config={'system_instruction':instruction,
                    'response_mime_type':'application/json','response_json_schema':schema,'temperature':0})
        if not response.text:
            return None
        parsed = json.loads(response.text)
        allowed = {item['offer']['vendor_id'] for item in candidates}
        ids = list(dict.fromkeys(value for value in parsed.get('ranked_vendor_ids', []) if value in allowed))[:10]
        reasons = parsed.get('reason_by_vendor') or {}
        return {'ranked_vendor_ids':ids,'reason_by_vendor':{key:value[:500] for key,value in reasons.items() if key in allowed and isinstance(value,str)}}
    except Exception:
        # A provider outage must not bypass deterministic matching or prevent review.
        return None


# ---------------------------------------------------------------------------
# RFQ email composer
# ---------------------------------------------------------------------------

def compose_rfq_email(requirements: dict, vendor: dict) -> dict:
    """Use Gemini or structured template to write a comprehensive, professional RFQ email for a specific vendor.

    Falls back to format_detailed_rfq when the API is unavailable.
    Returns {'subject': str, 'body': str, 'composed_by': str}
    """
    from backend.app.agentic_ai.graph import format_detailed_rfq

    vendor_name = vendor.get('vendor_name') or vendor.get('name') or 'Supplier'
    contact_name = vendor.get('contact_name') or (vendor.get('offer') or {}).get('contact_name')
    fallback_subject, fallback_body = format_detailed_rfq(
        requirements,
        vendor_name=vendor_name,
        contact_name=contact_name,
        offer=vendor.get('offer') or vendor,
    )
    return {'subject': fallback_subject, 'body': fallback_body, 'composed_by': 'structured_intake_rfq'}


# ---------------------------------------------------------------------------
# Vendor response analyser & final recommendation
# ---------------------------------------------------------------------------

def analyze_vendor_responses(requirements: dict, vendors_with_replies: list[dict]) -> dict:
    """Analyse all vendor replies and return a ranked recommendation with scores.

    Each entry in vendors_with_replies should have:
      vendor_name, vendor_id, reply_text, rfq_body (original RFQ), offer (catalog data)

    Returns:
      {
        'winner_vendor_id': str,
        'winner_vendor_name': str,
        'recommendation_summary': str,
        'ranked': [{'vendor_id', 'vendor_name', 'score', 'reasoning', 'strengths', 'concerns'}],
        'analysis_by': 'gemini' | 'rules',
      }
    """
    if not vendors_with_replies:
        return {
            'winner_vendor_id': None,
            'winner_vendor_name': None,
            'recommendation_summary': 'No vendor responses to analyse.',
            'ranked': [],
            'analysis_by': 'rules',
        }

    product  = requirements.get('product') or 'the requirement'
    currency = requirements.get('currency') or 'INR'
    budget   = requirements.get('budget')
    deadline = requirements.get('delivery_deadline') or ''
    specs    = requirements.get('specifications') or ''
    conditions = requirements.get('mandatory_conditions') or ''

    # Multi-criteria weighted ranking algorithm: Price (50%), Delivery Speed (20%), Warranty (15%), Terms & Reliability (15%)
    def _rules_rank():
        scored = []
        valid_prices = []
        for v in vendors_with_replies:
            offer = v.get('offer') or {}
            p = offer.get('total_price') or offer.get('unit_price')
            if p is not None:
                try:
                    valid_prices.append(float(p))
                except (ValueError, TypeError):
                    pass
        min_p = min(valid_prices) if valid_prices else (budget or 100000.0)

        for v in vendors_with_replies:
            offer = v.get('offer') or {}
            p = offer.get('total_price') or offer.get('unit_price')
            try:
                p_val = float(p) if p is not None else (budget or 100000.0)
            except (ValueError, TypeError):
                p_val = budget or 100000.0

            # 1. Price score (50% weight): 100 for lowest, decreasing as price increases
            price_score = min(100.0, max(20.0, (min_p / p_val) * 100.0)) if p_val > 0 else 50.0

            # 2. Lead time score (20% weight)
            lead = offer.get('lead_time_days')
            try:
                lead_days = int(lead) if lead is not None else 14
            except (ValueError, TypeError):
                lead_days = 14
            speed_score = max(30.0, min(100.0, 100.0 - (lead_days - 3) * 3.5))

            # 3. Warranty score (15% weight)
            w_str = str(offer.get('warranty', '')).lower()
            if '3 year' in w_str or '36' in w_str:
                w_score = 100.0
            elif '2 year' in w_str or '24' in w_str:
                w_score = 90.0
            elif '1 year' in w_str or '12' in w_str:
                w_score = 80.0
            else:
                w_score = 60.0

            # 4. Reliability & Terms score (15% weight)
            terms = str(offer.get('payment_terms', '')).lower()
            if 'net 60' in terms or 'net 45' in terms:
                t_score = 100.0
            elif 'net 30' in terms:
                t_score = 85.0
            elif 'advance' in terms:
                t_score = 45.0
            else:
                t_score = 75.0

            rating = float(offer.get('rating') or 4.0)
            reliability_score = (t_score * 0.7) + (rating / 5.0 * 100.0 * 0.3)

            composite = round((price_score * 0.50) + (speed_score * 0.20) + (w_score * 0.15) + (reliability_score * 0.15), 1)

            strengths = []
            concerns = []
            if price_score >= 85:
                strengths.append(f"Highly competitive commercial pricing ({currency} {p_val:,.2f})")
            elif price_score < 60:
                concerns.append(f"Quoted price is {currency} {p_val:,.2f} (above market benchmark)")

            if lead_days <= 7:
                strengths.append(f"Fast delivery turnaround ({lead_days} days)")
            elif lead_days > 20:
                concerns.append(f"Extended lead time ({lead_days} business days)")

            if w_score >= 85:
                strengths.append("Comprehensive multi-year warranty protection")
            if t_score >= 85:
                strengths.append(f"Favorable enterprise commercial terms ({offer.get('payment_terms', 'Net 30')})")
            elif t_score < 60:
                concerns.append("Demands upfront / advance payment")

            scored.append({
                'vendor_id': v['vendor_id'],
                'vendor_name': v['vendor_name'],
                'score': composite,
                'score_breakdown': {
                    'price_score': round(price_score, 1),
                    'speed_score': round(speed_score, 1),
                    'warranty_score': round(w_score, 1),
                    'reliability_score': round(reliability_score, 1),
                },
                'reasoning': f"Multi-criteria weighted fit: {composite}/100 based on price (50%), lead time (20%), warranty (15%), and terms (15%).",
                'strengths': strengths or ['Verified shortlisted supplier'],
                'concerns': concerns or ['Subject to formal final PO execution'],
            })

        scored.sort(key=lambda x: -x['score'])
        winner = scored[0] if scored else {}
        return {
            'winner_vendor_id': winner.get('vendor_id'),
            'winner_vendor_name': winner.get('vendor_name'),
            'recommendation_summary': f"Multi-criteria recommendation: {winner.get('vendor_name')} ranked #1 with an overall fit score of {winner.get('score')}/100, delivering optimal price-to-SLA balance.",
            'ranked': scored,
            'analysis_by': 'multi_criteria_engine',
        }

    return _rules_rank()
    if not os.getenv('GEMINI_API_KEY'):
        return _rules_rank()

    try:
        from google import genai
        from google.genai import types

        vendor_schema = {
            'type': 'OBJECT',
            'properties': {
                'vendor_id':   {'type': 'STRING'},
                'vendor_name': {'type': 'STRING'},
                'score':       {'type': 'NUMBER', 'description': '0-100 overall fit score'},
                'reasoning':   {'type': 'STRING'},
                'strengths':   {'type': 'ARRAY', 'items': {'type': 'STRING'}},
                'concerns':    {'type': 'ARRAY', 'items': {'type': 'STRING'}},
            },
            'required': ['vendor_id', 'vendor_name', 'score', 'reasoning', 'strengths', 'concerns'],
        }

        schema = {
            'type': 'OBJECT',
            'properties': {
                'winner_vendor_id':       {'type': 'STRING'},
                'winner_vendor_name':     {'type': 'STRING'},
                'recommendation_summary': {'type': 'STRING'},
                'ranked':                 {'type': 'ARRAY', 'items': vendor_schema},
            },
            'required': ['winner_vendor_id', 'winner_vendor_name', 'recommendation_summary', 'ranked'],
        }

        candidates_data = []
        for v in vendors_with_replies:
            reply_text = (v.get('reply_text') or '').strip()
            candidates_data.append({
                'vendor_id':   v['vendor_id'],
                'vendor_name': v['vendor_name'],
                'original_rfq': (v.get('rfq_body') or '')[:800],
                'vendor_reply': reply_text if reply_text else '[Formal quotation pending; evaluated on catalog baseline]',
                'has_formal_quote': bool(reply_text),
                'catalog_price': v.get('offer', {}).get('unit_price'),
                'catalog_lead_time_days': v.get('offer', {}).get('lead_time_days'),
                'catalog_rating': v.get('offer', {}).get('rating'),
            })

        prompt_data = {
            'procurement_requirement': {
                'product': product,
                'currency': currency,
                'budget': budget,
                'delivery_deadline': deadline,
                'specifications': specs,
                'mandatory_conditions': conditions,
            },
            'vendor_responses': candidates_data,
        }

        instruction = (
            "You are a senior procurement analyst reviewing vendor RFQ responses and supplier offers. "
            "Evaluate each vendor against the procurement requirements (budget, delivery location, deadline, specifications). "
            "For vendors with a vendor_reply (submitted quote), evaluate their quoted price, lead time, taxes, warranty, and terms. "
            "For vendors whose formal quotation is pending, evaluate them based on their approved catalog offer baseline. "
            "Score each vendor 0-100 considering: price competitiveness, compliance with specs, "
            "delivery lead time vs deadline, warranty, payment terms, and reliability. "
            "Identify the single best vendor (winner_vendor_id and winner_vendor_name). "
            "Write a clear recommendation_summary (2-4 sentences) explaining WHY this vendor is the best choice. "
            "List strengths and concerns for each vendor. Be objective, constructive, and factual."
        )

        with genai.Client(api_key=os.environ['GEMINI_API_KEY'],
                          http_options=types.HttpOptions(timeout=45000)) as client:
            response = client.models.generate_content(
                model=os.getenv('GEMINI_MODEL', GEMINI_MODEL),
                contents=json.dumps(prompt_data),
                config={
                    'system_instruction': instruction,
                    'response_mime_type': 'application/json',
                    'response_json_schema': schema,
                    'temperature': 0,
                },
            )

        if not response.text:
            return _rules_rank()

        parsed = json.loads(response.text)
        allowed_ids = {v['vendor_id'] for v in vendors_with_replies}

        # Validate winner id is among known vendors
        winner_id = parsed.get('winner_vendor_id')
        if winner_id not in allowed_ids:
            winner_id = (parsed.get('ranked') or [{}])[0].get('vendor_id') if parsed.get('ranked') else None

        return {
            'winner_vendor_id':       winner_id,
            'winner_vendor_name':     parsed.get('winner_vendor_name') or '',
            'recommendation_summary': parsed.get('recommendation_summary') or '',
            'ranked':                 parsed.get('ranked') or [],
            'analysis_by':            'gemini',
        }

    except Exception:
        return _rules_rank()



# ---------------------------------------------------------------------------
# Vendor quotation simulation engine
# ---------------------------------------------------------------------------

def generate_vendor_quote(requirements: dict, vendor_name: str, offer: dict | None = None, rfq_body: str = '') -> str:
    """Generate a realistic formal quotation from a supplier in response to an RFQ."""
    offer = offer or {}
    product = requirements.get('product') or offer.get('product') or 'Item'
    qty = requirements.get('quantity') or 1
    curr = requirements.get('currency') or offer.get('currency') or 'INR'
    unit_price = offer.get('unit_price')
    lead_time = offer.get('lead_time_days') or 5
    location = requirements.get('delivery_location') or 'Jaipur, India'
    
    # Calculate sensible price if none in catalog
    if unit_price is None:
        budget = requirements.get('budget')
        if budget:
            unit_price = round(float(budget) / max(qty, 1) * 0.92, 2)
        else:
            unit_price = 15000.0

    total_price = round(float(unit_price) * qty, 2)
    tax_rate = 18
    tax_amt = round(total_price * (tax_rate / 100), 2)
    grand_total = round(total_price + tax_amt, 2)

    fallback_quote = (
        f"COMMERCIAL QUOTATION\n"
        f"Quotation Ref: QTE-2026-{re.sub(r'[^A-Z0-9]', '', vendor_name.upper())[:6]}-01\n"
        f"From: {vendor_name} Commercial Sales Team\n"
        f"To: AuditAI Procurement\n\n"
        f"Dear Procurement Team,\n\n"
        f"Thank you for your Request for Quotation. We are pleased to provide our formal commercial offer for {product}:\n\n"
        f"  • Item Description : {product} (Standard Commercial Grade)\n"
        f"  • Quantity         : {qty} unit(s)\n"
        f"  • Unit Price       : {curr} {float(unit_price):,.2f}\n"
        f"  • Subtotal         : {curr} {total_price:,.2f}\n"
        f"  • Taxes (GST {tax_rate}%)   : {curr} {tax_amt:,.2f}\n"
        f"  • Grand Total      : {curr} {grand_total:,.2f} (Inclusive of all duties and taxes)\n"
        f"  • Delivery Lead    : {lead_time} business days to {location}\n"
        f"  • Shipping Terms   : DDP (Delivered Duty Paid), all transit insurance covered\n"
        f"  • Payment Terms    : Net 30 days upon delivery and inspection\n"
        f"  • Warranty         : 12 months comprehensive OEM replacement warranty\n"
        f"  • Validity         : 30 calendar days\n\n"
        f"We confirm complete compliance with your specifications and delivery deadlines.\n\n"
        f"Sincerely,\n{vendor_name} — Enterprise Solutions Group"
    )

    if not os.getenv('GEMINI_API_KEY'):
        return fallback_quote

    try:
        from google import genai
        from google.genai import types

        prompt = {
            'vendor_name': vendor_name,
            'procurement_requirements': requirements,
            'catalog_offer': offer,
            'rfq_inquiry': rfq_body,
            'baseline_unit_price': unit_price,
            'baseline_total': total_price,
            'currency': curr,
        }

        instruction = (
            f"You are the Commercial Director representing '{vendor_name}'. "
            "Write a formal, professional commercial quotation letter responding to the buyer's RFQ. "
            "Include: Quotation reference number, formal greeting, confirmed item description, "
            f"clear line item pricing in {curr} (unit price, subtotal, tax breakdown, grand total), "
            "delivery timeline, freight/insurance terms, payment terms (e.g. Net 30), warranty period, and validity. "
            "Write in a polished business tone. Return ONLY the quotation letter text."
        )

        with genai.Client(api_key=os.environ['GEMINI_API_KEY'], http_options=types.HttpOptions(timeout=25000)) as client:
            response = client.models.generate_content(
                model=os.getenv('GEMINI_MODEL', GEMINI_MODEL),
                contents=json.dumps(prompt),
                config={'system_instruction': instruction, 'temperature': 0.4},
            )
        return response.text.strip() if response.text else fallback_quote
    except Exception:
        return fallback_quote



# ---------------------------------------------------------------------------
# AI Vendor Negotiation & Progress Comparison Agent
# ---------------------------------------------------------------------------

def negotiate_and_compare_vendors(requirements: dict, vendors: list[dict]) -> dict:
    """Analyze all vendor quotations, calculate savings against budget,
    compare commercial terms, and generate an actionable negotiation playbook."""
    if not vendors:
        return {
            'best_vendor_id': None,
            'best_vendor_name': None,
            'progress_summary': 'No vendors available for commercial comparison.',
            'vendors_comparison': [],
            'negotiation_playbook': [],
        }

    product = requirements.get('product') or 'the requested requirement'
    currency = requirements.get('currency') or 'INR'
    qty = requirements.get('quantity') or 1
    budget = float(requirements.get('budget') or 0)

    # 1. Fallback deterministic analysis
    def _deterministic_comparison():
        compared = []
        for v in vendors:
            reply = v.get('reply_text') or ''
            price = None
            # Extract price from quote or offer
            if v.get('offer', {}).get('unit_price') is not None:
                try:
                    price = float(v['offer']['unit_price']) * qty
                except (ValueError, TypeError):
                    price = None
            
            # If price found in reply text (e.g., INR 365,800 or total)
            price_match = re.search(r'(?:Grand Total|Total|Price|Subtotal)[^\d]*([\d,]+(?:\.\d{2})?)', reply, re.IGNORECASE)
            if price_match:
                try:
                    extracted = float(price_match.group(1).replace(',', ''))
                    if extracted > 100:
                        price = extracted
                except ValueError:
                    pass

            if price is None:
                price = budget * 0.95 if budget > 0 else 50000.0

            diff = price - budget if budget > 0 else 0
            diff_pct = round((diff / budget) * 100, 1) if budget > 0 else 0
            is_cheaper = diff < 0

            status = "Lowest Price & Top Pick" if is_cheaper and abs(diff_pct) > 20 else ("Cheaper than Budget" if is_cheaper else ("At Target Budget" if diff == 0 else "Above Budget Target"))
            
            neg_tip = (
                f"Quoted {currency} {price:,.2f} ({abs(diff_pct)}% lower than target). Confirm written warranty and request 5-day delivery."
                if is_cheaper else
                f"Quoted {currency} {price:,.2f} ({diff_pct}% over budget). Counteroffer at {currency} {budget * 0.9:,.2f} citing competing bids."
            )

            target_counter = round(price * 0.93 if is_cheaper else budget * 0.92, 2)
            counter_draft = (
                f"Dear {v['vendor_name']} Commercial & Sales Team,\n\n"
                f"Thank you for submitting your formal quotation for {qty} unit(s) of {product}.\n\n"
                f"Our procurement committee has reviewed your proposal (quoted at {currency} {price:,.2f}). "
                + (
                    f"Your offer is among our top shortlisted bids; however, to finalize the award and issue our formal Purchase Order this week, "
                    f"we require a final volume adjustment to {currency} {target_counter:,.2f}, accompanied by Net 45 payment terms and a minimum 2-year warranty support package.\n\n"
                    if is_cheaper else
                    f"We have received competing proposals from qualified suppliers at a significantly more competitive price point with equivalent delivery timelines. "
                    f"We strongly prefer your technical solution, but we can only proceed if you can revise your commercial offer to {currency} {target_counter:,.2f} (all-inclusive DDP) with Net 45 payment terms.\n\n"
                )
                + f"If you can confirm acceptance of these revised terms by return email, we will fast-track contract sign-off and PO issuance.\n\n"
                f"We appreciate your partnership and look forward to your prompt response.\n\n"
                f"Sincerely,\n"
                f"Procurement & Sourcing Operations\n"
                f"AuditAI Commercial Sourcing"
            )

            compared.append({
                'vendor_id': str(v['vendor_id']),
                'vendor_name': v['vendor_name'],
                'quoted_price': round(price, 2),
                'diff_vs_budget': round(diff, 2),
                'diff_percent': diff_pct,
                'is_cheaper': is_cheaper,
                'savings_amount': round(abs(diff), 2) if is_cheaper else 0,
                'lead_time': v.get('offer', {}).get('lead_time_days') or '5-7 days',
                'commercial_status': status,
                'negotiation_tip': neg_tip,
                'counteroffer_email_draft': counter_draft,
                'needs_negotiation': True,
                'negotiation_decision': 'negotiate',
                'negotiation_decision_reason': '',
            })

        compared.sort(key=lambda x: x['quoted_price'])
        from backend.app.agentic_ai.reply_parser import analyze_email_negotiation_intelligence

        for idx, item in enumerate(compared):
            item['position_rank'] = idx + 1
            v_orig = next((x for x in vendors if str(x.get('vendor_id')) == str(item['vendor_id'])), {})
            intel = analyze_email_negotiation_intelligence(
                reply_text=v_orig.get('reply_text') or '',
                parsed_quote=v_orig.get('offer') or {'total_price': item['quoted_price']},
                budget=budget,
                currency=currency,
                benchmark_price=compared[0]['quoted_price'] if idx > 0 else None,
                benchmark_vendor=compared[0]['vendor_name'] if idx > 0 else None
            )
            item['negotiation_intelligence'] = intel

            # Format grounds and non-compliance text for counteroffer email
            grounds_list = intel.get('negotiation_grounds') or []
            wrong_list = intel.get('what_is_wrong') or []
            incomplete_list = intel.get('what_is_incomplete') or []

            grounds_email_snippet = ""
            if grounds_list:
                grounds_email_snippet = "\nSpecific Grounds for Commercial Adjustment:\n" + "\n".join([f"  • {g['title']}: {g['rationale']}" for g in grounds_list]) + "\n"

            corrections_email_snippet = ""
            if wrong_list:
                corrections_email_snippet = "\nPolicy Compliance Requirements:\n" + "\n".join([f"  • {w['violation']}: {w['policy']}" for w in wrong_list]) + "\n"

            if idx == 0:
                item['needs_negotiation'] = True
                item['negotiation_decision'] = 'negotiate'
                target_pref = round(item['quoted_price'] * 0.94, 2)
                round_2_target = round(item['quoted_price'] * 0.90, 2)
                policies_applied = [
                    f"Company Policy 1 (Preferred Partner Tier): 6% volume incentive target ({currency} {target_pref:,.2f})",
                    "Company Policy 2 (Working Capital): Mandatory Net 45 Days payment terms (Zero advance)",
                    "Company Policy 3 (Risk & Quality): Minimum 24-month comprehensive on-site warranty",
                    "Company Policy 4 (Logistics SLA): Priority 5-7 business days DDP delivery",
                ]
                item['company_policies_applied'] = policies_applied
                item['round_1_target_price'] = target_pref
                item['round_2_target_price'] = round_2_target
                item['round_2_requires_human_approval'] = True
                item['negotiation_decision_reason'] = (
                    f"{item['vendor_name']} is our #1 top-ranked preferred supplier ({currency} {item['quoted_price']:,.2f}). "
                    f"Identified {len(incomplete_list)} missing term(s) and {len(wrong_list)} policy correction(s). "
                    f"Round 1 Autonomous Policy Engine automatically dispatches our preferred-partner counteroffer ({currency} {target_pref:,.2f}, Net 45, 24-month warranty) based on volume incentive and policy grounds without human intervention."
                )
                item['counteroffer_email_draft'] = (
                    f"Dear {item['vendor_name']} Commercial & Sales Team,\n\n"
                    f"Thank you for submitting your formal quotation for {qty} unit(s) of {product}.\n\n"
                    f"Our autonomous procurement intelligence has evaluated your proposal (quoted at {currency} {item['quoted_price']:,.2f}). "
                    f"{item['vendor_name']} has emerged as our #1 preferred vendor for this award.\n"
                    f"{grounds_email_snippet}{corrections_email_snippet}\n"
                    f"In accordance with our Company Procurement Policies for primary award partners, we are ready to fast-track your Purchase Order subject to the following standard policy alignments (Round 1 Commercial Alignment):\n"
                    f"  • Preferred-Partner Volume Price: {currency} {target_pref:,.2f} (All-Inclusive DDP)\n"
                    f"  • Standard Payment Terms: Net 45 Days from invoice receipt\n"
                    f"  • Mandatory Warranty Coverage: Minimum 24-Month On-Site Commercial Warranty\n"
                    f"  • Delivery SLA: Priority 5-7 Business Days delivery\n\n"
                    f"If you can confirm these preferred-partner policy terms by return email, we will immediately proceed to contract sign-off and PO release.\n\n"
                    f"Sincerely,\n"
                    f"Autonomous Procurement Policy Engine\n"
                    f"AuditAI Commercial Sourcing"
                )
                item['round_2_counteroffer_draft'] = (
                    f"Dear {item['vendor_name']} Executive Commercial Team,\n\n"
                    f"Following our initial policy counteroffer for {qty} unit(s) of {product}, our Executive Procurement Authority has authorized a Round 2 Best-and-Final Offer (BAFO) prior to final Purchase Order issuance.\n\n"
                    f"To lock in an immediate single-source award today, our executive board requires:\n"
                    f"  • Round 2 Best-and-Final Price: {currency} {round_2_target:,.2f} (All-Inclusive DDP)\n"
                    f"  • Extended Credit Terms: Net 60 Days\n"
                    f"  • Extended Warranty & SLA: 36-Month Comprehensive Warranty with 24-hour replacement SLA\n\n"
                    f"Please confirm acceptance of this Best-and-Final Offer so we can release the authorized Purchase Order immediately.\n\n"
                    f"Sincerely,\n"
                    f"Executive Procurement Committee (Human-Approved Round 2 Escalation)\n"
                    f"AuditAI Commercial Sourcing"
                )
            else:
                best_bench = compared[0]
                item['needs_negotiation'] = True
                item['negotiation_decision'] = 'negotiate'
                target_match = round(best_bench['quoted_price'] * 0.98, 2)
                round_2_target = round(best_bench['quoted_price'] * 0.94, 2)
                policies_applied = [
                    f"Company Policy 1 (Competitive Benchmark Rule): Must match/beat leading bid ({currency} {best_bench['quoted_price']:,.2f}) at {currency} {target_match:,.2f}",
                    "Company Policy 2 (Working Capital): Mandatory Net 45 Days payment terms (Zero advance)",
                    "Company Policy 3 (Risk & Quality): Minimum 24-month comprehensive on-site warranty",
                    "Company Policy 4 (Logistics SLA): All-inclusive DDP delivery within 7 days",
                ]
                item['company_policies_applied'] = policies_applied
                item['round_1_target_price'] = target_match
                item['round_2_target_price'] = round_2_target
                item['round_2_requires_human_approval'] = True
                item['negotiation_decision_reason'] = (
                    f"Quoted price ({currency} {item['quoted_price']:,.2f}) exceeds the #1 market benchmark "
                    f"({best_bench['vendor_name']} at {currency} {best_bench['quoted_price']:,.2f}). "
                    f"Identified {len(incomplete_list)} missing term(s) and {len(wrong_list)} policy correction(s). "
                    f"Round 1 Autonomous Policy Engine automatically dispatches a benchmark-matching counteroffer ({currency} {target_match:,.2f}) based on competitive market grounds."
                )
                item['counteroffer_email_draft'] = (
                    f"Dear {item['vendor_name']} Commercial & Sales Team,\n\n"
                    f"Thank you for submitting your formal quotation for {qty} unit(s) of {product}.\n\n"
                    f"Our procurement engine has evaluated your proposal (quoted at {currency} {item['quoted_price']:,.2f}) against our Company Procurement Policies and competing market bids. "
                    f"We have received a verified benchmark quotation at {currency} {best_bench['quoted_price']:,.2f} with immediate delivery.\n"
                    f"{grounds_email_snippet}{corrections_email_snippet}\n"
                    f"Under our Corporate Competitive Sourcing Policy (Round 1 Automated Counteroffer), we invite {item['vendor_name']} to revise your offer to meet our qualification threshold:\n"
                    f"  • Target Benchmark Counteroffer: {currency} {target_match:,.2f} (All-Inclusive DDP)\n"
                    f"  • Mandatory Payment Terms: Net 45 Days\n"
                    f"  • Mandatory Warranty: Minimum 24-Month Commercial Warranty\n\n"
                    f"If you can confirm acceptance of these revised commercial terms by return email, your bid will advance to final executive PO sign-off.\n\n"
                    f"Sincerely,\n"
                    f"Autonomous Procurement Policy Engine\n"
                    f"AuditAI Commercial Sourcing"
                )
                item['round_2_counteroffer_draft'] = (
                    f"Dear {item['vendor_name']} Executive Sales Director,\n\n"
                    f"Following our Round 1 automated policy notice regarding {qty} unit(s) of {product}, our human procurement reviewer has authorized a final Round 2 Escalation (Best-and-Final Opportunity).\n\n"
                    f"Before we award the Purchase Order to the leading bidder, we are offering {item['vendor_name']} one final opportunity to secure this contract under the following Best-and-Final terms:\n"
                    f"  • Final Round 2 Target Price: {currency} {round_2_target:,.2f} (All-Inclusive DDP)\n"
                    f"  • Payment Terms: Net 60 Days\n"
                    f"  • Warranty & Support: 36-Month Priority Commercial Warranty\n\n"
                    f"Please reply with your signed confirmation within 24 hours if you wish to claim this award.\n\n"
                    f"Sincerely,\n"
                    f"Executive Procurement Committee (Human-Approved Round 2 Escalation)\n"
                    f"AuditAI Commercial Sourcing"
                )

        best = compared[0]
        max_savings = best['savings_amount'] if best['is_cheaper'] else 0
        max_savings_pct = abs(best['diff_percent']) if best['is_cheaper'] else 0

        summary = (
            f"{len(compared)} vendor proposals compared. {best['vendor_name']} is the most economical choice at "
            f"{currency} {best['quoted_price']:,.2f}, delivering {max_savings_pct}% savings ({currency} {max_savings:,.2f} below budget)."
        )

        playbook = [
            f"Use {best['vendor_name']}'s pricing as the benchmark anchor for all negotiations.",
            f"Invite second-ranked suppliers to price-match {best['vendor_name']} to qualify for dual-sourcing.",
            f"Negotiate Net 45 or Net 60 payment terms and SLA penalty clauses prior to PO issuance."
        ]

        return {
            'best_vendor_id': best['vendor_id'],
            'best_vendor_name': best['vendor_name'],
            'lowest_price': best['quoted_price'],
            'highest_price': compared[-1]['quoted_price'],
            'target_budget': budget,
            'max_savings_amount': max_savings,
            'max_savings_percentage': max_savings_pct,
            'progress_summary': summary,
            'vendors_comparison': compared,
            'negotiation_playbook': playbook,
            'analysis_mode': 'commercial_rules',
        }

    # Enforce deterministic Company Procurement Policies for Round 1 & Round 2 negotiations
    return _deterministic_comparison()
    if not os.getenv('GEMINI_API_KEY'):
        return _deterministic_comparison()

    try:
        from google import genai
        from google.genai import types

        prompt_vendors = []
        for v in vendors:
            prompt_vendors.append({
                'vendor_id': str(v['vendor_id']),
                'vendor_name': v['vendor_name'],
                'catalog_price': v.get('offer', {}).get('unit_price'),
                'catalog_lead_time': v.get('offer', {}).get('lead_time_days'),
                'reply_quote': (v.get('reply_text') or '')[:1000],
            })

        prompt_data = {
            'requirement': {
                'product': product,
                'quantity': qty,
                'target_budget': budget,
                'currency': currency,
            },
            'vendors': prompt_vendors,
        }

        schema = {
            'type': 'OBJECT',
            'properties': {
                'best_vendor_id': {'type': 'STRING'},
                'best_vendor_name': {'type': 'STRING'},
                'progress_summary': {'type': 'STRING'},
                'vendors_comparison': {
                    'type': 'ARRAY',
                    'items': {
                        'type': 'OBJECT',
                        'properties': {
                            'vendor_id': {'type': 'STRING'},
                            'vendor_name': {'type': 'STRING'},
                            'quoted_price': {'type': 'NUMBER'},
                            'diff_vs_budget': {'type': 'NUMBER'},
                            'diff_percent': {'type': 'NUMBER'},
                            'is_cheaper': {'type': 'BOOLEAN'},
                            'commercial_status': {'type': 'STRING'},
                            'negotiation_tip': {'type': 'STRING'},
                            'counteroffer_email_draft': {'type': 'STRING'},
                            'needs_negotiation': {'type': 'BOOLEAN'},
                            'negotiation_decision': {'type': 'STRING'},
                            'negotiation_decision_reason': {'type': 'STRING'},
                        },
                        'required': ['vendor_id', 'vendor_name', 'quoted_price', 'commercial_status', 'negotiation_tip', 'counteroffer_email_draft'],
                    },
                },
                'negotiation_playbook': {'type': 'ARRAY', 'items': {'type': 'STRING'}},
            },
            'required': ['best_vendor_id', 'best_vendor_name', 'progress_summary', 'vendors_comparison', 'negotiation_playbook'],
        }

        instruction = (
            "You are a Fortune 500 Chief Procurement Officer and elite commercial negotiator. "
            f"Analyze all vendor quotations against the client's target budget of {currency} {budget:,.2f} for {qty} unit(s) of {product}. "
            "For each vendor:\n"
            "1. Extract the exact total quoted price from their actual response text. Compare it to the target budget (calculate exact difference amount and percentage).\n"
            "2. Identify the cheapest vendor and calculate the exact cost delta between bids.\n"
            "3. Provide a sharp, strategic negotiation tip specifically tailored to that vendor's position.\n"
            "4. Craft a VERY HIGH-QUALITY, professional, and persuasive counteroffer email draft (in 'counteroffer_email_draft'). "
            "The email must be executive-ready, citing their exact quoted figure, referencing competing benchmark bids or budget constraints, "
            "proposing a specific counteroffer price, requesting Net 45/60 payment terms and 2-3 years warranty, and offering immediate PO issuance if accepted.\n"
            "5. Provide an actionable 3-step negotiation playbook for the buying team.\n"
            "6. Make an AI intelligence decision on whether commercial negotiations are needed ('needs_negotiation': boolean, 'negotiation_decision': 'negotiate' or 'no_negotiation_needed', and 'negotiation_decision_reason'). If the vendor's price is already >= 15% below budget with strong terms, decide 'no_negotiation_needed' so human can choose whether to override."
        )

        with genai.Client(api_key=os.environ['GEMINI_API_KEY'], http_options=types.HttpOptions(timeout=35000)) as client:
            response = client.models.generate_content(
                model=os.getenv('GEMINI_MODEL', GEMINI_MODEL),
                contents=json.dumps(prompt_data),
                config={
                    'system_instruction': instruction,
                    'response_mime_type': 'application/json',
                    'response_json_schema': schema,
                    'temperature': 0.2,
                },
            )

        if not response.text:
            return _deterministic_comparison()

        parsed = json.loads(response.text)
        comp_list = parsed.get('vendors_comparison') or []
        comp_list.sort(key=lambda x: x.get('quoted_price', float('inf')))
        for idx, item in enumerate(comp_list):
            item['position_rank'] = idx + 1
            p = float(item.get('quoted_price') or 0)
            diff_val = p - budget if budget > 0 else 0
            diff_p = round((diff_val / budget) * 100, 1) if budget > 0 else 0
            if idx == 0:
                item['needs_negotiation'] = True
                item['negotiation_decision'] = 'negotiate'
                target_pref = round(p * 0.94, 2)
                item['negotiation_decision_reason'] = (
                    f"{item.get('vendor_name')} is currently our #1 top-ranked preferred supplier ({currency} {p:,.2f}). "
                    f"AI is initiating an executive preferred-partner negotiation to secure an exclusive volume incentive ({currency} {target_pref:,.2f}) and 2-year warranty before final PO release."
                )
            else:
                best_bench = comp_list[0] if comp_list else {}
                item['needs_negotiation'] = True
                item['negotiation_decision'] = 'negotiate'
                item['negotiation_decision_reason'] = (
                    f"Quoted price ({currency} {p:,.2f}) is higher than the leading market benchmark "
                    f"({best_bench.get('vendor_name')} at {currency} {float(best_bench.get('quoted_price') or 0):,.2f}). "
                    f"AI recommends automatic commercial counteroffer to match or beat leading bid."
                )

        best = comp_list[0] if comp_list else {}
        lowest = best.get('quoted_price', 0)
        highest = comp_list[-1].get('quoted_price', 0) if comp_list else 0
        diff = lowest - budget if budget > 0 else 0
        max_savings = abs(diff) if diff < 0 else 0
        max_savings_pct = abs(round((diff / budget) * 100, 1)) if budget > 0 and diff < 0 else 0

        return {
            'best_vendor_id': parsed.get('best_vendor_id') or best.get('vendor_id'),
            'best_vendor_name': parsed.get('best_vendor_name') or best.get('vendor_name'),
            'lowest_price': lowest,
            'highest_price': highest,
            'target_budget': budget,
            'max_savings_amount': max_savings,
            'max_savings_percentage': max_savings_pct,
            'progress_summary': parsed.get('progress_summary') or '',
            'vendors_comparison': comp_list,
            'negotiation_playbook': parsed.get('negotiation_playbook') or [],
            'analysis_mode': 'gemini_negotiation_agent',
        }

    except Exception:
        return _deterministic_comparison()
