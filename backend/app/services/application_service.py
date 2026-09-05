from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application


def list_applications(db: Session) -> list[Application]:
    return list(db.scalars(select(Application).order_by(Application.created_at.desc())))
