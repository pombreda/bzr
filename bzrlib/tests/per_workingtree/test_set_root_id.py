# Copyright (C) 2006 Canonical Ltd
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

"""Tests for WorkingTree.set_root_id"""

from bzrlib import inventory
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree


class TestSetRootId(TestCaseWithWorkingTree):

    def test_set_and_read_unicode(self):
        # This write locks the local tree, and then grabs a read lock on a
        # copy, which is bogus and the test just needs to be rewritten.
        self.thisFailsStrictLockCheck()
        tree = self.make_branch_and_tree('a-tree')
        # setting the root id allows it to be read via get_root_id.
        root_id = u'\xe5n-id'.encode('utf8')
        tree.lock_write()
        try:
            old_id = tree.get_root_id()
            tree.set_root_id(root_id)
            self.assertEqual(root_id, tree.get_root_id())
            # set root id should not have triggered a flush of the tree,
            # so check a new tree sees the old state.
            reference_tree = tree.bzrdir.open_workingtree()
            self.assertEqual(old_id, reference_tree.get_root_id())
        finally:
            tree.unlock()
        # having unlocked the tree, the value should have been
        # preserved into the next lock, which is an implicit read
        # lock around the get_root_id call.
        self.assertEqual(root_id, tree.get_root_id())
        # and if we get a new working tree instance, then the value
        # should still be retained
        tree = tree.bzrdir.open_workingtree()
        self.assertEqual(root_id, tree.get_root_id())
