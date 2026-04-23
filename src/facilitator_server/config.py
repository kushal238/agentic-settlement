import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

FACILITATOR_PORT: int = int(os.getenv("FACILITATOR_PORT", "8001"))
BFT_F: int = int(os.getenv("BFT_F", "1"))
PER_VALIDATOR_TIMEOUT_S: float = float(os.getenv("PER_VALIDATOR_TIMEOUT_S", "2.0"))
GENESIS_ACCOUNTS_PATH: str | None = os.getenv("GENESIS_ACCOUNTS_PATH")
