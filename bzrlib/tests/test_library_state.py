# Copyright (C) 2010, 2011 Canonical Ltd
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

"""Tests for BzrLibraryState."""

import bzrlib
from bzrlib import (
    config,
    library_state,
    tests,
    trace,
    ui as _mod_ui
    )
from bzrlib.tests import fixtures


# TODO: once sufficiently cleaned up this should be able to be TestCase.
class TestLibraryState(tests.TestCaseWithTransport):

    def test_ui_is_used(self):
        ui = _mod_ui.SilentUIFactory()
        state = library_state.BzrLibraryState(
            ui=ui, trace=fixtures.RecordingContextManager())
        orig_ui = _mod_ui.ui_factory
        state.__enter__()
        try:
            self.assertEqual(ui, _mod_ui.ui_factory)
        finally:
            state.__exit__(None, None, None)
            self.assertEqual(orig_ui, _mod_ui.ui_factory)

    def test_trace_context(self):
        tracer = fixtures.RecordingContextManager()
        ui = _mod_ui.SilentUIFactory()
        state = library_state.BzrLibraryState(ui=ui, trace=tracer)
        state.__enter__()
        try:
            self.assertEqual(['__enter__'], tracer._calls)
        finally:
            state.__exit__(None, None, None)
            self.assertEqual(['__enter__', '__exit__'], tracer._calls)

    def test_warns_if_not_called(self):
        self.overrideAttr(bzrlib, 'global_state', None)
        warnings = []
        def warning(*args):
            warnings.append(args[0] % args[1:])
        self.overrideAttr(trace, 'warning', warning)
        # Querying for a an option requires a real global_state or emits a
        # warning
        c = config.GlobalStack()
        v = c.get('whatever')
        self.assertLength(1, warnings)
        self.assertEquals("You forgot to use 'with bzrlib.initialize():'",
                          warnings[0])
