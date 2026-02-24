from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session
from jose import JWTError

from app.database import get_db
from app.auth import decode_access_token
from app.models import Company, AdminUser


def get_current_company(
    access_token: str = Cookie(None),
    db: Session = Depends(get_db),
) -> Company:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/company/login"})
    try:
        payload = decode_access_token(access_token)
        if payload.get("type") != "company":
            raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/company/login"})
        company_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/company/login"})

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not company.is_active:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/company/login"})
    return company


def get_current_admin(
    admin_token: str = Cookie(None),
    db: Session = Depends(get_db),
) -> AdminUser:
    if not admin_token:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/admin/login"})
    try:
        payload = decode_access_token(admin_token)
        if payload.get("type") != "admin":
            raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/admin/login"})
        admin_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/admin/login"})

    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not admin or not admin.is_active:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/admin/login"})
    return admin
