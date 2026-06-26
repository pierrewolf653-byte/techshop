from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from database import SessionLocal
from models import Product as ProductModel
from schemas import Product

router = APIRouter(prefix="/products", tags=["products"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/", response_model=List[Product])
def get_products(db: Session = Depends(get_db)):
    return db.query(ProductModel).all()