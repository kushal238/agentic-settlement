"""Account state store -- each validator holds its own independent instance."""

from dataclasses import dataclass, field
from nacl.signing import VerifyKey


@dataclass
class Account:
    owner: VerifyKey
    balance: int
    nonce: int = 0


class AccountStateStore:
    """Tracks account state for a single validator. No shared state across validators."""

    def __init__(self):
        self._accounts: dict[str, Account] = {}

    def create_account(self, account_id: str, owner: VerifyKey, balance: int) -> None:
        self._accounts[account_id] = Account(owner=owner, balance=balance)

    def get_account(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    def get_balance(self, account_id: str) -> int:
        account = self.get_account(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        return account.balance

    def get_nonce(self, account_id: str) -> int:
        account = self.get_account(account_id)
        if account is None:
            raise KeyError(f"Account {account_id} not found")
        return account.nonce
