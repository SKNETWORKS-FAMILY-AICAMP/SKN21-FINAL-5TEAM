from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

# ==========================================
# Primitive Types & Enums
# ==========================================

ID = str
CurrencyCode = str  # "KRW", "USD", "JPY", "EUR", etc.


class OrderStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    PREPARING = "preparing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    EXCHANGE_REQUESTED = "exchange_requested"
    REFUND_REQUESTED = "refund_requested"
    REFUNDED = "refunded"
    UNKNOWN = "unknown"


class DeliveryStatus(str, Enum):
    READY = "ready"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    UNKNOWN = "unknown"


class KnowledgeDocumentType(str, Enum):
    FAQ = "faq"
    SHIPPING_POLICY = "shipping_policy"
    RETURN_POLICY = "return_policy"
    EXCHANGE_POLICY = "exchange_policy"
    CANCEL_POLICY = "cancel_policy"
    GENERAL_POLICY = "general_policy"


class OrderActionType(str, Enum):
    CANCEL = "cancel"
    REFUND = "refund"
    EXCHANGE = "exchange"


class OrderActionReason(str, Enum):
    CHANGED_MIND = "changed_mind"
    WRONG_ITEM = "wrong_item"
    DEFECTIVE_ITEM = "defective_item"
    DELAYED_DELIVERY = "delayed_delivery"
    DUPLICATE_ORDER = "duplicate_order"
    OTHER = "other"


class OrderActionStatus(str, Enum):
    ACCEPTED = "accepted"
    REQUESTED = "requested"
    REJECTED = "rejected"
    NOT_ALLOWED = "not_allowed"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


# ==========================================
# Core Models
# ==========================================


class Money(BaseModel):
    amount: float
    currency: CurrencyCode


class AuthenticatedContext(BaseModel):
    siteId: str
    userId: str
    sessionRef: Optional[str] = None
    accessToken: Optional[str] = None
    cookies: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, Any]] = None


class User(BaseModel):
    id: ID
    siteId: str
    email: Optional[str] = None
    name: Optional[str] = None


class ProductSummary(BaseModel):
    id: ID
    siteId: str
    title: str
    shortDescription: Optional[str] = None
    price: Optional[Money] = None
    inStock: Optional[bool] = None
    imageUrl: Optional[str] = None
    productUrl: Optional[str] = None
    categoryIds: Optional[List[ID]] = None
    brand: Optional[str] = None


class KnowledgeDocument(BaseModel):
    id: ID
    siteId: str
    type: KnowledgeDocumentType
    title: str
    content: str
    url: Optional[str] = None
    tags: Optional[List[str]] = None
    updatedAt: Optional[str] = None


class DeliveryEvent(BaseModel):
    status: str
    description: Optional[str] = None
    timestamp: Optional[str] = None


class DeliveryTracking(BaseModel):
    orderId: ID
    deliveryStatus: DeliveryStatus
    carrierName: Optional[str] = None
    trackingNumber: Optional[str] = None
    trackingUrl: Optional[str] = None
    lastUpdatedAt: Optional[str] = None
    events: Optional[List[DeliveryEvent]] = None


class OrderItem(BaseModel):
    productId: ID
    productTitle: str
    quantity: int
    unitPrice: Optional[Money] = None
    imageUrl: Optional[str] = None


class OrderSummary(BaseModel):
    orderId: ID
    siteId: str
    userId: ID
    status: OrderStatus
    items: List[OrderItem]
    totalPrice: Optional[Money] = None
    orderedAt: Optional[str] = None


# ==========================================
# Request / Response Schemas
# ==========================================


class ProductSearchFilter(BaseModel):
    query: str
    categoryIds: Optional[List[ID]] = None
    brandNames: Optional[List[str]] = None
    minPrice: Optional[float] = None
    maxPrice: Optional[float] = None
    inStockOnly: Optional[bool] = None
    limit: Optional[int] = None


class ProductSearchResult(BaseModel):
    items: List[ProductSummary]
    total: Optional[int] = None


class KnowledgeSearchInput(BaseModel):
    query: str
    topK: Optional[int] = None
    documentTypes: Optional[List[KnowledgeDocumentType]] = None


class KnowledgeSearchResult(BaseModel):
    documents: List[KnowledgeDocument]


class GetOrderStatusInput(BaseModel):
    orderId: ID


class GetOrderStatusResult(BaseModel):
    order: OrderSummary


class GetDeliveryTrackingInput(BaseModel):
    orderId: ID


class GetDeliveryTrackingResult(BaseModel):
    tracking: DeliveryTracking


class SubmitOrderActionInput(BaseModel):
    orderId: ID
    actionType: OrderActionType
    reasonCode: OrderActionReason
    reasonText: Optional[str] = None
    itemIds: Optional[List[ID]] = None


class SubmitOrderActionResult(BaseModel):
    success: bool
    requestId: Optional[ID] = None
    status: OrderActionStatus
    message: str


class AdapterHealth(BaseModel):
    siteId: str
    ok: bool
    checkedAt: str


# Exceptions
class AdapterError(Exception):
    def __init__(
        self, code: str, message: str, details: Optional[Dict[str, Any]] = None
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message} - {self.details}")
