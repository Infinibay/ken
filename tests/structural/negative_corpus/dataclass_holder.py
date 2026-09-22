class Money:
    def __init__(self, amount, currency):
        self.amount = amount
        self.currency = currency
    def get_amount(self): return self.amount
    def set_amount(self, value): self.amount = value
    def get_currency(self): return self.currency
    def format(self): return f"{self.amount} {self.currency}"
