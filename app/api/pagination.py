import math
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas.api import Page

T = TypeVar("T")


def paginate(db: Session, query, model: type[T], page: int, page_size: int) -> Page[T]:
    total = db.scalar(select(func.count()).select_from(model)) or 0
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=items, total=total, page=page, page_size=page_size,
                pages=math.ceil(total / page_size) if total else 0)
