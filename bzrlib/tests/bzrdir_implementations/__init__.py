# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
# -*- coding: utf-8 -*-
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""BzrDir implementation tests for bzr.

These test the conformance of all the bzrdir variations to the expected API.
Specific tests for individual formats are in the tests/test_bzrdir.py file 
rather than in tests/branch_implementations/*.py.
"""

from bzrlib.bzrdir import BzrDirTestProviderAdapter, BzrDirFormat
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestLoader,
                          TestSuite,
                          )
from bzrlib.transport.memory import MemoryServer


def test_suite():
    result = TestSuite()
    test_bzrdir_implementations = [
        'bzrlib.tests.bzrdir_implementations.test_bzrdir',
        ]
    formats = BzrDirFormat.known_formats()
    adapter = BzrDirTestProviderAdapter(
        default_transport,
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        formats)
    loader = TestLoader()
    adapt_modules(test_bzrdir_implementations, adapter, loader, result)

    ## >>>>>>>
    # XXX:
    # This will always add the tests for smart server transport, regardless of
    # the --transport option the user specified to 'bzr selftest'.
    from bzrlib.smart.server import SmartTCPServer_for_testing, ReadonlySmartTCPServer_for_testing
    from bzrlib.remote import RemoteBzrDirFormat

    # test the remote server behaviour using a MemoryTransport
    smart_server_suite = TestSuite()
    adapt_to_smart_server = BzrDirTestProviderAdapter(
        MemoryServer,
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteBzrDirFormat())])
    adapt_modules(test_bzrdir_implementations,
                  adapt_to_smart_server,
                  TestLoader(),
                  smart_server_suite)
    result.addTests(smart_server_suite)
    ## >>>>>>>

    return result
