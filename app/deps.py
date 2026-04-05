from typing import Optional
from datetime import datetime
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import decode_access_token
from app import models


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[models.User]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id: int = payload.get("sub")
    if not user_id:
        return None
    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if not user or not user.is_active:
        return None
    return user


def require_login(request: Request, db: Session = Depends(get_db)) -> models.User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
        )
    if user.must_change_password and request.url.path != "/auth/change-password":
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/change-password?first=1"},
        )
    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> models.User:
    user = require_login(request, db)
    if user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return user


def get_system_config(db: Session, key: str, default: str = "") -> str:
    cfg = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return cfg.value if cfg else default


def get_valid_authorization(db: Session, user: models.User) -> models.BookingAuthorization | None:
    """Retorna a primeira autorização válida do jogador, preferindo permanente."""
    authorizations = (
        db.query(models.BookingAuthorization)
        .filter(
            models.BookingAuthorization.user_id == user.id,
            models.BookingAuthorization.is_active == True,
            models.BookingAuthorization.used_at == None,
        )
        .order_by(models.BookingAuthorization.auth_type)  # permanent < single alfabeticamente
        .all()
    )
    for auth in authorizations:
        if auth.is_valid:
            return auth
    return None


def consume_authorization(db: Session, auth: models.BookingAuthorization) -> None:
    """Consome uma autorização avulsa. Permanentes não são consumidas."""
    if auth.auth_type == models.AuthorizationType.SINGLE:
        auth.used_at = datetime.utcnow()
        db.commit()
