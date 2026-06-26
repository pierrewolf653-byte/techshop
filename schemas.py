from pydantic import BaseModel

class ProductBase(BaseModel):
    name: str
    description: str
    price: float
    category: str
    image_url: str

class Product(ProductBase):
    id: int

    class Config:
        from_attributes = True