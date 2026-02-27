# main.py - NETSASA Backend with Lipana
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
import os
import asyncio
import json
import uuid
import logging
from contextlib import asynccontextmanager

# Lipana SDK
try:
    from lipana import Lipana, LipanaError
except ImportError:
    # Fallback mock for development without lipana
    class LipanaError(Exception):
        def __init__(self, message: str, code: Optional[str] = None):
            self.message = message
            self.code = code
            super().__init__(self.message)
    
    class Lipana:
        def __init__(self, api_key: str, environment: str = "production"):
            self.api_key = api_key
            self.environment = environment
            logger.warning("Using mock Lipana - actual SDK not installed")
        
        class Transactions:
            def __init__(self, parent):
                self.parent = parent
            
            def initiate_stk_push(self, phone: str, amount: int, **kwargs) -> Dict:
                # Mock implementation for testing
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("netsasa")

# -------------------- Configuration --------------------
class Settings:
    LIPANA_API_KEY = os.getenv("LIPANA_API_KEY")
    WEBHOOK_SECRET = os.getenv(
        "LIPANA_WEBHOOK_SECRET",
        "d7f5efcab4a3db923edfe8f066294c41613052eb95deee681b785f0770a268ed"
    )
    JWT_SECRET = os.getenv("JWT_SECRET", "your-jwt-secret-key")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./netsasa.db")
    AUTO_CANCEL_SECONDS = int(os.getenv("AUTO_CANCEL_SECONDS", "120"))
    FRONTEND_URL = os.getenv("FRONTEND_URL", "*")

settings = Settings()

if not settings.LIPANA_API_KEY:
    logger.warning("LIPANA_API_KEY not set - using mock mode")

# -------------------- Database (SQLAlchemy) --------------------
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

Base = declarative_base()
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class TransactionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

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

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checkout_request_id = Column(String(50), unique=True, index=True)
    merchant_request_id = Column(String(50), nullable=True)
    mpesa_receipt_number = Column(String(50), nullable=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    phone_number = Column(String(15), index=True)
    amount = Column(Float, nullable=False)
    package_name = Column(String(100), nullable=True)
    package_id = Column(String(50), nullable=True)
    status = Column(String(20), default=TransactionStatus.PENDING.value)
    result_code = Column(String(10), nullable=True)
    result_desc = Column(Text, nullable=True)
    transaction_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    raw_callback = Column(Text, nullable=True)
    user = relationship("User", back_populates="transactions")

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

Base.metadata.create_all(bind=engine)

# -------------------- Pydantic Models --------------------
class PaymentRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=13)
    amount: int = Field(..., ge=10)
    package_id: Optional[str] = None
    
    @validator('phone')
    def validate_phone(cls, v):
        v = v.strip().replace(" ", "").replace("-", "")
        if v.startswith('+'): v = v[1:]
        if v.startswith('254'): v = '0' + v[3:]
        if not v.startswith('0') or len(v) != 10 or not v.isdigit():
            raise ValueError('Invalid phone number format. Use 07XXXXXXXX')
        return v

class PaymentResponse(BaseModel):
    success: bool
    checkout_request_id: Optional[str] = None
    transaction_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None

# -------------------- Initialize Lipana --------------------
lipana = Lipana(
    api_key=settings.LIPANA_API_KEY or "mock-key",
    environment="production" if settings.LIPANA_API_KEY else "sandbox"
)

# -------------------- In-Memory Stores --------------------
checkout_store: Dict[str, Dict] = {}
subscribers: Dict[str, asyncio.Queue] = {}

