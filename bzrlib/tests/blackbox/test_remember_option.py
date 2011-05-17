# Copyright (C) 2011 Canonical Ltd
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


from bzrlib import branch
from bzrlib.tests import (
    script,
    )


def pull_first_use(test):
    test.run_script('''
        $ bzr init parent
        $ cd parent
        $ echo parent > file
        $ bzr commit -m 'parent'
        $ cd ..
        $ bzr branch parent %(working_dir)s
        $ cd parent
        $ echo new content > file
        $ bzr commit -m 'new content'
        $ cd ..
''' % {'working_dir': test.working_dir}, null_output_matches_anything=True)



class TestRememberMixin(object):
    """--remember and --no-remember set locations or not."""

    # the command to run (expecting additional arguments from the tests
    command = []
    # the dir where the command should be run (it should contain a branch for
    # which the tested locations are/will be set)
    working_dir = None
    # argument list for the first command invocation
    first_use_args = []
    # argument list for the next command invocation
    next_uses_args = []

    def do_command(self, *args):
        # We always expect the same result here and care only about the
        # arguments used and their consequences on the remembered locations
        out, err = self.run_bzr(self.command + list(args),
                                working_dir=self.working_dir)

    def test_first_use_no_option(self):
        self.setup_first_use()
        self.do_command(*self.first_use_args)
        self.assertLocations(self.first_use_args)

    def test_first_use_remember(self):
        self.setup_first_use()
        self.do_command('--remember', *self.first_use_args)
        self.assertLocations(self.first_use_args)

    def test_first_use_no_remember(self):
        self.setup_first_use()
        self.do_command('--no-remember', *self.first_use_args)
        self.assertLocations([])

    def test_next_uses_no_option(self):
        self.setup_next_uses()
        self.do_command(*self.next_uses_args)
        self.assertLocations(self.first_use_args)

    def test_next_uses_remember(self):
        self.setup_next_uses()
        self.do_command('--remember', *self.next_uses_args)
        self.assertLocations(self.next_uses_args)

    def test_next_uses_no_remember(self):
        self.setup_next_uses()
        self.do_command('--no-remember', *self.next_uses_args)
        self.assertLocations(self.first_use_args)


class TestSendRemember(script.TestCaseWithTransportAndScript,
                       TestRememberMixin):

    working_dir = 'work'
    command = ['send', '-o-',]
    first_use_args = ['../parent', '../grand_parent',]
    next_uses_args = ['../new_parent', '../new_grand_parent']

    def setup_first_use(self):
        self.run_script('''
            $ bzr init grand_parent
            $ cd grand_parent
            $ echo grand_parent > file
            $ bzr add
            $ bzr commit -m 'initial commit'
            $ cd ..
            $ bzr branch grand_parent parent
            $ cd parent
            $ echo parent > file
            $ bzr commit -m 'parent'
            $ cd ..
            $ bzr branch parent %(working_dir)s
            $ cd %(working_dir)s
            $ echo %(working_dir)s > file
            $ bzr commit -m '%(working_dir)s'
            $ cd ..
            ''' % {'working_dir': self.working_dir},
                        null_output_matches_anything=True)

    def setup_next_uses(self):
        self.setup_first_use()
        # Do a first send that remembers the locations
        self.do_command(*self.first_use_args)
        # Now create some new targets
        self.run_script('''
            $ bzr branch grand_parent new_grand_parent
            $ bzr branch parent new_parent
            ''',
                        null_output_matches_anything=True)

    def assertLocations(self, expected_locations):
        if not expected_locations:
            expected_submit_branch, expected_public_branch = None, None
        else:
            expected_submit_branch, expected_public_branch = expected_locations
        br, _ = branch.Branch.open_containing(self.working_dir)
        self.assertEquals(expected_submit_branch, br.get_submit_branch())
        self.assertEquals(expected_public_branch, br.get_public_branch())

