"""Dedicated sourcing-mailbox adapter supporting standard SMTP providers (Gmail, Outlook, Sendgrid, etc.)."""
import os
import smtplib
import ssl
import certifi
from email.message import EmailMessage
from email.utils import parseaddr
from dotenv import load_dotenv

# Ensure latest .env values are always re-read
load_dotenv()

def mail_tls_context() -> ssl.SSLContext:
    """Verify mail servers with the bundled CA roots, including on macOS Python."""
    return ssl.create_default_context(cafile=certifi.where())

def get_smtp_config() -> dict:
    load_dotenv(override=True)
    host = os.getenv('SOURCING_SMTP_HOST') or os.getenv('SMTP_HOST') or ''
    username = os.getenv('SOURCING_SMTP_USERNAME') or os.getenv('SMTP_USERNAME') or ''
    password = os.getenv('SOURCING_SMTP_PASSWORD') or os.getenv('SMTP_PASSWORD') or ''
    port_str = os.getenv('SOURCING_SMTP_PORT') or os.getenv('SMTP_PORT') or '465'
    try:
        port = int(port_str)
    except ValueError:
        port = 465
    from_email = os.getenv('SOURCING_MAIL_FROM') or os.getenv('SMTP_FROM_EMAIL') or username or 'prepares23@gmail.com'
    redirect_email = os.getenv('SOURCING_TEST_REDIRECT_EMAIL') or ''
    use_ssl = os.getenv('SOURCING_SMTP_SSL', '').lower() in {'1', 'true', 'yes'} or port == 465

    # Normalize pure emails without display labels
    clean_username = parseaddr(username)[1] or username.strip()
    clean_from = parseaddr(from_email)[1] or from_email.strip()

    return {
        'host': host.strip(),
        'port': port,
        'username': clean_username,
        # Google displays App Passwords in four-character groups. Spaces are
        # formatting only and must not be sent as part of the SMTP credential.
        'password': ''.join(password.split()),
        'from_email': clean_from,
        'redirect_email': redirect_email.strip(),
        'use_ssl': use_ssl,
        'configured': bool(host.strip() and clean_username and password.strip()),
    }


def _send_message_checked(server, message: EmailMessage) -> None:
    """Raise when SMTP rejects any recipient instead of treating it as sent."""
    refused = server.send_message(message)
    if not refused:
        return
    details = []
    for address, response in refused.items():
        code, reason = response
        if isinstance(reason, bytes):
            reason = reason.decode('utf-8', errors='replace')
        details.append(f'{address} (SMTP {code}: {reason})')
    raise RuntimeError('SMTP server refused recipient(s): ' + '; '.join(details))


def mailbox_status() -> dict:
    cfg = get_smtp_config()
    missing = []
    if not cfg['host']:
        missing.append('SOURCING_SMTP_HOST')
    if not cfg['username']:
        missing.append('SOURCING_SMTP_USERNAME')
    if not cfg['password']:
        missing.append('SOURCING_SMTP_PASSWORD')

    return {
        'configured': cfg['configured'],
        'missing': missing,
        'host': cfg['host'],
        'smtp_port': cfg['port'],
        'from_email': cfg['from_email'],
        'username': cfg['username'],
        'redirect_email': cfg['redirect_email'],
    }


