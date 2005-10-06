# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.commit import Commit


# TODO: Test commit with some added, and added-but-missing files

class TestConflicts(TestCaseInTempDir):

    def test_conflicts(self):
        """Conflicts are detected properly"""
        b = Branch.initialize('.')
        file('hello', 'w').write('hello world')
        file('hello.BASE', 'w').write('hello world')
        file('hello.sploo.BASE', 'w').write('yellow world')
        tree = b.working_tree()
        self.assertEqual(len(list(tree.list_files())), 3)
        conflicts = list(tree.iter_conflicts())
        self.assertEqual(len(conflicts), 2)
        assert 'hello' in conflicts
        assert 'hello.sploo' in conflicts
        os.unlink('hello.BASE')
        os.unlink('hello.sploo.BASE')
        self.assertEqual(len(list(tree.iter_conflicts())), 0)

