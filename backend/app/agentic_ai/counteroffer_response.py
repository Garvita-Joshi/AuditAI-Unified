"""Classify a vendor's reply to an AuditAI counteroffer.

A reply that arrives *after* we sent a counteroffer is not a fresh quotation. It must
be read term by term against what we asked for, and "acceptance of the counteroffer"
must be tracked separately from "the vendor standing by its original quotation".

Outcome classes (``response_class``):
  accepted               every requested term accepted
  partially_accepted     some terms accepted, others declined
  rejected               vendor refuses the revised terms
  counter_proposal       vendor offers new numbers different from ours and its original
  clarification_requested vendor asks us a question before deciding
  deferred               vendor needs time / will revert
  withdrawn              vendor can no longer supply / withdraws the quote
  auto_reply             out-of-office or delivery-failure notice (no state change)
  unclear                nothing reliable could be extracted -> human review

Gemini is used when configured; a deterministic parser is always the fallback and is
also used to sanity-check Gemini's answer for the numeric terms.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

TERMS = ('price', 'payment', 'warranty', 'delivery')

_MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
     'september', 'october', 'november', 'december'], 1)}

_ACCEPT = re.compile(
    r'\b(accept(?:ed|s)?|agree(?:d|s)?|confirm(?:ed|s)?|approved?|can accommodate|will (?:meet|honou?r|comply)|'
    r'compliant|acceptable|happy to|glad to|we can do|works for us|no objection)\b', re.I)
_REJECT = re.compile(
    r"\b(declin(?:e|ed|es|ing)|reject(?:ed|s)?|cannot|can't|can not|unable|not (?:available|possible|feasible|able|acceptable)|"
    r"not accept(?:ed|able)?|unfortunately|regret|refus(?:e|ed)|will not|won't|not agree|denied|no\b)", re.I)
_AUTO = re.compile(
    r'(out of (?:the )?office|automatic reply|auto[- ]?reply|undeliverable|delivery (?:status )?notification|'
    r'mailer-daemon|on (?:annual )?leave until|will return on)', re.I)
_DEFER = re.compile(
    r"(will (?:get back|revert|respond|reply)|need(?:s)? (?:more )?time|under review|checking with|"
    r'consult(?:ing)? (?:our|with)|discussing internally|by (?:end of|next) (?:day|week|month))', re.I)
_WITHDRAW = re.compile(
    r"(withdraw(?:ing|n)? (?:our|the) (?:quote|quotation|offer|bid)|no longer (?:able|available|interested|supply)|"
    r"unable to supply|cannot supply|not (?:participate|participating)|stock (?:is )?(?:exhausted|unavailable)|"
    r'discontinued)', re.I)
_QUESTION = re.compile(
    r'(could you (?:please )?(?:clarify|confirm|share|provide)|please (?:clarify|confirm|share)|what (?:is|are) your|'
    r'can you (?:clarify|confirm)|kindly (?:clarify|confirm)|\bwhich\b[^.\n]*\?|need (?:clarification|more details))', re.I)
_GLOBAL_ACCEPT = re.compile(
    r"(accept(?:s|ed)?|agree(?:s|d)?(?: to)?|confirm(?:s|ed)?) (?:to |with )?(?:all |both |the |your |these )*"
    r"(?:revised |counter ?offer|counter-offer|proposed|terms|commercial)", re.I)
_GLOBAL_REJECT = re.compile(
    r"(cannot|can't|unable to|will not|do not|don't|not able to|unfortunately[^.\n]*cannot) (?:accept|agree|proceed|accommodate|meet)"
    r"[^.\n]*(?:counter|revised|proposed|terms|target)|"
    r"(?:decline|reject)(?:d|s)?[^.\n]*(?:counter|revised|proposed)|"
    r"cannot accept the proposed", re.I)

_TOPIC_KEYS = {
    'price': re.compile(r'\b(pric(?:e|ing)|total|cost|discount|amount|landed|unit rate|rate|quote value|counter ?offer acceptance)\b', re.I),
    'payment': re.compile(r'\b(payment|net\s*\d+|credit period|advance)\b', re.I),
    'warranty': re.compile(r'\b(warranty|guarantee|support period|amc)\b', re.I),
    'delivery': re.compile(r'\b(deliver(?:y|ed)|timeline|lead ?time|completion|deadline|dispatch|ship(?:ping|ment)?)\b', re.I),
}

_AMOUNT = re.compile(r'(?:INR|Rs\.?|₹|USD|\$)\s*([0-9][0-9,]*(?:\.\d{1,2})?)', re.I)


def _num(s) -> float | None:
    try:
        v = float(str(s).replace(',', '').strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _amounts(line: str) -> list[float]:
    return [v for v in (_num(m.group(1)) for m in _AMOUNT.finditer(line)) if v]


def _parse_date(text: str) -> date | None:
    m = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})[,\s]+(\d{4})', text)
    if m:
        month = _MONTHS.get(m.group(2).lower()) or next((n for k, n in _MONTHS.items() if k.startswith(m.group(2).lower()[:3])), None)
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    m = re.search(r'([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})', text)
    if m:
        month = _MONTHS.get(m.group(1).lower()) or next((n for k, n in _MONTHS.items() if k.startswith(m.group(1).lower()[:3])), None)
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                return None
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _warranty_months(text: str) -> int | None:
    m = re.search(r'(\d+(?:\.\d+)?)\s*[- ]?\s*(year|yr|month|mo)s?', text, re.I)
    if not m:
        return None
    n = float(m.group(1))
    return int(round(n * 12)) if m.group(2).lower() in ('year', 'yr') else int(round(n))


def _net_days(text: str) -> int | None:
    m = re.search(r'net\s*(\d+)', text, re.I)
    return int(m.group(1)) if m else None


def _lead_days(text: str) -> int | None:
    m = re.search(r'(\d+)\s*(calendar|business|working)?\s*(day|week)s?', text, re.I)
    if not m:
        return None
    n = int(m.group(1))
    return n * 7 if m.group(3).lower() == 'week' else n


def _sections(text: str) -> dict[str, list[str]]:
    """Group the lines of the reply by the topic of the section they sit in."""
    buckets: dict[str, list[str]] = {t: [] for t in TERMS}
    buckets['_general'] = []
    current = '_general'
    for raw in text.replace('\r', '\n').split('\n'):
        line = raw.strip(' \t-•*')
        if not line:
            continue
        header = re.match(r'^(?:\d+[.)]|#{1,4})\s*(.{2,60})$', line)
        if header and not re.search(r'[:.]\s*\S', header.group(1)):
            title = header.group(1)
            for topic, key in _TOPIC_KEYS.items():
                if key.search(title):
                    current = topic
                    break
            else:
                current = '_general'
            continue
        # A line that names exactly one topic belongs to that topic regardless of section.
        hits = [t for t, k in _TOPIC_KEYS.items() if k.search(line.split(':')[0])]
        if len(hits) > 1 and ':' not in line:
            # Free-text sentence covering several topics: let each topic see it.
            for topic in hits:
                buckets[topic].append(line)
            buckets['_general'].append(line)
            continue
        topic = hits[0] if len(hits) == 1 else current
        if topic == 'price' and _TOPIC_KEYS['payment'].search(line) and 'net' in line.lower():
            topic = 'payment'
        buckets[topic].append(line)
        if topic != '_general':
            buckets['_general'].append(line)
    return buckets


def _verdict(lines: list[str]) -> str | None:
    """accepted / declined / None from explicit wording; the last explicit marker wins
    but a line saying a *requirement was accepted/declined* beats descriptive lines."""
    verdict = None
    for line in lines:
        label_part = line.split(':')[-1] if ':' in line else line
        explicit_label = bool(re.search(r'(accept|declin|reject|complian|requirement|deadline|immediate|available)', line.split(':')[0], re.I)) if ':' in line else False
        rej = _REJECT.search(label_part)
        acc = _ACCEPT.search(label_part)
        if explicit_label or ':' not in line:
            if rej and not acc:
                verdict = 'declined'
            elif acc and not rej:
                verdict = 'accepted'
            elif rej and acc:
                # "cannot ... but accepted": take whichever phrase comes last
                verdict = 'accepted' if acc.start() > rej.start() else 'declined'
    return verdict


def _targets_norm(targets: dict | None) -> dict:
    t = dict(targets or {})
    t['price'] = _num(t.get('price'))
    t['payment_days'] = _net_days(str(t.get('payment_terms') or '')) or (int(t['payment_days']) if t.get('payment_days') else None)
    t['warranty_months'] = int(t['warranty_months']) if t.get('warranty_months') else _warranty_months(str(t.get('warranty') or ''))
    d = t.get('delivery_deadline')
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d[:10]).date()
        except ValueError:
            d = None
    t['delivery_deadline'] = d
    return t


def _regex_analyze(text: str, targets: dict, original_quote: float | None, today: date) -> dict:
    sec = _sections(text)
    terms: dict[str, dict] = {k: {'decision': 'not_addressed', 'vendor_value': None, 'target': None, 'compliant': None, 'evidence': None} for k in TERMS}

    # ── price ───────────────────────────────────────────────────────────────────
    price = terms['price']
    price['target'] = targets['price']
    vendor_revised = None
    for line in sec['price']:
        label = line.split(':')[0].lower()
        vals = _amounts(line)
        if not vals:
            continue
        # skip lines that quote OUR target or the vendor's ORIGINAL numbers
        if re.search(r'(your|our target|procurement|requested|counter ?offer target|target)', label):
            continue
        if re.search(r'(original|initial|previous|earlier|gst|tax|charge|deployment|shipping|freight|base)', label):
            continue
        if re.search(r'(revised|new|final|best|improved|reduced|discounted|offer(?:ed)?|can offer|quote)', label) or ':' not in line:
            vendor_revised = vals[-1]
    price['vendor_value'] = vendor_revised
    pv = _verdict(sec['price'])
    if vendor_revised is not None:
        if targets['price'] and vendor_revised <= targets['price'] * 1.001:
            price['decision'] = 'accepted'
        elif original_quote and vendor_revised < original_quote * 0.999:
            price['decision'] = 'counter_proposed'
        elif pv == 'accepted':
            price['decision'] = 'accepted'
        elif original_quote and abs(vendor_revised - original_quote) / original_quote < 0.001:
            price['decision'] = 'declined'
        else:
            price['decision'] = pv or 'declined'
    elif pv:
        price['decision'] = pv
    if price['decision'] != 'not_addressed':
        price['evidence'] = next((l for l in reversed(sec['price']) if _REJECT.search(l) or _ACCEPT.search(l)), None)

    # ── payment ─────────────────────────────────────────────────────────────────
    pay = terms['payment']
    pay['target'] = targets['payment_days']
    pdv = _verdict(sec['payment'])
    offered_days = None
    for line in sec['payment']:
        d = _net_days(line)
        if d and not re.search(r'(requested|your|counter ?offer terms|target)', line.split(':')[0], re.I):
            offered_days = d
    if offered_days is None and sec['payment']:
        offered_days = next((d for d in (_net_days(l) for l in sec['payment']) if d), None)
    pay['vendor_value'] = offered_days
    if pdv:
        pay['decision'] = pdv
    elif offered_days is not None and targets['payment_days']:
        pay['decision'] = 'accepted' if offered_days >= targets['payment_days'] else 'declined'
    if pay['decision'] == 'accepted' and offered_days and targets['payment_days'] and offered_days < targets['payment_days'] and pdv is None:
        pay['decision'] = 'declined'
    if pay['decision'] != 'not_addressed':
        pay['evidence'] = next((l for l in reversed(sec['payment']) if _REJECT.search(l) or _ACCEPT.search(l)), None)

    # ── warranty ────────────────────────────────────────────────────────────────
    war = terms['warranty']
    war['target'] = targets['warranty_months']
    wv = _verdict(sec['warranty'])
    months = None
    for line in sec['warranty']:
        m = _warranty_months(line)
        if m and not re.search(r'(requirement|requested|your)', line.split(':')[0], re.I):
            months = m
    if months is None:
        months = next((m for m in (_warranty_months(l) for l in sec['warranty']) if m), None)
    war['vendor_value'] = months
    if wv:
        war['decision'] = wv
    elif months is not None and targets['warranty_months']:
        war['decision'] = 'accepted' if months >= targets['warranty_months'] else 'declined'
    if war['decision'] == 'accepted' and months and targets['warranty_months'] and months < targets['warranty_months']:
        war['decision'] = 'declined'
    if war['decision'] != 'not_addressed':
        war['evidence'] = next((l for l in reversed(sec['warranty']) if _REJECT.search(l) or _ACCEPT.search(l)), None)

    # ── delivery ────────────────────────────────────────────────────────────────
    dl = terms['delivery']
    dl['target'] = targets['delivery_deadline'].isoformat() if targets['delivery_deadline'] else (targets.get('delivery_days') or None)
    dv = _verdict(sec['delivery'])
    promised_date = None
    promised_days = None
    for line in sec['delivery']:
        if re.search(r'(immediate|required deadline)', line.split(':')[0], re.I) and ':' in line:
            continue
        promised_date = promised_date or _parse_date(line)
        promised_days = promised_days or _lead_days(line)
    if promised_date is None and promised_days:
        from datetime import timedelta
        promised_date = today + timedelta(days=promised_days)
    dl['vendor_value'] = promised_date.isoformat() if promised_date else promised_days
    meets = None
    if promised_date and targets['delivery_deadline']:
        meets = promised_date <= targets['delivery_deadline']
    elif promised_days and targets.get('delivery_days'):
        meets = promised_days <= int(targets['delivery_days'])
    if dv:
        dl['decision'] = dv
    elif meets is not None:
        dl['decision'] = 'accepted' if meets else 'declined'
    elif promised_date or promised_days:
        dl['decision'] = 'counter_proposed'
    elif sec['delivery']:
        dl['decision'] = 'not_addressed'
    if meets is False and dl['decision'] == 'accepted' and dv is None:
        dl['decision'] = 'declined'
    if dl['decision'] != 'not_addressed':
        dl['evidence'] = next((l for l in reversed(sec['delivery']) if _REJECT.search(l) or _ACCEPT.search(l)), None)

    for key, term in terms.items():
        term['compliant'] = {'accepted': True, 'declined': False}.get(term['decision'])
    return {'terms': terms}


def _validity_days(text: str) -> int | None:
    m = re.search(r'valid(?:ity)?(?:\s+for|\s+up to|\s+until)?\s*(\d+)\s*days|(\d+)\s*days\s+(?:validity|from)', text, re.I)
    if m:
        return int(m.group(1) or m.group(2))
    return None


def _classify(text: str, terms: dict) -> tuple[str, str]:
    """Return (response_class, reason)."""
    if _AUTO.search(text[:600]):
        return 'auto_reply', 'Automated out-of-office / delivery notice.'
    if _WITHDRAW.search(text):
        return 'withdrawn', 'Vendor withdrew or can no longer supply.'

    decisions = [t['decision'] for t in terms.values()]
    acc = decisions.count('accepted')
    dec = decisions.count('declined')
    cnt = decisions.count('counter_proposed')
    addressed = acc + dec + cnt

    if addressed == 0:
        if _GLOBAL_REJECT.search(text):
            return 'rejected', 'Vendor declined the revised terms without itemising them.'
        if _GLOBAL_ACCEPT.search(text):
            return 'accepted', 'Vendor accepted the revised terms in general wording.'
        if _QUESTION.search(text) or text.count('?') >= 1:
            return 'clarification_requested', 'Vendor is asking a question before deciding.'
        if _DEFER.search(text):
            return 'deferred', 'Vendor will respond later.'
        return 'unclear', 'No term-level decision could be identified.'

    if cnt and not acc and not dec:
        return 'counter_proposal', 'Vendor proposed its own revised terms.'
    if cnt:
        return 'counter_proposal', 'Vendor accepted some terms and proposed alternatives for others.'
    if dec == 0:
        return 'accepted', 'Every addressed term meets the counteroffer.'
    if acc == 0:
        return 'rejected', 'Every addressed term was declined.'
    return 'partially_accepted', f'{acc} term(s) accepted, {dec} declined.'


_STATUS_MAP = {
    'accepted': ('counteroffer_accepted', 'counteroffer_accepted', 'ready_for_po_authorization', False),
    'partially_accepted': ('counteroffer_partially_accepted', 'negotiation_pending', 'prepare_round_2_or_escalate', True),
    'rejected': ('counteroffer_rejected', 'negotiation_pending', 'prepare_round_2_bafo_or_move_to_next_vendor', True),
    'counter_proposal': ('counter_proposal_received', 'negotiation_pending', 'evaluate_vendor_counter_proposal', True),
    'clarification_requested': ('vendor_question_pending', 'vendor_question_pending', 'answer_vendor_question', True),
    'deferred': ('awaiting_vendor_decision', 'awaiting_vendor_decision', 'wait_and_follow_up', False),
    'withdrawn': ('vendor_withdrew', 'declined_cannot_supply', 'remove_vendor_from_ranking', True),
    'auto_reply': ('no_change', None, 'ignore_auto_reply', False),
    'unclear': ('needs_human_review', 'reply_received_human_review', 'human_review', True),
}


def _gemini_analyze(text: str, targets: dict, original_quote, currency: str) -> dict | None:
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        term_schema = {
            'type': 'OBJECT',
            'properties': {
                'decision': {'type': 'STRING', 'enum': ['accepted', 'declined', 'counter_proposed', 'not_addressed']},
                'vendor_value': {'type': 'STRING'},
                'evidence': {'type': 'STRING'},
            },
            'required': ['decision'],
        }
        schema = {
            'type': 'OBJECT',
            'properties': {
                'response_class': {'type': 'STRING', 'enum': [
                    'accepted', 'partially_accepted', 'rejected', 'counter_proposal', 'clarification_requested',
                    'deferred', 'withdrawn', 'auto_reply', 'unclear']},
                'price': term_schema, 'payment': term_schema, 'warranty': term_schema, 'delivery': term_schema,
                'quote_validity_days': {'type': 'INTEGER'},
                'summary': {'type': 'STRING'},
            },
            'required': ['response_class', 'price', 'payment', 'warranty', 'delivery', 'summary'],
        }
        prompt = (
            'You read a vendor email that REPLIES TO A PROCUREMENT COUNTEROFFER. Decide, term by term, whether the '
            'vendor ACCEPTED, DECLINED, or COUNTER-PROPOSED our requested terms. Do not treat a repeated original '
            'quotation, or acceptance of only one term (e.g. warranty), as acceptance of the counteroffer.\n'
            f"Our counteroffer targets: price={targets.get('price')} {currency}; payment={targets.get('payment_terms')}; "
            f"warranty={targets.get('warranty_months')} months; delivery deadline={targets.get('delivery_deadline')}.\n"
            f"Vendor's original quotation: {original_quote} {currency}.\n"
            'Use not_addressed when the email is silent on a term. Treat out-of-office, questions, requests for time '
            'and withdrawals with the matching response_class.\n\n'
            f'Vendor email:\n"""\n{text[:5000]}\n"""'
        )
        resp = client.models.generate_content(
            model=os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'),
            contents=prompt,
            config={'response_mime_type': 'application/json', 'response_json_schema': schema, 'temperature': 0.0},
        )
        return json.loads(resp.text) if resp.text else None
    except Exception:
        return None


def analyze_counteroffer_reply(reply_text: str, targets: dict | None = None, original_quote: float | None = None,
                               currency: str = 'INR', today: date | None = None, use_llm: bool = True) -> dict:
    """Analyse a vendor reply to a counteroffer. ``targets`` keys: price, payment_terms|payment_days,
    warranty|warranty_months, delivery_deadline (date or ISO string), delivery_days."""
    today = today or date.today()
    text = (reply_text or '').strip()
    tg = _targets_norm(targets)
    original_quote = _num(original_quote)

    if not text:
        base_terms = {k: {'decision': 'not_addressed', 'vendor_value': None, 'target': None, 'compliant': None, 'evidence': None} for k in TERMS}
        cls, reason = 'unclear', 'Empty reply.'
        analyzer = 'rules'
    else:
        parsed = _regex_analyze(text, tg, original_quote, today)
        base_terms = parsed['terms']
        analyzer = 'rules'
        llm = _gemini_analyze(text, tg, original_quote, currency) if use_llm else None
        if llm:
            analyzer = 'gemini+rules'
            for key in TERMS:
                item = llm.get(key) or {}
                dec = item.get('decision')
                rule_dec = base_terms[key]['decision']
                # The deterministic numeric comparison wins when it is certain; Gemini fills gaps.
                if dec in ('accepted', 'declined', 'counter_proposed') and rule_dec == 'not_addressed':
                    base_terms[key]['decision'] = dec
                    base_terms[key]['compliant'] = {'accepted': True, 'declined': False}.get(dec)
                    base_terms[key]['evidence'] = item.get('evidence')
                    if base_terms[key]['vendor_value'] is None and item.get('vendor_value'):
                        base_terms[key]['vendor_value'] = item['vendor_value']
        cls, reason = _classify(text, base_terms)
        if llm and cls in ('unclear',) and llm.get('response_class') in _STATUS_MAP:
            cls, reason = llm['response_class'], llm.get('summary') or reason
        # Never let a single accepted term mean full acceptance.
        addressed = [t['decision'] for t in base_terms.values() if t['decision'] != 'not_addressed']
        if cls == 'accepted' and addressed and 'accepted' in addressed and len(addressed) < 2 and not _GLOBAL_ACCEPT.search(text):
            cls, reason = 'partially_accepted', 'Only one term addressed; other counteroffer terms are unconfirmed.'

    negotiation_status, vendor_status, next_action, needs_human = _STATUS_MAP[cls]
    price_t = base_terms['price']
    pay_t = base_terms['payment']
    war_t = base_terms['warranty']
    del_t = base_terms['delivery']
    unaddressed = [k for k, v in base_terms.items() if v['decision'] == 'not_addressed']
    full = cls == 'accepted' and not unaddressed
    # Silence on a term is not acceptance.
    if cls == 'accepted' and unaddressed:
        cls = 'partially_accepted'
        negotiation_status, vendor_status, next_action, needs_human = _STATUS_MAP[cls]
        reason = f"Accepted, but no explicit answer for: {', '.join(unaddressed)}."

    return {
        'response_class': cls,
        'counteroffer_acceptance': {
            'accepted': 'accepted', 'partially_accepted': 'partial', 'rejected': 'rejected',
            'counter_proposal': 'counter_proposed',
        }.get(cls, 'none'),
        'counteroffer_fully_accepted': full,
        'quotation_acceptance': 'stands_by_original_quote' if cls in ('rejected', 'partially_accepted') else 'n/a',
        'original_quote': original_quote,
        'counteroffer_price': price_t['target'],
        'vendor_revised_price': price_t['vendor_value'] if price_t['decision'] in ('accepted', 'counter_proposed') else None,
        'terms': base_terms,
        'warranty_compliant': war_t['compliant'],
        'payment_terms_accepted': pay_t['compliant'],
        'delivery_compliant': del_t['compliant'],
        'unaddressed_terms': unaddressed,
        'quote_validity_days': _validity_days(text),
        'negotiation_status': negotiation_status,
        'vendor_status': vendor_status,
        'next_action': next_action,
        'requires_human': needs_human,
        'reason': reason,
        'analyzer': analyzer,
        'analysed_at': datetime.utcnow().isoformat(),
    }


def targets_from_negotiation(neg: dict | None, requirements: dict | None, draft_text: str = '') -> dict:
    """Build the counteroffer target set from stored negotiation data + the draft we sent."""
    neg = neg or {}
    requirements = requirements or {}
    draft = draft_text or neg.get('round_2_counteroffer_draft') or neg.get('counteroffer_email_draft') or ''
    rnd = int(neg.get('negotiation_round') or 1)
    price = (neg.get('round_2_target_price') if rnd >= 2 and neg.get('round_2_approved_and_sent') else None) or neg.get('round_1_target_price')
    if not price and draft:
        amounts = _amounts(draft)
        price = amounts[0] if amounts else None
    pay = None
    m = re.search(r'net\s*\d+', draft, re.I)
    if m:
        pay = m.group(0)
    war = _warranty_months(draft) if re.search(r'warrant', draft, re.I) else None
    return {
        'price': price,
        'payment_terms': pay or 'Net 45',
        'warranty_months': war or 24,
        'delivery_deadline': requirements.get('delivery_deadline'),
    }
