"""SQLAlchemy models. Importing this package registers every table on Base."""

from app.models.analysis import Analysis, HSClassification
from app.models.base import (
    ALL_ENUMS,
    SENT_FAMILY_STATUSES,
    Base,
    BuyerSource,
    CampaignStatus,
    EmailStatus,
    SenderProviderType,
    SenderVerificationStatus,
    SuppressionReason,
    UserRole,
    VerificationStatus,
    utcnow,
)
from app.models.buyer import Buyer, Contact, ProductBuyerMatch
from app.models.campaign import Campaign, LIARecord
from app.models.compliance import AuditLog, SuppressionEntry
from app.models.email import APPROVAL_CHECK_SQL, Email
from app.models.factory import Factory
from app.models.market import Market, MarketSnapshot
from app.models.product import EMBEDDING_DIM, HSCode, HSCorrection, Product
from app.models.sender_account import Notification, SenderAccount
from app.models.shipment import Shipment
from app.models.user import User
from app.models.world_trade import WorldTrade

__all__ = [
    "ALL_ENUMS",
    "APPROVAL_CHECK_SQL",
    "EMBEDDING_DIM",
    "SENT_FAMILY_STATUSES",
    "Analysis",
    "AuditLog",
    "Base",
    "Buyer",
    "BuyerSource",
    "Campaign",
    "CampaignStatus",
    "Contact",
    "Email",
    "EmailStatus",
    "Factory",
    "HSClassification",
    "HSCode",
    "HSCorrection",
    "LIARecord",
    "Market",
    "MarketSnapshot",
    "Notification",
    "Product",
    "ProductBuyerMatch",
    "SenderAccount",
    "SenderProviderType",
    "SenderVerificationStatus",
    "Shipment",
    "SuppressionEntry",
    "SuppressionReason",
    "User",
    "UserRole",
    "VerificationStatus",
    "WorldTrade",
    "utcnow",
]
