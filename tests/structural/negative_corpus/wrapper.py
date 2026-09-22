class Client:
    def request(self, url):
        return f"GET {url}"

class AuthenticatedClient:
    """Wraps a client to add a header. Encapsulation, not decoration."""
    def __init__(self, inner: Client, token: str):
        self._inner = inner
        self._token = token
    def request(self, url):
        return self._inner.request(url) + f" (token={self._token})"