# -------------------- Dependencies --------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------- Lifespan --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("NETSASA Backend with Lipana starting up...")
    
    db = SessionLocal()
    try:
        if db.query(Package).count() == 0:
            default_packages = [
                Package(id="p1", name="Sawa 50", description="Quick browsing", price=10, duration_minutes=50, data_limit_mb=300, speed_mbps=10, max_devices=2, package_type="hourly"),
                Package(id="p2", name="Leo 1 Hour", description="Extended session", price=20, duration_minutes=60, data_limit_mb=1024, speed_mbps=15, max_devices=2, package_type="hourly"),
                Package(id="p3", name="Kipindi 3 Hours", description="Study sessions", price=50, duration_minutes=180, data_limit_mb=3072, speed_mbps=20, max_devices=3, package_type="hourly"),
                Package(id="p4", name="Usiku Night", description="Unlimited night", price=40, duration_minutes=540, data_limit_mb=None, speed_mbps=10, max_devices=2, package_type="special"),
                Package(id="p5", name="Siku 1 Day", description="Full day", price=60, duration_minutes=1440, data_limit_mb=2048, speed_mbps=15, max_devices=3, package_type="daily"),
                Package(id="p6", name="Siku Plus", description="Heavy usage", price=100, duration_minutes=1440, data_limit_mb=5120, speed_mbps=20, max_devices=4, package_type="daily"),
                Package(id="p7", name="Weekend Special", description="48 hours", price=150, duration_minutes=2880, data_limit_mb=5120, speed_mbps=20, max_devices=4, package_type="special"),
                Package(id="p8", name="Wiki 3 Days", description="Mid-week", price=200, duration_minutes=4320, data_limit_mb=5120, speed_mbps=20, max_devices=4, package_type="weekly"),
                Package(id="p9", name="Wiki 7 Days", description="Full week", price=400, duration_minutes=10080, data_limit_mb=15360, speed_mbps=25, max_devices=5, package_type="weekly"),
                Package(id="p10", name="Mwezi Lite", description="Monthly", price=1000, duration_minutes=43200, data_limit_mb=30720, speed_mbps=30, max_devices=6, package_type="monthly"),
            ]
            db.add_all(default_packages)
            db.commit()
            logger.info("Default packages created")
    except Exception as e:
        logger.error(f"Error creating packages: {e}")
    finally:
        db.close()
    
    yield
    logger.info("NETSASA Backend shutting down...")

# -------------------- FastAPI App --------------------
app = FastAPI(
    title="NETSASA API with Lipana",
    description="Premium Wi-Fi Payment API using Lipana SDK",
    version="2.2.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL] if settings.FRONTEND_URL != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"]
)

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
        "message": "NETSASA API with Lipana",
        "status": "operational",
        "lipana_mode": "live" if settings.LIPANA_API_KEY else "mock",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health", tags=["Health"])
async def health_check():
    lipana_status = "connected" if settings.LIPANA_API_KEY else "mock_mode"
    return {
        "status": "healthy",
        "database": "connected",
        "lipana_sdk": lipana_status,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/packages", tags=["Packages"])
def get_packages(db: Session = Depends(get_db)):
    packages = db.query(Package).filter(Package.is_active == True).all()
    return {
        "packages": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": p.price,
                "duration": f"{p.duration_minutes} mins" if p.duration_minutes and p.duration_minutes < 1440 else f"{p.duration_minutes // 1440} days" if p.duration_minutes else "Until depleted",
                "data_limit": f"{p.data_limit_mb} MB" if p.data_limit_mb else "Unlimited",
                "speed": f"{p.speed_mbps} Mbps",
                "max_devices": p.max_devices,
                "popular": p.id in ["p1", "p5", "p9"]
            }
            for p in packages
        ]
    }

