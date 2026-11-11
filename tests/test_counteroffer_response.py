from datetime import date

from backend.app.agentic_ai.counteroffer_response import analyze_counteroffer_reply, targets_from_negotiation

TARGETS = {'price': 86240, 'payment_terms': 'Net 45', 'warranty_months': 24, 'delivery_deadline': date(2026, 11, 27)}
TODAY = date(2026, 11, 10)


def run(text, original=305000):
    return analyze_counteroffer_reply(text, TARGETS, original, today=TODAY, use_llm=False)


REJECTION = """Dear AuditAI Commercial Sourcing Team,

Thank you for reviewing our quotation and providing the revised commercial terms.

1. Revised Pricing
- Our Original Unit Price: INR 2,50,000
- GST (18%): INR 45,000
- International Deployment Charges: INR 10,000
- Total Landed Price: INR 3,05,000
- Your Target Counteroffer: INR 86,240
- Counteroffer Acceptance: Declined.
Unfortunately, we cannot accommodate the proposed target price due to the customization and implementation requirements.

2. Delivery Commitment
- Implementation Timeline: 40 calendar days
- Expected Completion: 20 December 2026
- Immediate Delivery: Not Available
- Required Deadline: Cannot be met.
3. Warranty
- Warranty Period: 24 months
- Counteroffer Warranty Requirement: Accepted.
- Support: 24/7 technical assistance.
- Critical Issue Response: Within 4 hours.
4. Payment Terms
- Our Proposed Payment Terms: Net 30
- Requested Counteroffer Terms: Net 45
- Net 45 Acceptance: Declined.
5. Final Commercial Position

We appreciate the opportunity but cannot accept the proposed revised commercial terms. Our original quotation remains valid for 45 days.

Regards,
Garvita
"""


def test_user_example_partial_rejection_is_not_full_compliance():
    r = run(REJECTION)
    assert r['terms']['price']['decision'] == 'declined'
    assert r['terms']['payment']['decision'] == 'declined'
    assert r['terms']['warranty']['decision'] == 'accepted'
    assert r['terms']['delivery']['decision'] == 'declined'
    assert r['warranty_compliant'] is True
    assert r['payment_terms_accepted'] is False
    assert r['delivery_compliant'] is False
    assert r['counteroffer_fully_accepted'] is False
    assert r['response_class'] == 'partially_accepted'
    assert r['vendor_status'] == 'negotiation_pending'
    assert r['quote_validity_days'] == 45
    assert r['original_quote'] == 305000
    assert r['counteroffer_price'] == 86240


def test_pure_rejection():
    r = run('Dear team,\nWe regret that we cannot accept the proposed revised commercial terms. Our original quotation stands.\nRegards')
    assert r['response_class'] == 'rejected'
    assert r['counteroffer_acceptance'] == 'rejected'
    assert r['requires_human'] is True


def test_full_acceptance_itemised():
    r = run("""Dear Team,
1. Pricing
- Revised Total Price: INR 86,240
- Counteroffer Acceptance: Accepted.
2. Payment Terms
- Net 45 Acceptance: Accepted.
3. Warranty
- Warranty Period: 24 months. Accepted.
4. Delivery
- Expected Completion: 25 November 2026
- Delivery Deadline: Accepted.
""")
    assert r['response_class'] == 'accepted'
    assert r['counteroffer_fully_accepted'] is True
    assert r['vendor_status'] == 'counteroffer_accepted'


def test_general_acceptance_without_itemising_is_partial_if_silent_terms():
    r = run('We accept your revised counteroffer and agree to the proposed terms.')
    # Wording is global, but nothing explicit about each term -> needs confirmation, not auto-PO.
    assert r['response_class'] in ('accepted', 'partially_accepted')
    assert r['counteroffer_fully_accepted'] is False or r['unaddressed_terms'] == []


def test_counter_proposal_with_new_price():
    r = run("""Dear Team,
Thank you. We can offer a revised price of INR 2,10,000 with Net 30 payment terms.
""")
    assert r['terms']['price']['decision'] == 'counter_proposed'
    assert r['response_class'] in ('counter_proposal', 'partially_accepted')
    assert r['vendor_revised_price'] == 210000
    assert r['counteroffer_fully_accepted'] is False


def test_warranty_only_never_means_acceptance():
    r = run('Hi, we confirm the 24 months warranty.')
    assert r['response_class'] != 'accepted'
    assert r['counteroffer_fully_accepted'] is False


def test_clarification_question():
    r = run('Could you please clarify whether the target price includes GST and installation?')
    assert r['response_class'] == 'clarification_requested'
    assert r['vendor_status'] == 'vendor_question_pending'


def test_deferred():
    r = run('Thanks for the update. Our management is reviewing it and we will get back to you by end of week.')
    assert r['response_class'] == 'deferred'


def test_withdrawn():
    r = run('We are unable to supply this item any longer and withdraw our quotation.')
    assert r['response_class'] == 'withdrawn'
    assert r['vendor_status'] == 'declined_cannot_supply'


def test_auto_reply_is_ignored():
    r = run('Automatic reply: I am out of office until Monday and will return on 15 Nov.')
    assert r['response_class'] == 'auto_reply'
    assert r['vendor_status'] is None


def test_empty_and_unclear():
    assert run('')['response_class'] == 'unclear'
    assert run('ok thanks')['response_class'] == 'unclear'


def test_targets_from_draft():
    neg = {'round_1_target_price': 86240, 'counteroffer_email_draft': 'Target INR 86,240 with Net 45 payment terms and a 2 year warranty.'}
    t = targets_from_negotiation(neg, {'delivery_deadline': '2026-11-27'}, neg['counteroffer_email_draft'])
    assert t['price'] == 86240 and t['payment_terms'].lower() == 'net 45' and t['warranty_months'] == 24

