from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.company import Company
from app.schemas.job import CompanyListResponse, CompanyRead
from app.services import company_service

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=CompanyListResponse)
def list_companies(
    db: Session = Depends(get_db),
) -> CompanyListResponse:
    companies = company_service.list_companies(db)
    items = [company_service.company_view(db, company) for company in companies]
    return CompanyListResponse(items=items, total=len(items))


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(
    company_id: int, db: Session = Depends(get_db)
) -> CompanyRead:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company_service.company_view(db, company)
