# Copyright (C) 2005 Canonical Ltd
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


from StringIO import StringIO

from bzrlib.revisionspec import RevisionSpec
from bzrlib.status import show_pending_merges, show_tree_status
from bzrlib.tests import TestCaseWithTransport


class TestStatus(TestCaseWithTransport):

    def test_pending_none(self):
        # Test whether show_pending_merges works in a tree with no commits
        tree = self.make_branch_and_tree('a')
        tree.commit('empty commit')
        tree2 = self.make_branch_and_tree('b')
        # set a left most parent that is not a present commit
        tree2.add_parent_tree_id('some-ghost', allow_leftmost_as_ghost=True)
        # do a merge
        tree2.merge_from_branch(tree.branch)
        output = StringIO()
        show_pending_merges(tree2, output)
        self.assertContainsRe(output.getvalue(), 'empty commit')

    def tests_revision_to_revision(self):
        """doing a status between two revision trees should work."""
        tree = self.make_branch_and_tree('.')
        r1_id = tree.commit('one', allow_pointless=True)
        r2_id = tree.commit('two', allow_pointless=True)
        r2_tree = tree.branch.repository.revision_tree(r2_id)
        output = StringIO()
        show_tree_status(tree, to_file=output,
                     revision=[RevisionSpec.from_string("revid:%s" % r1_id),
                               RevisionSpec.from_string("revid:%s" % r2_id)])
        # return does not matter as long as it did not raise.

    def test_pending_specific_files(self):
        """With a specific file list, pending merges are not shown."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', 'content of a\n')])
        tree.add('a')
        r1_id = tree.commit('one')
        alt = tree.bzrdir.sprout('alt').open_workingtree()
        self.build_tree_contents([('alt/a', 'content of a\nfrom alt\n')])
        alt_id = alt.commit('alt')
        tree.merge_from_branch(alt.branch)
        output = StringIO()
        show_tree_status(tree, to_file=output)
        self.assertContainsRe(output.getvalue(), 'pending merges:')
        output = StringIO()
        show_tree_status(tree, to_file=output, specific_files=['a'])
        self.assertNotContainsRe(output.getvalue(), 'pending merges:')
