"""
SQLAlchemy Models - Inventory Module
재고 거래 내역 관련 모델
"""
from datetime import datetime
from typing import Optional
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, Text, Integer,
    DateTime, Enum, Index
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ecommerce.platform.backend.app.database import Base


# ==================================================
# Enums
# ==================================================

class ProductType(str, PyEnum):
    """상품 유형"""
    NEW = "new"
    USED = "used"


class TransactionType(str, PyEnum):
    """재고 거래 유형"""
    PURCHASE = "purchase"
    SALE = "sale"
    RETURN = "return"
    ADJUSTMENT = "adjustment"


# ==================================================
# Inventory Transaction Model
# ==================================================

class InventoryTransaction(Base):
    """재고 거래 내역"""
    __tablename__ = "inventorytransactions"
    __table_args__ = (
        Index('idx_option', 'product_option_type', 'product_option_id'),
        Index('idx_created', 'created_at'),
        {'comment': '재고 거래 내역'}
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment='재고 거래 내역 고유 ID'
    )
    product_option_type: Mapped[ProductType] = mapped_column(
        Enum(ProductType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, comment='옵션 유형'
    )
    product_option_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment='품목 옵션 ID'
    )
    quantity_change: Mapped[int] = mapped_column(
        Integer, nullable=False, comment='수량 변동 (양수: 입고, 음수: 출고)'
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, comment='거래 유형'
    )
    reference_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='Order ID 등 참조 ID'
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, comment='비고'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), comment='생성일시'
    )
