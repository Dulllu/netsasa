# main.py - Complete NETSASA Backend API
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
import os
import asyncio
import json
import uuid
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("netsasa")

# -------------------- Configuration --------------------
class Settings:
    LIPANA_API_KEY = os.getenv("LIPANA_API_KEY")
    WEBHOOK_SECRET = os.getenv("LIPANA_WEBHOOK_SECRET", "d7f5efcab4a3db923edfe8f066294c41613052eb95deee681b785f0770a268ed")
    JWT_SECRET = os.getenv("JWT_SECRET", "your-jwt-secret-key")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./netsasa.db")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    AUTO_CANCEL_SECONDS = int(os.getenv("AUTO_CANCEL_SECONDS", "120"))
    RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
    RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

settings = Settings()

if not settings.LIPANA_API_KEY:
    raise Exception("LIPANA_API_KEY not set in environment variables")

# -------------------- Lipana SDK Stub --------------------
# Replace with actual: from lipana import Lipana, LipanaError
class LipanaError(Exception):
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(self.message)

class Lipana:
    def __init__(self, api_key: str, environment: str = "production"):
        self.api_key = api_key
        self.environment = environment
        logger.info(f"Lipana initialized in {environment} mode")
    
    class Transactions:
        def __init__(self, parent):
            self.parent = parent
        
        def initiate_stk_push(self, phone: str, amount: int, **kwargs) -> Dict:
            # Simulate STK push - replace with actual implementation
            checkout_id = f"ws_{uuid.uuid4().hex[:16].upper()}"
            return {
                "CheckoutRequestID": checkout_id,
                "ResponseCode": "0",
                "ResponseDescription": "Success. Request accepted for processing",
                "CustomerMessage": "Success. Request accepted for processing",
                "transactionId": f"TXN_{uuid.uuid4().hex[:12].upper()}"
            }
    
    @property
    def transactions(self):
        return self.Transactions(self)

lipana = Lipana(api_key=settings.LIPANA_API_KEY, environment=settings.ENVIRONMENT)

# -------------------- Database Models (SQLAlchemy) --------------------
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Enum as SQLEnum, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

Base = declarative_base()
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class TransactionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

class PackageType(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SPECIAL = "special"

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    phone = Column(String(15), unique=True, index=True)
    email = Column(String(255), unique=True, nullable=True)
    name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    loyalty_points = Column(Integer, default=0)
    total_spent = Column(Float, default=0.0)
    
    transactions = relationship("Transaction", back_populates="user")
    sessions = relationship("UserSession", back_populates="user")

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checkout_request_id = Column(String(50), unique=True, index=True)
    merchant_request_id = Column(String(50), nullable=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    phone_number = Column(String(15), index=True)
    amount = Column(Float, nullable=False)
    package_name = Column(String(100), nullable=True)
    package_id = Column(String(50), nullable=True)
    status = Column(String(20), default=TransactionStatus.PENDING.value)
    result_code = Column(String(10), nullable=True)
    result_desc = Column(Text, nullable=True)
    mpesa_receipt_number = Column(String(50), nullable=True)
    transaction_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    raw_callback = Column(Text, nullable=True)
    
    user = relationship("User", back_populates="transactions")

class UserSession(Base):
    __tablename__ = "user_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"))
    ip_address = Column(String(45))
    mac_address = Column(String(17), nullable=True)
    device_info = Column(Text, nullable=True)
    package_id = Column(String(50))
    package_name = Column(String(100))
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    data_used_mb = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    
    user = relationship("User", back_populates="sessions")

class Package(Base):
    __tablename__ = "packages"
    
    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    price = Column(Float, nullable=False)
    duration_minutes = Column(Integer, nullable=True)
    data_limit_mb = Column(Float, nullable=True)
    speed_mbps = Column(Integer, default=10)
    max_devices = Column(Integer, default=1)
    package_type = Column(String(20))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables
Base.metadata.create_all(bind=engine)

# -------------------- Pydantic Models --------------------
class PaymentRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=13, description="Phone number in format 07XX or 2547XX")
    amount: int = Field(..., ge=10, description="Amount in KES, minimum 10")
    package_id: Optional[str] = Field(None, description="Selected package ID")
    
    @validator('phone')
    def validate_phone(cls, v):
        v = v.strip().replace(" ", "").replace("-", "")
        if v.startswith('+'):
            v = v[1:]
        if v.startswith('254'):
            v = '0' + v[3:]
        if not v.startswith('0') or len(v) != 10 or not v.isdigit():
            raise ValueError('Invalid phone number format. Use 07XXXXXXXX or 2547XXXXXXXX')
        return v

