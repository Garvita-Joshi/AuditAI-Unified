import ssl

import pytest

from backend.app.agentic_ai import messaging


def test_mail_tls_keeps_certificate_checks_when_system_ca_is_missing(monkeypatch):
    monkeypatch.setenv('SSL_CERT_FILE', '/missing/local/python/cert.pem')
    context = messaging.mail_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()['x509_ca'] > 0


@pytest.mark.parametrize('implicit_ssl', [True, False])
@pytest.mark.parametrize('refused', [False, True])
def test_rfq_uses_verified_tls_and_reports_smtp_refusals(monkeypatch, implicit_ssl, refused):
    config = dict(host='smtp.gmail.com', port=465 if implicit_ssl else 587,
                  username='prepares23@gmail.com', password='test-app-password',
                  from_email='prepares23@gmail.com', redirect_email='',
                  use_ssl=implicit_ssl, configured=True)
    monkeypatch.setattr(messaging, 'get_smtp_config', lambda: config)
    calls = []

    class SmtpClient:
        def __init__(self, host, port, **kwargs):
            if implicit_ssl:
                self.check_context(kwargs['context'])

        @staticmethod
        def check_context(context):
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname is True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, *, context):
            self.check_context(context)
            calls.append('starttls')

        def login(self, username, password):
            calls.append('login')

        def send_message(self, message):
            calls.append(message)
            return {'supplier@business.test': (550, b'Recipient rejected')} if refused else {}

    monkeypatch.setattr(messaging.smtplib, 'SMTP_SSL' if implicit_ssl else 'SMTP', SmtpClient)
    args = dict(to_email='supplier@business.test', subject='Approved quotation request',
                body='Please quote for ten headsets.', run_id=7, vendor_id=11)
    if refused:
        with pytest.raises(RuntimeError, match='550: Recipient rejected'):
            messaging.send_rfq(**args)
    else:
        result = messaging.send_rfq(**args)
        assert result['recipient'] == 'supplier@business.test'
        assert result['ref_token'] == 'AuditAI-R7-V11'
    assert ('starttls' in calls) is (not implicit_ssl)
    message = calls[-1]
    assert message['To'] == 'supplier@business.test'
    assert message['From'] == 'prepares23@gmail.com'
    assert message['Cc'] == 'prepares23@gmail.com'
