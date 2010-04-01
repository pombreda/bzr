# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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


from bzrlib import (
    branch,
    builtins,
    tests,
    )
from bzrlib.tests import transport_util


class TestPull(transport_util.TestCaseWithConnectionHookedTransport):

    def test_pull(self):
        wt1 = self.make_branch_and_tree('branch1')
        tip = wt1.commit('empty commit')
        wt2 = self.make_branch_and_tree('branch2')

        self.start_logging_connections()

        cmd = builtins.cmd_pull()
        # We don't care about the ouput but 'outf' should be defined
        cmd.outf = tests.StringIOWrapper()
        cmd.run_direct(self.get_url('branch1'), directory='branch2')
        self.assertEquals(1, len(self.connections))

    def test_pull_with_bound_branch(self):

        master_wt = self.make_branch_and_tree('master')
        local_wt = self.make_branch_and_tree('local')
        master_branch = branch.Branch.open(self.get_url('master'))
        local_wt.branch.bind(master_branch)

        remote_wt = self.make_branch_and_tree('remote')
        remote_wt.commit('empty commit')

        self.start_logging_connections()

        pull = builtins.cmd_pull()
        # We don't care about the ouput but 'outf' should be defined
        pull.outf = tests.StringIOWrapper()
        pull.run_direct(self.get_url('remote'), directory='local')
        self.assertEquals(1, len(self.connections))

