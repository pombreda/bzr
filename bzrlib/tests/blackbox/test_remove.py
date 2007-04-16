# Copyright (C) 2005, 2006 Canonical Ltd
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


import os, re

from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree
from bzrlib import osutils

_id='-id'
a='a'
b='b/'
c='b/c'
files=(a,b,c)


class TestRemove(ExternalBase):

    def _make_add_and_assert_tree(self,files):
        tree = self.make_branch_and_tree('.')
        self.build_tree(files)
        for f in files:
            id=str(f).replace('/', '_') + _id
            tree.add(f, id)
            self.assertEqual(tree.path2id(f), id)
            self.failUnlessExists(f)
            self.assertInWorkingTree(f)
        return tree

    def assertFilesDeleted(self,files):
        for f in files:
            id=f+_id
            self.assertNotInWorkingTree(f)
            self.failIfExists(f)

    def assertFilesUnversioned(self,files):
        for f in files:
            self.assertNotInWorkingTree(f)
            self.failUnlessExists(f)

    def run_bzr_remove_changed_files(self, error_regexes, cmd):
        error_regexes.extend(["Can't remove changed or unknown files:",
            'Use --keep to not delete them,'
            ' or --force to delete them regardless.'
            ])
        self.run_bzr_error(error_regexes, cmd)

    def test_remove_no_files_specified(self):
        tree = self._make_add_and_assert_tree([])
        self.run_bzr_error(["bzr: ERROR: Specify one or more files to remove, "
            "or use --new."], 'remove')

        self.run_bzr_error(["bzr: ERROR: No matching files."], 'remove --new')

        self.run_bzr_error(["bzr: ERROR: No matching files."],
            'remove --new .')

    def test_remove_invalid_files(self):
        self.build_tree([a])
        tree = self.make_branch_and_tree('.')
        self.run_bzr('remove .')

    def test_remove_unversioned_files(self):
        self.build_tree([a])
        tree = self.make_branch_and_tree('.')
        self.run_bzr_remove_changed_files(['unknown:[.\s]*a'], 'remove a')

    def test_remove_keep_unversioned_files(self):
        self.build_tree([a])
        tree = self.make_branch_and_tree('.')
        self.run_bzr('remove --keep a', error_regexes=["a is not versioned."])

    def test_remove_force_unversioned_files(self):
        self.build_tree([a])
        tree = self.make_branch_and_tree('.')
        self.run_bzr('remove --force a', error_regexes=["deleted a"])
        self.assertFilesDeleted([a])

    def test_remove_non_existing_files(self):
        tree = self._make_add_and_assert_tree([])
        self.run_bzr_remove_changed_files(['unknown:[.\s]*b'], 'remove b')

    def test_remove_keep_non_existing_files(self):
        tree = self._make_add_and_assert_tree([])
        self.run_bzr('remove --keep b', error_regexes=["b is not versioned."])

    def test_rm_one_file(self):
        tree = self._make_add_and_assert_tree([a])
        self.run_bzr("commit -m 'added a'")
        self.run_bzr('rm a', error_regexes=["deleted a"])
        self.assertFilesDeleted([a])

    def test_remove_one_file(self):
        tree = self._make_add_and_assert_tree([a])
        self.run_bzr("commit -m 'added a'")
        self.run_bzr('remove a', error_regexes=["deleted a"])
        self.assertFilesDeleted([a])

    def test_remove_keep_one_file(self):
        tree = self._make_add_and_assert_tree([a])
        self.run_bzr('remove --keep a', error_regexes=["removed a"])
        self.assertFilesUnversioned([a])

    def test_remove_files(self):
        tree = self._make_add_and_assert_tree(files)
        self.run_bzr("commit -m 'added files'")
        self.run_bzr('remove a b b/c', 
                     error_regexes=["deleted a", "deleted b", "deleted b/c"])
        self.assertFilesDeleted(files)

    def test_remove_keep_files(self):
        tree = self._make_add_and_assert_tree(files)
        self.run_bzr("commit -m 'added files'")
        self.run_bzr('remove --keep a b b/c', 
                     error_regexes=["removed a", "removed b", "removed b/c"])
        self.assertFilesUnversioned(files)

    def test_remove_on_deleted(self):
        tree = self._make_add_and_assert_tree([a])
        self.run_bzr("commit -m 'added a'")        
        os.unlink(a)
        self.assertInWorkingTree(a)
        self.run_bzr('remove a')
        self.assertNotInWorkingTree(a)

    def test_remove_with_new(self):
        tree = self._make_add_and_assert_tree(files)
        self.run_bzr('remove --new --keep',
                     error_regexes=["removed a", "removed b", "removed b/c"])
        self.assertFilesUnversioned(files)

    def test_remove_with_new_in_dir1(self):
        tree = self._make_add_and_assert_tree(files)
        self.run_bzr('remove --new --keep b b/c',
                     error_regexes=["removed b", "removed b/c"])
        tree = WorkingTree.open('.')
        self.assertInWorkingTree(a)
        self.assertEqual(tree.path2id(a), a+_id)
        self.assertFilesUnversioned([b,c])

    def test_remove_with_new_in_dir2(self):
        tree = self._make_add_and_assert_tree(files)
        self.run_bzr('remove --new --keep .',
                     error_regexes=["removed a", "removed b", "removed b/c"])
        tree = WorkingTree.open('.')
        self.assertFilesUnversioned([a])
