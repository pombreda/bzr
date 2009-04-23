# Copyright (C) 2007 Canonical Ltd
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

"""Test that all Tree's implement get_symlink_target"""

import os

from bzrlib import (
    errors,
    osutils,
    tests,
    )
from bzrlib.tests import tree_implementations


class TestGetSymlinkTarget(tree_implementations.TestCaseWithTree):

    def get_tree_with_symlinks(self):
        self.requireFeature(tests.SymlinkFeature)
        tree = self.make_branch_and_tree('tree')
        os.symlink('foo', 'tree/link')
        os.symlink('../bar', 'tree/rel_link')
        os.symlink('/baz/bing', 'tree/abs_link')

        tree.add(['link', 'rel_link', 'abs_link'],
                 ['link-id', 'rel-link-id', 'abs-link-id'])
        return self._convert_tree(tree)

    def test_get_symlink_target(self):
        tree = self.get_tree_with_symlinks()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual('foo', tree.get_symlink_target('link-id'))
        self.assertEqual('../bar', tree.get_symlink_target('rel-link-id'))
        self.assertEqual('/baz/bing', tree.get_symlink_target('abs-link-id'))

    def test_get_unicode_symlink_target(self):
        self.requireFeature(tests.SymlinkFeature)
        self.requireFeature(tests.UnicodeFilenameFeature)
        tree = self.make_branch_and_tree('tree')
        target = u'targ\N{Euro Sign}t'
        os.symlink(target,  u'tree/\u03b2_link'.encode(osutils._fs_enc))
        tree.add([u'\u03b2_link'], ['unicode-link-id'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        actual = tree.get_symlink_target(u'unicode-link-id')
        self.assertEqual(target, actual)

