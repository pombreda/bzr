# Copyright (C) 2006 by Canonical Ltd
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

"""Tests for the extra cases that WorkingTree.walkdirs can encounter."""

import os

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree

# tests to write:
# type mismatches - file to link, dir, dir to file, link, link to file, dir

class TestWalkdirs(TestCaseWithWorkingTree):

    def get_tree_with_unknowns(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree([
            'unknown file',
            'unknown dir/',
            'unknown dir/a file',
            ])
        u_f_stat = os.lstat('unknown file')
        u_d_stat = os.lstat('unknown dir')
        u_d_f_stat = os.lstat('unknown dir/a file')
        expected_dirblocks = [
            (('', tree.inventory.root.file_id),
             [
              ('unknown dir', 'unknown dir', 'directory', u_d_stat, None, None),
              ('unknown file', 'unknown file', 'file', u_f_stat, None, None),
             ]
            ),
            (('unknown dir', None),
             [('unknown dir/a file', 'a file', 'file', u_d_f_stat, None, None),
             ]
            ),
            ]
        return tree, expected_dirblocks
    
    def test_walkdir_unknowns(self):
        """unknown files and directories should be reported by walkdirs."""
        # test that its iterable by iterating:
        result = []
        tree, expected_dirblocks = self.get_tree_with_unknowns()
        for dirinfo, dirblock in tree.walkdirs():
            result.append((dirinfo, list(dirblock)))
        # check each return value for debugging ease.
        for pos, item in enumerate(expected_dirblocks):
            self.assertEqual(item, result[pos])
        self.assertEqual(len(expected_dirblocks), len(result))

    def test_walkdir_from_unknown_dir(self):
        """Doing a walkdir when the requested prefix is unknown but on disk."""
        result = []
        tree, expected_dirblocks = self.get_tree_with_unknowns()
        for dirinfo, dirblock in tree.walkdirs('unknown dir'):
            result.append((dirinfo, list(dirblock)))
        # check each return value for debugging ease.
        for pos, item in enumerate(expected_dirblocks[1:]):
            self.assertEqual(item, result[pos])
        self.assertEqual(len(expected_dirblocks) - 1, len(result))

    def get_tree_with_missings(self):
        tree = self.make_branch_and_tree('.')
        paths = [
            'missing file',
            'missing dir/',
            'missing dir/a file',
            ]
        ids = [
            'a file',
            'a dir',
            'a dir-a file',
            ]
        self.build_tree(paths)
        tree.add(paths, ids)
        tree.commit('first post')
        # now make the files be missing
        tree.bzrdir.root_transport.delete_tree('missing dir')
        tree.bzrdir.root_transport.delete('missing file')
        expected_dirblocks = [
            (('', tree.inventory.root.file_id),
             [
              ('missing dir', 'missing dir', 'unknown', None, 'a dir', 'directory'),
              ('missing file', 'missing file', 'unknown', None, 'a file', 'file'),
             ]
            ),
            (('missing dir', 'a dir'),
             [('missing dir/a file', 'a file', 'unknown', None, 'a dir-a file', 'file'),
             ]
            ),
            ]
        return tree, expected_dirblocks
    
    def test_walkdir_missings(self):
        """missing files and directories should be reported by walkdirs."""
        # test that its iterable by iterating:
        result = []
        tree, expected_dirblocks = self.get_tree_with_missings()
        for dirinfo, dirblock in tree.walkdirs():
            result.append((dirinfo, list(dirblock)))
        # check each return value for debugging ease.
        for pos, item in enumerate(expected_dirblocks):
            self.assertEqual(item, result[pos])
        self.assertEqual(len(expected_dirblocks), len(result))

    def test_walkdir_from_missing_dir(self):
        """Doing a walkdir when the requested prefix is missing but on disk."""
        result = []
        tree, expected_dirblocks = self.get_tree_with_missings()
        for dirinfo, dirblock in tree.walkdirs('missing dir'):
            result.append((dirinfo, list(dirblock)))
        # check each return value for debugging ease.
        for pos, item in enumerate(expected_dirblocks[1:]):
            self.assertEqual(item, result[pos])
        self.assertEqual(len(expected_dirblocks[1:]), len(result))
