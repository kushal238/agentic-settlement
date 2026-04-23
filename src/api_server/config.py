import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_PORT: int = int(os.getenv("API_PORT", "8000"))
FACILITATOR_URL: str = os.getenv("FACILITATOR_URL", "http://localhost:8001")
FACILITATOR_TIMEOUT_S: float = float(os.getenv("FACILITATOR_TIMEOUT_S", "10.0"))
PAYMENT_RECIPIENT: str = os.getenv("PAYMENT_RECIPIENT", "server-recipient")
PAYMENT_AMOUNT: int = int(os.getenv("PAYMENT_AMOUNT", "10"))
