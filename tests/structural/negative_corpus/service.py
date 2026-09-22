from typing import Protocol
class Repo(Protocol):
    def save(self, x): ...
class Mailer(Protocol):
    def send(self, x): ...
class OrderService:
    def __init__(self, repo: Repo, mailer: Mailer) -> None:
        self._repo = repo
        self._mailer = mailer
    def place(self, order):
        self._repo.save(order)
        self._mailer.send(order)
        return order
