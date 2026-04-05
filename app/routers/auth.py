from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.auth import hash_password, verify_password, create_access_token
from app.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

DEFAULT_INITIAL_PASSWORD = "Baroneza@2025"


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("auth/login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == email.lower().strip()).first()
    if not user or not verify_password(password, user.password_hash) or not user.is_active:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "E-mail ou senha incorretos."},
            status_code=401,
        )
    token = create_access_token({"sub": str(user.id)})
    # Se precisa trocar senha, redireciona para troca obrigatória
    if user.must_change_password:
        response = RedirectResponse("/auth/change-password?first=1", status_code=302)
    else:
        response = RedirectResponse("/", status_code=302)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 8)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/auth/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, first: str = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)
    return templates.TemplateResponse(
        "auth/change_password.html",
        {"request": request, "user": user, "error": None, "success": False, "first": first == "1"},
    )


@router.post("/change-password", response_class=HTMLResponse)
def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    # Bloqueia navegação se deve trocar senha
    first = user.must_change_password

    if not verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(
            "auth/change_password.html",
            {"request": request, "user": user, "error": "Senha atual incorreta.", "success": False, "first": first},
        )
    if new_password != confirm_password:
        return templates.TemplateResponse(
            "auth/change_password.html",
            {"request": request, "user": user, "error": "As senhas não coincidem.", "success": False, "first": first},
        )
    if len(new_password) < 6:
        return templates.TemplateResponse(
            "auth/change_password.html",
            {"request": request, "user": user, "error": "A senha deve ter ao menos 6 caracteres.", "success": False, "first": first},
        )
    if new_password == current_password:
        return templates.TemplateResponse(
            "auth/change_password.html",
            {"request": request, "user": user, "error": "A nova senha deve ser diferente da senha atual.", "success": False, "first": first},
        )

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.commit()

    return templates.TemplateResponse(
        "auth/change_password.html",
        {"request": request, "user": user, "error": None, "success": True, "first": False},
    )