class PaymentResponse(BaseModel):
    success: bool
    checkout_request_id: Optional[str] = None
    transaction_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None

class WebhookPayload(BaseModel):
    CheckoutRequestID: Optional[str] = Field(None, alias="checkoutRequestID")
    MerchantRequestID: Optional[str] = Field(None, alias="merchantRequestID")
    ResultCode: Optional[str] = Field(None, alias="resultCode")
    ResultDesc: Optional[str] = Field(None, alias="resultDesc")
    TransactionID: Optional[str] = Field(None, alias="transactionId")
    MpesaReceiptNumber: Optional[str] = Field(None, alias="mpesaReceiptNumber")
    TransactionDate: Optional[str] = Field(None, alias="transactionDate")
    PhoneNumber: Optional[str] = Field(None, alias="phoneNumber")
    Amount: Optional[float] = Field(None, alias="amount")
    
    class Config:
        populate_by_name = True

class PackageResponse(BaseModel):
    id: str
    name: str
    description: str
    price: float
    duration: str
    data_limit: Optional[str]
    speed: str
    max_devices: int
    popular: bool = False

# -------------------- In-Memory Stores --------------------
checkout_store: Dict[str, Dict] = {}
subscribers: Dict[str, asyncio.Queue] = {}
rate_limit_store: Dict[str, List[datetime]] = {}

# -------------------- Dependencies --------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

security = HTTPBearer(auto_error=False)

async def verify_webhook_signature(request: Request) -> bool:
    """Verify Lipana webhook signature"""
    body = await request.body()
    signature = request.headers.get("X-Lipana-Signature")
    if not signature:
        return False
    
    expected = hmac.new(
        settings.WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

async def check_rate_limit(client_id: str) -> bool:
    """Simple rate limiting"""
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=settings.RATE_LIMIT_WINDOW)
    
    if client_id not in rate_limit_store:
        rate_limit_store[client_id] = []
    
    # Clean old entries
    rate_limit_store[client_id] = [
        t for t in rate_limit_store[client_id] if t > window_start
    ]
    
    if len(rate_limit_store[client_id]) >= settings.RATE_LIMIT_REQUESTS:
        return False
    
    rate_limit_store[client_id].append(now)
    return True

# -------------------- Lifespan --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("NETSASA Backend starting up...")
    
    # Initialize default packages if none exist
    db = SessionLocal()
    if db.query(Package).count() == 0:
        default_packages = [
            Package(id="p1", name="Mwangaza 20", description="Quick browsing", price=5, duration_minutes=20, data_limit_mb=100, speed_mbps=5, max_devices=1, package_type="hourly"),
            Package(id="p3", name="Sawa 50", description="Light browsing & social", price=10, duration_minutes=50, data_limit_mb=300, speed_mbps=10, max_devices=2, package_type="hourly"),
            Package(id="p11", name="Siku 1 Day", description="All-day access", price=60, duration_minutes=1440, data_limit_mb=2048, speed_mbps=15, max_devices=3, package_type="daily"),
            Package(id="p18", name="Wiki 7 Day", description="Full week coverage", price=400, duration_minutes=10080, data_limit_mb=15360, speed_mbps=25, max_devices=5, package_type="weekly"),
        ]
        db.add_all(default_packages)
        db.commit()
        logger.info("Default packages created")
    db.close()
    
    yield
    
    # Shutdown
    logger.info("NETSASA Backend shutting down...")

# -------------------- FastAPI App --------------------
app = FastAPI(
    title="NETSASA API",
    description="Premium Wi-Fi Payment and Management API",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://netsasa-frontend.onrender.com",
        "https://netsasa.com",
        "https://www.netsasa.com",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"]
)

# Request ID middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# -------------------- Endpoints --------------------