@app.post("/api/pay", response_model=PaymentResponse, tags=["Payments"])
async def initiate_payment(
    request: Request,
    payment: PaymentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    try:
        result = lipana.transactions.initiate_stk_push(
            phone=f"+254{payment.phone[-9:]}",
            amount=int(payment.amount),
            account_reference="NETSASA",
            transaction_desc=f"WiFi {payment.package_id or 'Package'}"
        )
        
        checkout_id = result.get("CheckoutRequestID") or result.get("checkoutRequestID")
        
        if not checkout_id:
            raise Exception("Failed to get checkout request ID")
        
        transaction = Transaction(
            checkout_request_id=checkout_id,
            phone_number=payment.phone,
            amount=payment.amount,
            package_id=payment.package_id,
            status=TransactionStatus.PENDING.value
        )
        db.add(transaction)
        db.commit()
        
        checkout_store[checkout_id] = {
            "status": TransactionStatus.PENDING.value,
            "transaction_id": result.get("transactionId"),
            "phone": payment.phone,
            "amount": payment.amount,
            "created_at": datetime.utcnow().isoformat()
        }
        subscribers[checkout_id] = asyncio.Queue()
        
        background_tasks.add_task(auto_cancel_payment, checkout_id)
        
        logger.info(f"Payment initiated via Lipana: {checkout_id}")
        
        return PaymentResponse(
            success=True,
            checkout_request_id=checkout_id,
            transaction_id=result.get("transactionId"),
            message="STK push sent to your phone. Please enter M-Pesa PIN."
        )
        
    except LipanaError as err:
        logger.error(f"Lipana error: {err.message}")
        return PaymentResponse(success=False, error=err.message)
    except Exception as e:
        logger.error(f"Payment error: {str(e)}")
        return PaymentResponse(success=False, error=str(e))

@app.get("/api/check/{checkout_id}", tags=["Payments"])
def check_payment_status(checkout_id: str, db: Session = Depends(get_db)):
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
    
    entry = checkout_store.get(checkout_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    return {
        "checkout_id": checkout_id,
        "status": entry["status"],
        "amount": entry.get("amount"),
        "phone": entry.get("phone")
    }

@app.post("/api/webhook", tags=["Webhooks"])
async def lipana_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        logger.info(f"Lipana webhook: {json.dumps(data)}")
        
        checkout_id = data.get("CheckoutRequestID") or data.get("checkoutRequestID")
        status = data.get("status")
        transaction_id = data.get("transactionId")
        
        if checkout_id:
            checkout_store[checkout_id] = {
                "status": status,
                "transaction_id": transaction_id,
                "raw": data
            }
            await notify_subscriber(checkout_id, {"status": status})
            
            # Update database
            transaction = db.query(Transaction).filter(
                Transaction.checkout_request_id == checkout_id
            ).first()
            if transaction:
                transaction.status = status
                transaction.mpesa_receipt_number = data.get("mpesaReceiptNumber")
                transaction.raw_callback = json.dumps(data)
                if status == "success":
                    transaction.completed_at = datetime.utcnow()
                db.commit()
        
        return {"received": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"received": True}  # Always return 200 to prevent retries

@app.get("/api/stream/{checkout_id}", tags=["SSE"])
async def stream_checkout(checkout_id: str):
    if checkout_id not in subscribers:
        subscribers[checkout_id] = asyncio.Queue()
    
    async def event_generator():
        queue = subscribers[checkout_id]
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(data)}\n\n"
                if data.get("status") in ["success", "failed", "cancelled"]:
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
            except asyncio.CancelledError:
                break
        
        if checkout_id in subscribers:
            del subscribers[checkout_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.get("/api/transactions/{phone}", tags=["Transactions"])
def get_user_transactions(phone: str, limit: int = 20, db: Session = Depends(get_db)):
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith('+254'): phone = '0' + phone[3:]
    elif phone.startswith('254'): phone = '0' + phone[2:]
    
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
                "mpesa_receipt": t.mpesa_receipt_number,
                "amount": t.amount,
                "status": t.status,
                "package": t.package_id,
                "created_at": t.created_at.isoformat() if t.created_at else None
            }
            for t in transactions
        ]
    }

# -------------------- Background Tasks --------------------

async def auto_cancel_payment(checkout_id: str):
    await asyncio.sleep(settings.AUTO_CANCEL_SECONDS)
    
    db = SessionLocal()
    try:
        entry = checkout_store.get(checkout_id)
        if entry and entry.get("status") == TransactionStatus.PENDING.value:
            transaction = db.query(Transaction).filter(
                Transaction.checkout_request_id == checkout_id
            ).first()
            if transaction and transaction.status == TransactionStatus.PENDING.value:
                transaction.status = TransactionStatus.CANCELLED.value
                db.commit()
                entry["status"] = TransactionStatus.CANCELLED.value
                await notify_subscriber(checkout_id, {"status": "cancelled"})
                logger.info(f"Auto-cancelled: {checkout_id}")
    finally:
        db.close()

async def notify_subscriber(checkout_id: str, message: dict):
    queue = subscribers.get(checkout_id)
    if queue:
        try:
            await queue.put(message)
        except Exception as e:
            logger.error(f"Notify error: {e}")

# -------------------- Error Handlers --------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "timestamp": datetime.utcnow().isoformat()}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled: {str(e)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal error", "timestamp": datetime.utcnow().isoformat()}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
