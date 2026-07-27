# db/base.py
# Importing these models ensures SQLModel registers their metadata before table creation
from app.models.user import User
from app.models.company import Company, PaymentAccount
from app.models.admin import Admin
from app.models.driver import Driver
from app.models.trip import Trip, Transaction, PaymentMethod, PaymentStatus, LedgerEntryType, CompanyLedger
from app.models.vehicle import Vehicle