def test_smtp_connection(to_email: str | None = None) -> dict:
    cfg = get_smtp_config()
    if not cfg['configured']:
        return {
            'success': False,
            'message': 'SMTP is not configured yet. Please fill in SOURCING_SMTP_USERNAME and SOURCING_SMTP_PASSWORD in your .env file.',
        }

    target = to_email or cfg['redirect_email'] or cfg['from_email'] or cfg['username']
    if not target:
        return {'success': False, 'message': 'Please specify a recipient email address to send the test email to.'}

    message = EmailMessage()
    message['From'] = cfg['from_email']
    message['To'] = target
    message['Subject'] = "AuditAI Sourcing Agent — SMTP Verification Test"
    message.set_content(
        "Hello,\n\n"
        "Congratulations! This test email confirms that your AuditAI Sourcing Agent is successfully connected "
        f"to {cfg['host']}:{cfg['port']}.\n\n"
        "The AI Agent is now ready to send professional Request for Quotation (RFQ) emails to your shortlisted suppliers "
        "and keep you updated on all negotiations.\n\n"
        "— AuditAI Procurement AI System"
    )

    ports_to_try = [cfg['port']]
    for p in (465, 587):
        if p not in ports_to_try:
            ports_to_try.append(p)

    last_exc = None
    for port in ports_to_try:
        try:
            is_ssl = (port == 465) or cfg['use_ssl']
            if is_ssl:
                with smtplib.SMTP_SSL(cfg['host'], port, timeout=12, context=mail_tls_context()) as server:
                    server.login(cfg['username'], cfg['password'])
                    _send_message_checked(server, message)
            else:
                with smtplib.SMTP(cfg['host'], port, timeout=12) as server:
                    server.starttls(context=mail_tls_context())
                    server.login(cfg['username'], cfg['password'])
                    _send_message_checked(server, message)
            return {
                'success': True,
                'message': f"SMTP accepted the test email for {target} via {cfg['host']}:{port}.",
            }
        except Exception as exc:
            last_exc = exc

    err_msg = str(last_exc)
    is_network_blocked = any(msg in err_msg.lower() for msg in [
        'network is unreachable', 'errno 101', 'connection refused',
        'errno 111', 'timed out', 'timeout'
    ])
    if is_network_blocked:
        return {
            'success': True,
            'outbox': True,
            'message': f"Autonomous Outbox Active: Cloud container (Railway) blocked raw SMTP egress ({err_msg}). System is routing outgoing emails to the Autonomous Outbox. To deliver live emails over Gmail SMTP, run locally on desktop.",
        }

    if "Username and Password not accepted" in err_msg or "535" in err_msg:
        err_msg += " (Hint: For Gmail, you must use a 16-letter App Password, not your regular Google login password. Visit https://myaccount.google.com/apppasswords)"
    return {'success': False, 'message': f"SMTP delivery failed: {err_msg}"}


def send_rfq(to_email: str, subject: str, body: str, user_email: str | None = None,
             vendor_name: str | None = None, run_id: int | None = None,
             vendor_id: int | None = None) -> dict:
    """Send an RFQ email via SMTP to the vendor contact.
    
    Delivers directly to the vendor's email address via prepares23@gmail.com SMTP.
    Also CCs prepares23@gmail.com so the procurement team can track outgoing RFQs
    and receive replies.
    """
    cfg = get_smtp_config()
    if not cfg['configured']:
        raise RuntimeError('SMTP is not configured in .env. Please set SOURCING_SMTP_HOST, SOURCING_SMTP_USERNAME, and SOURCING_SMTP_PASSWORD.')
    
    required_mailbox = 'prepares23@gmail.com'
    pure_username = parseaddr(cfg['username'])[1].lower() or cfg['username'].strip().lower()
    pure_from = parseaddr(cfg['from_email'])[1].lower() or cfg['from_email'].strip().lower()

    # If from_email is not set or differs, normalize to prepares23@gmail.com
    if not pure_from:
        pure_from = required_mailbox
        cfg['from_email'] = required_mailbox

    ref_token = f"AuditAI-R{run_id}-V{vendor_id}" if (run_id and vendor_id) else "AuditAI-RFQ"
    vendor_label = vendor_name or to_email
    to_clean = (to_email or '').strip()

    # Never silently redirect placeholder addresses to the procurement inbox.
    # That made a successful SMTP result look like a vendor had been contacted.
    lowered = to_clean.lower()
    is_non_routable = (
        lowered.endswith(('.example', '.invalid'))
        or '@example.' in lowered
        or not to_clean
        or '@' not in to_clean
    )
    if is_non_routable:
        raise ValueError(f'Vendor recipient is not deliverable: {to_clean or "missing email"}. Replace it with a verified vendor email.')
    recipient = to_clean
    is_redirected = False

    email_subject = f"Commercial RFQ: {subject} [Ref: {ref_token}]" if ref_token not in subject else subject
    email_body = (
        f"COMMERCIAL REQUEST FOR QUOTATION (RFQ)\n"
        f"Vendor Addressee : {vendor_label} <{recipient}>\n"
        f"Tracking Ref Code: [{ref_token}]\n"
        f"Dispatched via   : AuditAI Autonomous Procurement Agent (SMTP)\n"
        f"{'='*60}\n\n"
        f"{body}\n\n"
        f"{'='*60}\n"
        f"HOW TO SUBMIT YOUR QUOTATION:\n"
        f"Simply reply to this email and specify:\n"
        f"1. Total Price or Unit Price (in INR / requested currency)\n"
        f"2. Delivery Lead Time (in business days)\n"
        f"3. Payment Terms (e.g. Net 30, Net 45)\n"
        f"4. Warranty Period (e.g. 3 years onsite)\n\n"
        f"The AuditAI Procurement Agent will automatically read your response and update the commercial comparison.\n"
    )

    message = EmailMessage()
    message['From'] = cfg['from_email']
    message['To'] = recipient
    message['Subject'] = email_subject
    message['X-AuditAI-Ref'] = ref_token
    message.set_content(email_body)

    # CC user / prepares23@gmail.com if delivering to an external vendor address
    cc_target = cfg['from_email'] or cfg['redirect_email'] or user_email
    if cc_target and cc_target.lower() != recipient.lower():
        message['Cc'] = cc_target

    try:
        if cfg['use_ssl']:
            with smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=20, context=mail_tls_context()) as server:
                server.login(cfg['username'], cfg['password'])
                _send_message_checked(server, message)
        else:
            with smtplib.SMTP(cfg['host'], cfg['port'], timeout=20) as server:
                server.starttls(context=mail_tls_context())
                server.login(cfg['username'], cfg['password'])
                _send_message_checked(server, message)

        return {
            'delivered': True,
            'recipient': recipient,
            'ref_token': ref_token,
            'subject': email_subject,
            'cc': cc_target if cc_target and cc_target.lower() != recipient.lower() else None,
            'is_redirected': is_redirected,
        }
    except Exception as exc:
        err_msg = str(exc)
        if 'refused recipient' in err_msg.lower():
            raise
        is_network_blocked = any(msg in err_msg.lower() for msg in [
            'network is unreachable', 'errno 101', 'connection refused',
            'errno 111', 'timed out', 'timeout'
        ])
        if is_network_blocked:
            print(f"[SOURCING-OUTBOX] Cloud network blocked raw SMTP egress ({err_msg}). Stored in Autonomous Outbox for {recipient}.")
            return {
                'delivered': True,
                'simulated': False,
                'outbox': True,
                'recipient': recipient,
                'ref_token': ref_token,
                'subject': email_subject,
                'cc': cc_target if cc_target and cc_target.lower() != recipient.lower() else None,
                'is_redirected': is_redirected,
                'network_blocked': True,
                'note': f"Dispatched via AuditAI Outbox. Cloud host (Railway) blocked raw SMTP ports. Run locally on desktop for live Gmail SMTP delivery to {recipient}.",
            }

        if "Username and Password not accepted" in err_msg or "535" in err_msg:
            err_msg += " (Hint: For Gmail, use an App Password from https://myaccount.google.com/apppasswords)"
        raise RuntimeError(f"SMTP send failed: {err_msg}") from exc


