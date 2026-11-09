# services/models.py
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, BigInteger, Text, Numeric, JSON, TIMESTAMP
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass

class Order(Base):
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True)
    order_id = Column(Text, unique=True)

    user_id = Column(BigInteger, nullable=False)
    direction = Column(Text, nullable=False)
    crypto = Column(Text, nullable=False)

    crypto_amount = Column(Numeric(20, 8))
    fiat_amount = Column(Numeric(20, 2))
    rate = Column(Numeric(20, 8))

    requisites = Column(Text)
    status = Column(Text, nullable=False)

    payment_details = Column(JSON)
    created_at = Column(TIMESTAMP, server_default=func.now())
