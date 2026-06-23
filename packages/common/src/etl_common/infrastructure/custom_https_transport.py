import http.client
import ssl
import xmlrpc.client
from typing import Any


class CustomHTTPSTransport(xmlrpc.client.SafeTransport):
    def __init__(
        self,
        use_https: bool = True,
        check_hostname: bool = False,
        verify_ssl: bool = False,
    ) -> None:
        super().__init__()
        self.use_https = use_https
        self.check_hostname = check_hostname
        self.verify_ssl = verify_ssl
        self._timeout = 300

    def make_connection(self, host: Any) -> http.client.HTTPSConnection:
        if not self.verify_ssl:
            context = ssl._create_unverified_context()
            context.check_hostname = self.check_hostname
            context.verify_mode = ssl.CERT_NONE
            return http.client.HTTPSConnection(
                host, context=context, timeout=self._timeout
            )
        return super().make_connection(host)
