import pytest
from backend.app.api import auth

@pytest.mark.parametrize('port,ssl_expected', [(465,True),(587,False)])
def test_otp_uses_port_specific_tls_and_normalizes_gmail_password(monkeypatch,port,ssl_expected):
    import smtplib
    calls=[]
    class MailClient:
        def __init__(self,*args,**kwargs): calls.append(('connect',kwargs))
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def starttls(self,**kwargs): calls.append(('starttls',kwargs))
        def login(self,user,password): calls.append(('login',password))
        def send_message(self,message): calls.append(('send',message['To']))
    def unexpected(*args,**kwargs): raise AssertionError('Wrong SMTP transport')
    monkeypatch.setattr(smtplib,'SMTP_SSL',MailClient if ssl_expected else unexpected)
    monkeypatch.setattr(smtplib,'SMTP',unexpected if ssl_expected else MailClient)
    for name,value in {'SMTP_HOST':'smtp.gmail.com','SMTP_PORT':port,'SMTP_USERNAME':'sender@example.test','SMTP_PASSWORD':'abcd efgh ijkl mnop','SMTP_FROM_EMAIL':'sender@example.test','AUTH_DEBUG_OTP':False}.items():
        monkeypatch.setattr(auth,name,value)
    auth.deliver_otp('recipient@example.test','123456')
    assert ('login','abcdefghijklmnop') in calls
    assert ('send','recipient@example.test') in calls
    assert any(c[0]=='starttls' for c in calls)==(not ssl_expected)
