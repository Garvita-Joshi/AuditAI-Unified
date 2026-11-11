"""Permanent request deletion with immutable timestamped audit log trail."""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, exists
from backend.app.db import Base


class RequestArchive(Base):
    __tablename__ = 'request_archives'
    request_kind = Column(String(20), primary_key=True)
    request_id = Column(Integer, primary_key=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(Integer, ForeignKey('auth_users.id'), nullable=True)


class RequestRecordEvent(Base):
    __tablename__ = 'request_record_events'
    id = Column(Integer, primary_key=True)
    request_kind = Column(String(20), nullable=False, index=True)
    request_id = Column(Integer, nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey('auth_users.id'), nullable=False)
    action = Column(String(40), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def archived_condition(kind, request_id):
    return exists().where(RequestArchive.request_kind == kind,
        RequestArchive.request_id == request_id, RequestArchive.deleted_at.is_not(None))


def is_archived(db, kind, request_id):
    state = db.get(RequestArchive, (kind, request_id))
    return bool(state and state.deleted_at)


def record_action(db, kind, request_id, actor_id, action, **details):
    now = datetime.utcnow()
    timestamp_iso = now.isoformat() + "Z"
    log_time = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    actor_name = details.get("actor")
    actor_email = details.get("actor_email")
    actor_role = details.get("actor_role")
    if (not actor_name or actor_name.startswith("User #")) and actor_id:
        try:
            from backend.app.models.auth import AuthUser
            user_obj = db.get(AuthUser, actor_id)
            if user_obj:
                actor_name = f"{user_obj.display_name} ({user_obj.email} · {user_obj.role.title()})"
                actor_email = user_obj.email
                actor_role = user_obj.role
        except Exception:
            pass

    event_details = {
        **details,
        "timestamp": details.get("timestamp") or timestamp_iso,
        "log_time": details.get("log_time") or log_time,
        "actor_id": actor_id,
        "actor": actor_name or details.get("actor") or ("User #" + str(actor_id)),
        "actor_email": actor_email,
        "actor_role": actor_role,
        "action": action
    }
    db.add(RequestRecordEvent(
        request_kind=kind,
        request_id=request_id,
        actor_id=actor_id,
        action=action,
        details=event_details,
        created_at=now
    ))


def set_archived(db, kind, request_id, actor_id, deleted):
    state = db.get(RequestArchive, (kind, request_id))
    if state and state.deleted_at and not deleted:
        # Once deleted, there is no going back
        raise ValueError("Once a request is deleted, there is no going back. Deletion is permanent and irreversible.")
    if state is None:
        state = RequestArchive(request_kind=kind, request_id=request_id)
        db.add(state)
    now = datetime.utcnow()
    state.deleted_at = now if deleted else None
    state.deleted_by = actor_id if deleted else None
    record_action(
        db,
        kind,
        request_id,
        actor_id,
        'request_permanently_deleted' if deleted else 'restore_attempted',
        permanent=True,
        irreversible=True,
        note='Request permanently deleted. Once deleted, there is no going back.'
    )
    db.commit()


def get_audit_log(db, kind, request_id):
    """Retrieve the complete immutable timestamped audit log trail for a request."""
    user_map = {}
    try:
        from backend.app.models.auth import AuthUser
        for u in db.query(AuthUser).all():
            user_map[u.id] = {
                "name": u.display_name or u.email,
                "email": u.email,
                "role": u.role or "employee",
                "employee_id": u.employee_id
            }
    except Exception:
        pass

    events = (db.query(RequestRecordEvent)
              .filter_by(request_kind=kind, request_id=request_id)
              .order_by(RequestRecordEvent.created_at.desc(), RequestRecordEvent.id.desc())
              .all())
    log_entries = []
    seen_keys = set()
    for e in events:
        details = dict(e.details or {})
        timestamp = details.get("timestamp") or (e.created_at.isoformat() + "Z")
        log_time = details.get("log_time") or e.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        seen_keys.add((e.action, timestamp[:19]))
        
        u_info = user_map.get(e.actor_id)
        actor_name = details.get("actor")
        if (not actor_name or actor_name.startswith("User #")) and u_info:
            actor_name = f"{u_info['name']} ({u_info['email']} · {u_info['role'].title()})"
        elif not actor_name:
            actor_name = f"User #{e.actor_id}"

        log_entries.append({
            "id": e.id,
            "request_kind": e.request_kind,
            "request_id": e.request_id,
            "actor_id": e.actor_id,
            "actor": actor_name,
            "actor_name": u_info['name'] if u_info else details.get("actor_name"),
            "actor_email": u_info['email'] if u_info else details.get("actor_email"),
            "actor_role": u_info['role'] if u_info else details.get("actor_role"),
            "action": e.action,
            "details": details,
            "timestamp": timestamp,
            "log_time": log_time
        })

    if kind == 'sourcing':
        try:
            from backend.app.agentic_ai.records import AgentActivity
            activities = (db.query(AgentActivity)
                          .filter_by(request_id=request_id)
                          .order_by(AgentActivity.created_at.desc(), AgentActivity.id.desc())
                          .all())
            for a in activities:
                ts_iso = (a.created_at.isoformat() + "Z")
                ts_short = ts_iso[:19]
                if (a.event, ts_short) in seen_keys:
                    continue
                seen_keys.add((a.event, ts_short))
                det = a.details if isinstance(a.details, dict) else {'info': str(a.details)}
                log_entries.append({
                    "id": f"act-{a.id}",
                    "request_kind": "sourcing",
                    "request_id": a.request_id,
                    "actor_id": 1,
                    "actor": a.actor or "AI Agent",
                    "action": a.event,
                    "details": {**det, "actor": a.actor or "AI Agent"},
                    "timestamp": ts_iso,
                    "log_time": a.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                })
        except Exception:
            pass

    log_entries.sort(key=lambda x: str(x.get('timestamp') or ''), reverse=True)
    return log_entries