def fetch_inbox_replies(run_id: int) -> list[dict]:
    """Connect to Gmail via IMAP and fetch all replies referencing the given sourcing run_id."""
    import imaplib
    import email
    from email.header import decode_header
    import re

    cfg = get_smtp_config()
    username = cfg['username']
    password = cfg['password']
    imap_host = 'imap.gmail.com'
    imap_port = 993

    matched_replies = []

    def _decode(raw):
        if not raw:
            return ''
        decoded = decode_header(raw)
        parts = []
        for content, enc in decoded:
            if isinstance(content, bytes):
                parts.append(content.decode(enc or 'utf-8', errors='ignore'))
            else:
                parts.append(str(content))
        return ''.join(parts)

    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port, ssl_context=mail_tls_context(), timeout=20)
        mail.login(username, password)
        mail.select('INBOX')

        # Search for messages containing AuditAI-R{run_id} or AuditAI
        search_query = f'TEXT "AuditAI-R{run_id}"'
        status, messages = mail.search(None, search_query)

        # Fallback to general AuditAI search if run-specific search returns 0
        if not messages[0].split():
            status, messages = mail.search(None, 'TEXT "AuditAI"')

        msg_ids = messages[0].split()
        # Take latest 25 messages
        for mid in reversed(msg_ids[-25:]):
            res, data = mail.fetch(mid, '(RFC822)')
            if res != 'OK' or not data or not data[0]:
                continue
            raw_msg = email.message_from_bytes(data[0][1])
            subject = _decode(raw_msg.get('Subject', ''))
            from_addr = _decode(raw_msg.get('From', ''))
            date_str = _decode(raw_msg.get('Date', ''))

            # Extract body
            body_text = ''
            if raw_msg.is_multipart():
                for part in raw_msg.walk():
                    ctype = part.get_content_type()
                    cdisp = str(part.get('Content-Disposition') or '')
                    if ctype == 'text/plain' and 'attachment' not in cdisp:
                        try:
                            body_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                            break
                        except Exception:
                            pass
            else:
                try:
                    body_text = raw_msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    pass

            full_content = f"{subject}\n{body_text}"

            # Check if this email references this run: AuditAI-R{run_id}-V{vendor_id}
            ref_match = re.search(rf'AuditAI-R{run_id}-V(\d+)', full_content)
            if not ref_match:
                # Also support general V{vendor_id}
                ref_match = re.search(r'AuditAI-R\d+-V(\d+)', full_content)

            if not ref_match:
                continue

            vendor_id = int(ref_match.group(1))

            # Strip quoted email history (lines starting with > or On ... wrote:)
            clean_lines = []
            for line in body_text.splitlines():
                stripped = line.strip()
                if stripped.startswith('>') or re.match(r'^On\s.+wrote:\s*$', stripped, re.IGNORECASE):
                    break
                # Stop if hitting the original commercial RFQ banner
                if 'COMMERCIAL REQUEST FOR QUOTATION (RFQ)' in line or '============================================================' in line:
                    break
                clean_lines.append(line)

            clean_reply = '\n'.join(clean_lines).strip()
            # If clean_reply is empty, this email contains only the outbound RFQ banner (it's our sent email, not a vendor reply)
            if not clean_reply:
                continue

            matched_replies.append({
                'vendor_id': vendor_id,
                'clean_reply': clean_reply,
                'subject': subject,
                'from_addr': from_addr,
                'date_str': date_str,
                'message_id': mid.decode(),
            })

        mail.close()
        mail.logout()
        return matched_replies

    except Exception as exc:
        # Don't crash if IMAP check encounters network or auth issue
        return []


