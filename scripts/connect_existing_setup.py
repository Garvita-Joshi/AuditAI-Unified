"""One-time local setup import. Source DB is read-only; target is a separate database.
No purchase history, OTP/session tokens, messages, or payment records are imported.
"""
from pathlib import Path
import json, os, secrets, shutil, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('/Users/garvita16/Desktop/Projects/AuditAI-main')

def main():
    source_env=dotenv_values(SOURCE/'.env')
    source_url=make_url(source_env['DATABASE_URL'])
    from sqlalchemy.exc import ProgrammingError
    target_url=source_url.set(database='auditai_unified')
    assert target_url.database != source_url.database
    admin=create_engine(source_url.set(database='postgres'),isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as c:
            if not c.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'),{'name':target_url.database}).scalar():
                c.execute(text('CREATE DATABASE auditai_unified'))
    except ProgrammingError as exc:
        if getattr(exc.orig, 'pgcode', None) != '42501':
            raise
        runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
        target_url=make_url('sqlite:///'+str(runtime/'unified.db'))
        print('PostgreSQL CREATE DATABASE permission unavailable; using isolated local SQLite.')
    finally:
        admin.dispose()
    workbook=json.loads((SOURCE/'data/company_workflow_data.json').read_text())
    employees={str(e.get('email','')).strip().lower():e for e in workbook.get('sheets',{}).get('Employees',[])}
    source_engine=create_engine(source_url)
    with source_engine.connect() as c:
        accounts=[dict(row) for row in c.execute(text('SELECT id,email,full_name,role,is_active FROM users')).mappings()]
    source_engine.dispose()
    env={k:v for k,v in source_env.items() if v is not None and (k.startswith(('SMTP_','SOURCING_','GEMINI_')))}
    env.update(DATABASE_URL=target_url.render_as_string(hide_password=False),JWT_SECRET_KEY=secrets.token_urlsafe(48),AUTH_DEBUG_OTP='false',AUTH_COOKIE_SECURE='false',FRONTEND_ORIGINS='http://127.0.0.1:5190',CORS_ORIGINS='http://127.0.0.1:5190',COMPANY_EMAIL_DOMAINS=','.join(sorted({a['email'].rsplit('@',1)[1].lower() for a in accounts}|{e.rsplit('@',1)[1] for e in employees if '@' in e})),COMPANY_VENDOR_CATALOG=str(ROOT/'data/vendors/company_catalog.json'))
    envpath=ROOT/'.env'
    if envpath.exists():
        prior=dotenv_values(envpath)
        env['JWT_SECRET_KEY']=prior.get('JWT_SECRET_KEY') or env['JWT_SECRET_KEY']
    envpath.write_text('\n'.join(k+'='+json.dumps(str(v)) for k,v in env.items())+'\n');envpath.chmod(0o600)
    for k,v in env.items():os.environ[k]=str(v)
    target=ROOT/'data/company_workflow_data.json';target.parent.mkdir(exist_ok=True)
    shutil.copy2(SOURCE/'data/company_workflow_data.json',target)
    from backend.app.main import app
    from backend.app.db import Base,engine,SessionLocal
    from backend.app.models.auth import AuthUser
    from backend.app.auth.security import hash_password
    from backend.app.procurement.company_data import workbook_catalog
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for account in accounts:
            email=account['email'].strip().lower();employee=employees.get(email,{})
            user=db.query(AuthUser).filter_by(email=email).first()
            if user is None:
                user=AuthUser(email=email,password_hash=hash_password(secrets.token_urlsafe(32)))
                db.add(user)
            user.employee_id=str(employee.get('employee_id') or f"LEGACY-{account['id']}")
            user.display_name=employee.get('full_name') or account['full_name'] or email.split('@')[0]
            user.role=account['role'] if account['role'] in {'manager','finance','security','admin','procurement','legal','it'} else 'employee'
            user.roles=sorted(set((user.roles or [])+['employee']+([user.role] if user.role!='employee' else [])))
            user.active=bool(account['is_active'])
        db.commit()
        account_count=db.query(AuthUser).count()
    offers=workbook_catalog()
    dest=ROOT/'data/vendors/company_catalog.json';dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(offers,indent=2,default=str))
    from backend.app.sourcing.catalog import load_catalog
    catalog=load_catalog()
    models=ROOT/'backend/trained_models';models.mkdir(exist_ok=True)
    for name in ['procurement_bundle.joblib','procurement_evaluation.json']:
        shutil.copy2(SOURCE/'backend/trained_models'/name,models/name)
    print(json.dumps({'database':target_url.database,'accounts':account_count,'directory_employees':len(employees),'catalog_offers':len(catalog),'procurement_model_copied':True,'expense_model_available':(models/'pipeline_v2.joblib').exists(),'smtp_configured':bool(env.get('SMTP_PASSWORD')),'sourcing_smtp_configured':bool(env.get('SOURCING_SMTP_PASSWORD'))}))

if __name__=='__main__': main()