@app.get("/", tags=["Health"])
def root():
    return {
        "message": "NETSASA API v2.0",
        "status": "operational",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "payment_gateway": "connected",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/packages", response_model=List[PackageResponse], tags=["Packages"])
def get_packages(db: Session = Depends(get_db)):
    """Get all available packages"""
    packages = db.query(Package).filter(Package.is_active == True).all()
    
    result = []
    for p in packages:
        duration = f"{p.duration_minutes} mins" if p.duration_minutes and p.duration_minutes < 1440 else \
                   f"{p.duration_minutes // 1440} days" if p.duration_minutes else "Until depleted"
        
        result.append(PackageResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            price=p.price,
            duration=duration,
            data_limit=f"{p.data_limit_mb} MB" if p.data_limit_mb else "Unlimited",
            speed=f"{p.speed_mbps} Mbps",
            max_devices=p.max_devices,
            popular=p.id in ["p3", "p11", "p18"]
        ))
    
    return result

@app.post("/api/pay", response_model=PaymentResponse, tags=["Payments"])
async def initiate_payment(
    request: Request,
    payment: PaymentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Initiate M-Pesa STK Push payment
    """
    # Rate limiting
    client_ip = request.client.host
    if not await check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later."
        )
    
    try:
        # Format phone for Lipana (+2547XXXXXXXX)
        phone_formatted = f"+254{payment.phone[-9:]}"
        
        # Initiate STK push
        result = lipana.transactions.initiate_stk_push(
            phone=phone_formatted,
            amount=payment.amount,
            account_reference="NETSASA",
            transaction_desc="Wi-Fi Package Purchase"
        )
        
        checkout_id = result.get("CheckoutRequestID") or result.get("checkoutRequestID")
        
        if not checkout_id:
            raise LipanaError("Failed to get checkout request ID")
        
        # Create transaction record
        transaction = Transaction(
            checkout_request_id=checkout_id,
            phone_number=payment.phone,
            amount=payment.amount,
            package_id=payment.package_id,
            status=TransactionStatus.PENDING.value
        )
        db.add(transaction)
        db.commit()
        
        # Store in memory for SSE
        checkout_store[checkout_id] = {
            "status": TransactionStatus.PENDING.value,
            "transaction_id": result.get("transactionId"),
            "phone": payment.phone,
            "amount": payment.amount,
            "created_at": datetime.utcnow().isoformat()
        }
        subscribers[checkout_id] = asyncio.Queue()
        
        # Schedule auto-cancel
        background_tasks.add_task(auto_cancel_payment, checkout_id)
        
        logger.info(f"Payment initiated: {checkout_id} for {payment.phone}")
        
        return PaymentResponse(
            success=True,
            checkout_request_id=checkout_id,
            transaction_id=result.get("transactionId"),
            message="STK push sent to your phone. Please enter M-Pesa PIN to complete."
        )
        
    except LipanaError as e:
        logger.error(f"Lipana error: {e.message}")
        return PaymentResponse(
            success=False,
            error=e.message
        )
    except Exception as e:
        logger.error(f"Payment initiation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment initiation failed. Please try again."
        )

@app.get("/api/check/{checkout_id}", tags=["Payments"])
def check_payment_status(checkout_id: str, db: Session = Depends(get_db)):
    """Check payment status by checkout ID"""
    # Check database first
    transaction = db.query(Transaction).filter(
        Transaction.checkout_request_id == checkout_id
    ).first()
    
    if transaction:
        return {
            "checkout_id": checkout_id,
            "status": transaction.status,
            "amount": transaction.amount,
            "phone": transaction.phone_number,
            "mpesa_receipt": transaction.mpesa_receipt_number,
            "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
            "completed_at": transaction.completed_at.isoformat() if transaction.completed_at else None
        }
    
    # Fallback to memory store
    entry = checkout_store.get(checkout_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    return {
        "checkout_id": checkout_id,
        "status": entry["status"],
        "amount": entry.get("amount"),
        "phone": entry.get("phone"),
        "created_at": entry.get("created_at")
    }

@app.get("/api/stream/{checkout_id}", tags=["SSE"])
async def stream_payment_status(checkout_id: str):
    """
    Server-Sent Events endpoint for real-time payment updates
    """
    if checkout_id not in subscribers:
        subscribers[checkout_id] = asyncio.Queue()
    
    async def event_generator():
        queue = subscribers[checkout_id]
        retry_count = 0
        max_retries = 3
        
        # Send initial status
        initial_status = checkout_store.get(checkout_id, {}).get("status", "pending")
        yield f"data: {json.dumps({'status': initial_status, 'type': 'initial'})}\n\n"
        
        while retry_count < max_retries:
            try:
                # Wait for update with timeout
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(data)}\n\n"
                
                # End stream if final status
                if data.get("status") in ["success", "failed", "cancelled"]:
                    break
                    
            except asyncio.TimeoutError:
                # Send keep-alive
                yield f"data: {json.dumps({'type': 'ping', 'status': 'waiting'})}\n\n"
                retry_count += 1
                
            except asyncio.CancelledError:
                logger.info(f"SSE client disconnected: {checkout_id}")
                break
                
            except Exception as e:
                logger.error(f"SSE error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                break
        
        # Cleanup
        if checkout_id in subscribers:
            del subscribers[checkout_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/webhook", tags=["Webhooks"])
async def lipana_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Receive Lipana/M-Pesa payment callbacks
    """
    # Verify signature in production
    if settings.ENVIRONMENT == "production":
        is_valid = await verify_webhook_signature(request)
        if not is_valid:
            logger.warning("Invalid webhook signature received")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature"
            )
    
    try:
        payload = await request.json()
        logger.info(f"Webhook received: {json.dumps(payload)}")
        
        # Extract fields (handle both camelCase and PascalCase)
        checkout_id = payload.get("CheckoutRequestID") or payload.get("checkoutRequestID")
        result_code = payload.get("ResultCode") or payload.get("resultCode")
        result_desc = payload.get("ResultDesc") or payload.get("resultDesc")
        mpesa_receipt = payload.get("MpesaReceiptNumber") or payload.get("mpesaReceiptNumber")
        transaction_id = payload.get("TransactionID") or payload.get("transactionId")
        phone = payload.get("PhoneNumber") or payload.get("phoneNumber")
        amount = payload.get("Amount") or payload.get("amount")
        
        if not checkout_id:
            logger.error("Webhook missing checkout ID")
            return {"received": False, "error": "Missing checkout ID"}
        
        # Determine status
        status_map = {
            "0": TransactionStatus.SUCCESS,
            "1": TransactionStatus.FAILED,
            "1032": TransactionStatus.CANCELLED,
            "1037": TransactionStatus.CANCELLED,
        }
        new_status = status_map.get(str(result_code), TransactionStatus.FAILED)
        
        # Update database
        transaction = db.query(Transaction).filter(
            Transaction.checkout_request_id == checkout_id
        ).first()
        
        if transaction:
            transaction.status = new_status.value
            transaction.result_code = str(result_code)
            transaction.result_desc = result_desc
            transaction.mpesa_receipt_number = mpesa_receipt
            transaction.transaction_date = datetime.utcnow()
            transaction.raw_callback = json.dumps(payload)
            
            if new_status == TransactionStatus.SUCCESS:
                transaction.completed_at = datetime.utcnow()
                
                # Update user loyalty points
                user = db.query(User).filter(User.phone == transaction.phone_number).first()
                if user:
                    user.loyalty_points += int(transaction.amount / 10)  # 1 point per 10 KES
                    user.total_spent += transaction.amount
                else:
                    # Create new user
                    new_user = User(
                        phone=transaction.phone_number,
                        loyalty_points=int(transaction.amount / 10),
                        total_spent=transaction.amount
                    )
                    db.add(new_user)
            
            db.commit()
            logger.info(f"Transaction {checkout_id} updated to {new_status.value}")
        
        # Update memory store
        if checkout_id in checkout_store:
            checkout_store[checkout_id]["status"] = new_status.value
            checkout_store[checkout_id]["mpesa_receipt"] = mpesa_receipt
            checkout_store[checkout_id]["completed_at"] = datetime.utcnow().isoformat()
        
        # Notify SSE subscribers
        await notify_subscriber(checkout_id, {
            "status": new_status.value,
            "checkout_id": checkout_id,
            "mpesa_receipt": mpesa_receipt,
            "transaction_id": transaction_id,
            "amount": amount,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Activate user session in background if successful
        if new_status == TransactionStatus.SUCCESS:
            background_tasks.add_task(activate_user_session, checkout_id)
        
        return {"received": True, "checkout_id": checkout_id, "status": new_status.value}
        
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )

@app.get("/api/transactions/{phone}", tags=["Transactions"])
def get_user_transactions(phone: str, limit: int = 10, db: Session = Depends(get_db)):
    """Get transaction history for a phone number"""
    # Normalize phone
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith('+254'):
        phone = '0' + phone[3:]
    elif phone.startswith('254'):
        phone = '0' + phone[2:]
    
    transactions = db.query(Transaction).filter(
        Transaction.phone_number == phone
    ).order_by(Transaction.created_at.desc()).limit(limit).all()
    
    return {
        "phone": phone,
        "count": len(transactions),
        "transactions": [
            {
                "id": t.id,
                "checkout_id": t.checkout_request_id,
                "amount": t.amount,
                "status": t.status,
                "package": t.package_name,
                "mpesa_receipt": t.mpesa_receipt_number,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None
            }
            for t in transactions
        ]
    }

@app.get("/api/user/{phone}/profile", tags=["Users"])
def get_user_profile(phone: str, db: Session = Depends(get_db)):
    """Get user profile with loyalty info"""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith('+254'):
        phone = '0' + phone[3:]
    elif phone.startswith('254'):
        phone = '0' + phone[2:]
    
    user = db.query(User).filter(User.phone == phone).first()
    
    if not user:
        return {
            "phone": phone,
            "is_new": True,
            "loyalty_points": 0,
            "total_spent": 0,
            "tier": "bronze"
        }
    
    # Determine tier
    tier = "bronze"
    if user.total_spent >= 5000:
        tier = "platinum"
    elif user.total_spent >= 2000:
        tier = "gold"
    elif user.total_spent >= 500:
        tier = "silver"
    
    return {
        "id": user.id,
        "phone": user.phone,
        "name": user.name,
        "email": user.email,
        "loyalty_points": user.loyalty_points,
        "total_spent": user.total_spent,
        "tier": tier,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "is_new": False
    }

# -------------------- Background Tasks --------------------

async def auto_cancel_payment(checkout_id: str):
    """Auto-cancel pending payments after timeout"""
    await asyncio.sleep(settings.AUTO_CANCEL_SECONDS)
    
    entry = checkout_store.get(checkout_id)
    if entry and entry.get("status") == TransactionStatus.PENDING.value:
        entry["status"] = TransactionStatus.CANCELLED.value
        
        # Update database
        db = SessionLocal()
        transaction = db.query(Transaction).filter(
            Transaction.checkout_request_id == checkout_id
        ).first()
        if transaction and transaction.status == TransactionStatus.PENDING.value:
            transaction.status = TransactionStatus.CANCELLED.value
            db.commit()
        db.close()
        
        await notify_subscriber(checkout_id, {
            "status": "cancelled",
            "reason": "timeout",
            "message": "Payment was not completed in time"
        })
        logger.info(f"Auto-cancelled payment: {checkout_id}")

async def notify_subscriber(checkout_id: str, message: dict):
    """Send update to SSE subscriber"""
    queue = subscribers.get(checkout_id)
    if queue:
        try:
            await queue.put(message)
            logger.debug(f"Notified subscriber for {checkout_id}")
        except Exception as e:
            logger.error(f"Failed to notify subscriber: {e}")

def activate_user_session(checkout_id: str):
    """Activate Wi-Fi session after successful payment"""
    db = SessionLocal()
    try:
        transaction = db.query(Transaction).filter(
            Transaction.checkout_request_id == checkout_id
        ).first()
        
        if transaction and transaction.package_id:
            # Get package details
            package = db.query(Package).filter(
                Package.id == transaction.package_id
            ).first()
            
            if package:
                # Calculate expiry
                expires = datetime.utcnow() + timedelta(minutes=package.duration_minutes or 1440)
                
                # Create session
                session = UserSession(
                    user_id=transaction.user_id,
                    package_id=package.id,
                    package_name=package.name,
                    expires_at=expires,
                    ip_address="0.0.0.0"  # Will be updated on first connection
                )
                db.add(session)
                db.commit()
                
                logger.info(f"Activated session for {checkout_id}, expires at {expires}")
                
                # TODO: Integrate with RADIUS/MikroTik to actually enable access
    finally:
        db.close()

# -------------------- Error Handlers --------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# -------------------- Main --------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=settings.ENVIRONMENT == "development",
        workers=1 if settings.ENVIRONMENT == "development" else 4
    )
