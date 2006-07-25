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

"""Tests for the test trees used by the tree_implementations tests."""

from bzrlib import inventory 
from bzrlib.tests.tree_implementations import TestCaseWithTree


class TestTreeShapes(TestCaseWithTree):

    def test_empty_tree_no_parents(self):
        tree = self.get_tree_no_parents_no_content()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        self.assertEqual([inventory.ROOT_ID], list(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID)],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])

    def test_abc_tree_no_parents(self):
        tree = self.get_tree_no_parents_abc_content()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))

    def test_abc_tree_content_2_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_2()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('foobar\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))
        
    def test_abc_tree_content_3_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_3()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('a', 'a-id'), ('b', 'b-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertTrue(tree.is_executable('c-id'))
        
    def test_abc_tree_content_4_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_4()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('b', 'b-id'), ('d', 'a-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))
        
    def test_abc_tree_content_5_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_5()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('b', 'b-id'), ('d', 'a-id'), ('b/c', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('bar\n', tree.get_file_text('a-id'))
        self.assertFalse(tree.is_executable('c-id'))
        
    def test_abc_tree_content_6_no_parents(self):
        tree = self.get_tree_no_parents_abc_content_6()
        self.assertEqual([], tree.get_parent_ids())
        self.assertEqual([], tree.conflicts())
        self.assertEqual([], list(tree.unknowns()))
        # __iter__ has no strongly defined order
        self.assertEqual(
            set([inventory.ROOT_ID, 'a-id', 'b-id', 'c-id']),
            set(iter(tree)))
        self.assertEqual(
            [('', inventory.ROOT_ID), ('a', 'a-id'), ('b', 'b-id'), ('e', 'c-id')],
            [(path, node.file_id) for path, node in tree.iter_entries_by_dir()])
        self.assertEqualDiff('contents of a\n', tree.get_file_text('a-id'))
        self.assertTrue(tree.is_executable('c-id'))
