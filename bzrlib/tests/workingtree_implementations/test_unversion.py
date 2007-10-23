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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests of the WorkingTree.unversion API."""

from bzrlib import errors
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestUnversion(TestCaseWithWorkingTree):

    def test_unversion_requires_write_lock(self):
        """WT.unversion([]) in a read lock raises ReadOnlyError."""
        tree = self.make_branch_and_tree('.')
        tree.lock_read()
        self.assertRaises(errors.ReadOnlyError, tree.unversion, [])
        tree.unlock()

    def test_unversion_missing_file(self):
        """WT.unversion(['missing-id']) raises NoSuchId."""
        tree = self.make_branch_and_tree('.')
        self.assertRaises(errors.NoSuchId, tree.unversion, ['missing-id'])

    def test_unversion_several_files(self):
        """After unversioning several files, they should not be versioned."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'c'])
        tree.add(['a', 'b', 'c'], ['a-id', 'b-id', 'c-id'])
        # within a lock unversion should take effect
        tree.lock_write()
        tree.unversion(['a-id', 'b-id'])
        self.assertFalse(tree.has_id('a-id'))
        self.assertFalse(tree.has_id('b-id'))
        self.assertTrue(tree.has_id('c-id'))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('b'))
        self.assertTrue(tree.has_filename('c'))
        tree.unlock()
        # the changes should have persisted to disk - reopen the workingtree
        # to be sure.
        tree = tree.bzrdir.open_workingtree()
        tree.lock_read()
        self.assertFalse(tree.has_id('a-id'))
        self.assertFalse(tree.has_id('b-id'))
        self.assertTrue(tree.has_id('c-id'))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('b'))
        self.assertTrue(tree.has_filename('c'))
        tree.unlock()

    def test_unversion_subtree(self):
        """Unversioning the root of a subtree unversions the entire subtree."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'c'])
        tree.add(['a', 'a/b', 'c'], ['a-id', 'b-id', 'c-id'])
        # within a lock unversion should take effect
        tree.lock_write()
        tree.unversion(['a-id'])
        self.assertFalse(tree.has_id('a-id'))
        self.assertFalse(tree.has_id('b-id'))
        self.assertTrue(tree.has_id('c-id'))
        self.assertTrue(tree.has_filename('a'))
        self.assertTrue(tree.has_filename('a/b'))
        self.assertTrue(tree.has_filename('c'))
        tree.unlock()

    def test_unversion_subtree_and_children(self):
        """Passing a child id will raise NoSuchId.

        This is because the parent directory will have already been removed.
        """
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b', 'a/c', 'd'])
        tree.add(['a', 'a/b', 'a/c', 'd'], ['a-id', 'b-id', 'c-id', 'd-id'])
        tree.lock_write()
        try:
            tree.unversion(['b-id', 'a-id'])
            self.assertFalse(tree.has_id('a-id'))
            self.assertFalse(tree.has_id('b-id'))
            self.assertFalse(tree.has_id('c-id'))
            self.assertTrue(tree.has_id('d-id'))
            # The files are still on disk
            self.assertTrue(tree.has_filename('a'))
            self.assertTrue(tree.has_filename('a/b'))
            self.assertTrue(tree.has_filename('a/c'))
            self.assertTrue(tree.has_filename('d'))
        finally:
            tree.unlock()

    def test_unversion_renamed(self):
        tree = self.make_branch_and_tree('a')
        self.build_tree(['a/dir/', 'a/dir/f1', 'a/dir/f2', 'a/dir/f3',
                         'a/dir2/'])
        tree.add(['dir', 'dir/f1', 'dir/f2', 'dir/f3', 'dir2'],
                 ['dir-id', 'f1-id', 'f2-id', 'f3-id', 'dir2-id'])
        rev_id1 = tree.commit('init')
        # Start off by renaming entries, and then unversion a bunch of entries
        # https://bugs.launchpad.net/bzr/+bug/114615
        tree.rename_one('dir/f1', 'dir/a')
        tree.rename_one('dir/f2', 'dir/z')
        tree.move(['dir/f3'], 'dir2')

        tree.lock_read()
        try:
            root_id = tree.inventory.root.file_id
            paths = [(path, ie.file_id)
                     for path, ie in tree.iter_entries_by_dir()]
        finally:
            tree.unlock()
        self.assertEqual([('', root_id),
                          ('dir', 'dir-id'),
                          ('dir2', 'dir2-id'),
                          ('dir/a', 'f1-id'),
                          ('dir/z', 'f2-id'),
                          ('dir2/f3', 'f3-id'),
                         ], paths)

        tree.unversion(set(['dir-id']))
        paths = [(path, ie.file_id)
                 for path, ie in tree.iter_entries_by_dir()]

        self.assertEqual([('', root_id),
                          ('dir2', 'dir2-id'),
                          ('dir2/f3', 'f3-id'),
                         ], paths)

