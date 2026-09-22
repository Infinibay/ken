class Ticket:
    def __init__(self):
        self.status = "new"
    def advance(self, action):
        if self.status == "new" and action == "open":
            self.status = "open"
        elif self.status == "open" and action == "close":
            self.status = "closed"
        elif self.status == "closed":
            self.status = "new"
        return self.status
