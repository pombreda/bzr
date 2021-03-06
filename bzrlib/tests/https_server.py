# Copyright (C) 2007-2011 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""HTTPS test server, available when ssl python module is available"""

import ssl
import sys

from bzrlib.tests import (
    http_server,
    ssl_certs,
    test_server,
    )


class TestingHTTPSServerMixin:

    def __init__(self, key_file, cert_file):
        self.key_file = key_file
        self.cert_file = cert_file

    def _get_ssl_request (self, sock, addr):
        """Wrap the socket with SSL"""
        ssl_sock = ssl.wrap_socket(sock, server_side=True,
                                   keyfile=self.key_file,
                                   certfile=self.cert_file,
                                   do_handshake_on_connect=False)
        return ssl_sock, addr

    def verify_request(self, request, client_address):
        """Verify the request.

        Return True if we should proceed with this request, False if we should
        not even touch a single byte in the socket !
        """
        serving = test_server.TestingTCPServerMixin.verify_request(
            self, request, client_address)
        if serving:
            try:
                request.do_handshake()
            except ssl.SSLError, e:
                # FIXME: We proabaly want more tests to capture which ssl
                # errors are worth reporting but mostly our tests want an https
                # server that works -- vila 2012-01-19
                return False
        return serving

    def ignored_exceptions_during_shutdown(self, e):
        if (sys.version < (2, 7) and isinstance(e, TypeError)
            and e.args[0] == "'member_descriptor' object is not callable"):
            # Fixed in python-2.7 (and some Ubuntu 2.6) there is a bug where
            # the ssl socket fail to raise a socket.error when trying to read
            # from a closed socket. This is rarely observed in practice but
            # still make valid selftest runs fail if not caught.
            return True
        base = test_server.TestingTCPServerMixin
        return base.ignored_exceptions_during_shutdown(self, e)


class TestingHTTPSServer(TestingHTTPSServerMixin,
                         http_server.TestingHTTPServer):

    def __init__(self, server_address, request_handler_class,
                 test_case_server, key_file, cert_file):
        TestingHTTPSServerMixin.__init__(self, key_file, cert_file)
        http_server.TestingHTTPServer.__init__(
            self, server_address, request_handler_class, test_case_server)

    def get_request(self):
        sock, addr = http_server.TestingHTTPServer.get_request(self)
        return self._get_ssl_request(sock, addr)


class TestingThreadingHTTPSServer(TestingHTTPSServerMixin,
                                  http_server.TestingThreadingHTTPServer):

    def __init__(self, server_address, request_handler_class,
                 test_case_server, key_file, cert_file):
        TestingHTTPSServerMixin.__init__(self, key_file, cert_file)
        http_server.TestingThreadingHTTPServer.__init__(
            self, server_address, request_handler_class, test_case_server)

    def get_request(self):
        sock, addr = http_server.TestingThreadingHTTPServer.get_request(self)
        return self._get_ssl_request(sock, addr)


class HTTPSServer(http_server.HttpServer):

    _url_protocol = 'https'

    # The real servers depending on the protocol
    http_server_class = {'HTTP/1.0': TestingHTTPSServer,
                         'HTTP/1.1': TestingThreadingHTTPSServer,
                         }

    # Provides usable defaults since an https server requires both a
    # private key and a certificate to work.
    def __init__(self, request_handler=http_server.TestingHTTPRequestHandler,
                 protocol_version=None,
                 key_file=ssl_certs.build_path('server_without_pass.key'),
                 cert_file=ssl_certs.build_path('server.crt')):
        http_server.HttpServer.__init__(self, request_handler=request_handler,
                                        protocol_version=protocol_version)
        self.key_file = key_file
        self.cert_file = cert_file
        self.temp_files = []

    def create_server(self):
        return self.server_class(
            (self.host, self.port), self.request_handler_class, self,
            self.key_file, self.cert_file)


class HTTPSServer_urllib(HTTPSServer):
    """Subclass of HTTPSServer that gives https+urllib urls.

    This is for use in testing: connections to this server will always go
    through urllib where possible.
    """

    # urls returned by this server should require the urllib client impl
    _url_protocol = 'https+urllib'


class HTTPSServer_PyCurl(HTTPSServer):
    """Subclass of HTTPSServer that gives http+pycurl urls.

    This is for use in testing: connections to this server will always go
    through pycurl where possible.
    """

    # We don't care about checking the pycurl availability as
    # this server will be required only when pycurl is present

    # urls returned by this server should require the pycurl client impl
    _url_protocol = 'https+pycurl'