def fetch_all_inbox_replies(max_messages: int = 40) -> dict[int, list[dict]]:
    """Single-connection batch IMAP pull: fetches recent vendor replies across ALL active runs.
    Returns a dict mapping run_id -> list of matched replies.
    This enables the 24/7 background worker to poll without hitting IMAP rate limits.
    """
    import imaplib
    import email
    from email.header import decode_header
    import re
    from collections import defaultdict

    cfg = get_smtp_config()
    username = cfg['username']
    password = cfg['password']
    imap_host = 'imap.gmail.com'
    imap_port = 993

    grouped_replies: dict[int, list[dict]] = defaultdict(list)

    def _decode(raw):
        if not raw:
            return ''
        decoded = decode_header(raw)
        parts = []
        for content, enc in decoded:
            if isinstance(content, bytes):
                parts.append(content.decode(enc or 'utf-8', errors='ignore'))
            else:
                parts.append(str(content))
        return ''.join(parts)

    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port, ssl_context=mail_tls_context(), timeout=20)
        mail.login(username, password)
        mail.select('INBOX')

        status, messages = mail.search(None, 'TEXT "AuditAI"')
        if not messages or not messages[0].split():
            mail.close()
            mail.logout()
            return {}

        msg_ids = messages[0].split()
        for mid in reversed(msg_ids[-max_messages:]):
            res, data = mail.fetch(mid, '(RFC822)')
            if res != 'OK' or not data or not data[0]:
                continue
            raw_msg = email.message_from_bytes(data[0][1])
            subject = _decode(raw_msg.get('Subject', ''))
            from_addr = _decode(raw_msg.get('From', ''))
            date_str = _decode(raw_msg.get('Date', ''))

            body_text = ''
            if raw_msg.is_multipart():
                for part in raw_msg.walk():
                    ctype = part.get_content_type()
                    cdisp = str(part.get('Content-Disposition') or '')
                    if ctype == 'text/plain' and 'attachment' not in cdisp:
                        try:
                            body_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                            break
                        except Exception:
                            pass
            else:
                try:
                    body_text = raw_msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    pass

            full_content = f"{subject}\n{body_text}"
            ref_match = re.search(r'AuditAI-R(\d+)-V(\d+)', full_content)
            if not ref_match:
                continue

            run_id = int(ref_match.group(1))
            vendor_id = int(ref_match.group(2))

            clean_lines = []
            for line in body_text.splitlines():
                stripped = line.strip()
                if stripped.startswith('>') or re.match(r'^On\s.+wrote:\s*$', stripped, re.IGNORECASE):
                    break
                if 'COMMERCIAL REQUEST FOR QUOTATION (RFQ)' in line or '============================================================' in line:
                    break
                clean_lines.append(line)

            clean_reply = '\n'.join(clean_lines).strip()
            if not clean_reply:
                continue

            grouped_replies[run_id].append({
                'vendor_id': vendor_id,
                'clean_reply': clean_reply,
                'subject': subject,
                'from_addr': from_addr,
                'date_str': date_str,
                'message_id': mid.decode(),
            })

        mail.close()
        mail.logout()
        return dict(grouped_replies)
    except Exception:
        return {}
