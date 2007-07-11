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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the compiled dirstate helpers."""

import bisect
import os

from bzrlib import (
    tests,
    )


class _CompiledDirstateHelpersFeature(tests.Feature):
    def _probe(self):
        try:
            import bzrlib._dirstate_helpers_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._dirstate_helpers_c'

CompiledDirstateHelpersFeature = _CompiledDirstateHelpersFeature()


class TestBisectPathMixin(object):
    """Test that bisect_path_*() returns the expected values.

    bisect_path_* is intended to work like bisect.bisect_*() except it
    knows it is working on paths that are sorted by ('path', 'to', 'foo')
    chunks rather than by raw 'path/to/foo'.
    """

    def get_bisect_path(self):
        """Return an implementation of bisect_path_*"""
        raise NotImplementedError

    def get_bisect(self):
        """Return a version of bisect.bisect_*.

        Also, for the 'exists' check, return the offset to the real values.
        For example bisect_left returns the index of an entry, while
        bisect_right returns the index *after* an entry

        :return: (bisect_func, offset)
        """
        raise NotImplementedError

    def assertBisect(self, paths, split_paths, path, exists=True):
        """Assert that bisect_split works like bisect_left on the split paths.

        :param paths: A list of path names
        :param split_paths: A list of path names that are already split up by directory
            ('path/to/foo' => ('path', 'to', 'foo'))
        :param path: The path we are indexing.
        :param exists: The path should be present, so make sure the
            final location actually points to the right value.

        All other arguments will be passed along.
        """
        bisect_path = self.get_bisect_path()
        self.assertIsInstance(paths, list)
        bisect_path_idx = bisect_path(paths, path)
        split_path = self.split_for_dirblocks([path])[0]
        bisect_func, offset = self.get_bisect()
        bisect_split_idx = bisect_func(split_paths, split_path)
        self.assertEqual(bisect_split_idx, bisect_path_idx,
                         '%s disagreed. %s != %s'
                         ' for key %r'
                         % (bisect_path.__name__,
                            bisect_split_idx, bisect_path_idx, path)
                         )
        if exists:
            self.assertEqual(path, paths[bisect_path_idx+offset])

    def split_for_dirblocks(self, paths):
        dir_split_paths = []
        for path in paths:
            dirname, basename = os.path.split(path)
            dir_split_paths.append((dirname.split('/'), basename))
        dir_split_paths.sort()
        return dir_split_paths

    def test_simple(self):
        """In the simple case it works just like bisect_left"""
        paths = ['', 'a', 'b', 'c', 'd']
        split_paths = self.split_for_dirblocks(paths)
        for path in paths:
            self.assertBisect(paths, split_paths, path, exists=True)
        self.assertBisect(paths, split_paths, '_', exists=False)
        self.assertBisect(paths, split_paths, 'aa', exists=False)
        self.assertBisect(paths, split_paths, 'bb', exists=False)
        self.assertBisect(paths, split_paths, 'cc', exists=False)
        self.assertBisect(paths, split_paths, 'dd', exists=False)
        self.assertBisect(paths, split_paths, 'a/a', exists=False)
        self.assertBisect(paths, split_paths, 'b/b', exists=False)
        self.assertBisect(paths, split_paths, 'c/c', exists=False)
        self.assertBisect(paths, split_paths, 'd/d', exists=False)

    def test_involved(self):
        """This is where bisect_path_* diverges slightly."""
        # This is the list of paths and their contents
        # a/
        #   a/
        #     a
        #     z
        #   a-a/
        #     a
        #   a-z/
        #     z
        #   a=a/
        #     a
        #   a=z/
        #     z
        #   z/
        #     a
        #     z
        #   z-a
        #   z-z
        #   z=a
        #   z=z
        # a-a/
        #   a
        # a-z/
        #   z
        # a=a/
        #   a
        # a=z/
        #   z
        # This is the exact order that is stored by dirstate
        # All children in a directory are mentioned before an children of
        # children are mentioned.
        # So all the root-directory paths, then all the
        # first sub directory, etc.
        paths = [# content of '/'
                 '', 'a', 'a-a', 'a-z', 'a=a', 'a=z',
                 # content of 'a/'
                 'a/a', 'a/a-a', 'a/a-z',
                 'a/a=a', 'a/a=z',
                 'a/z', 'a/z-a', 'a/z-z',
                 'a/z=a', 'a/z=z',
                 # content of 'a/a/'
                 'a/a/a', 'a/a/z',
                 # content of 'a/a-a'
                 'a/a-a/a',
                 # content of 'a/a-z'
                 'a/a-z/z',
                 # content of 'a/a=a'
                 'a/a=a/a',
                 # content of 'a/a=z'
                 'a/a=z/z',
                 # content of 'a/z/'
                 'a/z/a', 'a/z/z',
                 # content of 'a-a'
                 'a-a/a',
                 # content of 'a-z'
                 'a-z/z',
                 # content of 'a=a'
                 'a=a/a',
                 # content of 'a=z'
                 'a=z/z',
                ]
        split_paths = self.split_for_dirblocks(paths)
        sorted_paths = []
        for dir_parts, basename in split_paths:
            if dir_parts == ['']:
                sorted_paths.append(basename)
            else:
                sorted_paths.append('/'.join(dir_parts + [basename]))

        self.assertEqual(sorted_paths, paths)

        for path in paths:
            self.assertBisect(paths, split_paths, path, exists=True)


class TestBisectPathLeft(tests.TestCase, TestBisectPathMixin):

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_py import bisect_path_left_py
        return bisect_path_left_py

    def get_bisect(self):
        return bisect.bisect_left, 0


class TestCompiledBisectPathLeft(TestBisectPathLeft):
    """Test that bisect_path_left() returns the expected values.

    This runs all the normal tests that TestBisectDirblock did, but uses the
    compiled version.
    """

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_c import bisect_path_left_c
        return bisect_path_left_c


class TestBisectPathRight(tests.TestCase, TestBisectPathMixin):

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_py import bisect_path_right_py
        return bisect_path_right_py

    def get_bisect(self):
        return bisect.bisect_right, -1


class TestCompiledBisectPathRight(TestBisectPathRight):
    """Test that bisect_path_right() returns the expected values.

    This runs all the normal tests that TestBisectDirblock did, but uses the
    compiled version.
    """

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_bisect_path(self):
        from bzrlib._dirstate_helpers_c import bisect_path_right_c
        return bisect_path_right_c


class TestBisectDirblock(tests.TestCase):
    """Test that bisect_dirblock() returns the expected values.

    bisect_dirblock is intended to work like bisect.bisect_left() except it
    knows it is working on dirblocks and that dirblocks are sorted by ('path',
    'to', 'foo') chunks rather than by raw 'path/to/foo'.
    """

    def get_bisect_dirblock(self):
        """Return an implementation of bisect_dirblock"""
        from bzrlib._dirstate_helpers_py import bisect_dirblock_py
        return bisect_dirblock_py

    def assertBisect(self, dirblocks, split_dirblocks, path, *args, **kwargs):
        """Assert that bisect_split works like bisect_left on the split paths.

        :param dirblocks: A list of (path, [info]) pairs.
        :param split_dirblocks: A list of ((split, path), [info]) pairs.
        :param path: The path we are indexing.

        All other arguments will be passed along.
        """
        bisect_dirblock = self.get_bisect_dirblock()
        self.assertIsInstance(dirblocks, list)
        bisect_split_idx = bisect_dirblock(dirblocks, path, *args, **kwargs)
        split_dirblock = (path.split('/'), [])
        bisect_left_idx = bisect.bisect_left(split_dirblocks, split_dirblock,
                                             *args)
        self.assertEqual(bisect_left_idx, bisect_split_idx,
                         'bisect_split disagreed. %s != %s'
                         ' for key %r'
                         % (bisect_left_idx, bisect_split_idx, path)
                         )

    def paths_to_dirblocks(self, paths):
        """Convert a list of paths into dirblock form.

        Also, ensure that the paths are in proper sorted order.
        """
        dirblocks = [(path, []) for path in paths]
        split_dirblocks = [(path.split('/'), []) for path in paths]
        self.assertEqual(sorted(split_dirblocks), split_dirblocks)
        return dirblocks, split_dirblocks

    def test_simple(self):
        """In the simple case it works just like bisect_left"""
        paths = ['', 'a', 'b', 'c', 'd']
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path)
        self.assertBisect(dirblocks, split_dirblocks, '_')
        self.assertBisect(dirblocks, split_dirblocks, 'aa')
        self.assertBisect(dirblocks, split_dirblocks, 'bb')
        self.assertBisect(dirblocks, split_dirblocks, 'cc')
        self.assertBisect(dirblocks, split_dirblocks, 'dd')
        self.assertBisect(dirblocks, split_dirblocks, 'a/a')
        self.assertBisect(dirblocks, split_dirblocks, 'b/b')
        self.assertBisect(dirblocks, split_dirblocks, 'c/c')
        self.assertBisect(dirblocks, split_dirblocks, 'd/d')

    def test_involved(self):
        """This is where bisect_left diverges slightly."""
        paths = ['', 'a',
                 'a/a', 'a/a/a', 'a/a/z', 'a/a-a', 'a/a-z',
                 'a/z', 'a/z/a', 'a/z/z', 'a/z-a', 'a/z-z',
                 'a-a', 'a-z',
                 'z', 'z/a/a', 'z/a/z', 'z/a-a', 'z/a-z',
                 'z/z', 'z/z/a', 'z/z/z', 'z/z-a', 'z/z-z',
                 'z-a', 'z-z',
                ]
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path)

    def test_involved_cached(self):
        """This is where bisect_left diverges slightly."""
        paths = ['', 'a',
                 'a/a', 'a/a/a', 'a/a/z', 'a/a-a', 'a/a-z',
                 'a/z', 'a/z/a', 'a/z/z', 'a/z-a', 'a/z-z',
                 'a-a', 'a-z',
                 'z', 'z/a/a', 'z/a/z', 'z/a-a', 'z/a-z',
                 'z/z', 'z/z/a', 'z/z/z', 'z/z-a', 'z/z-z',
                 'z-a', 'z-z',
                ]
        cache = {}
        dirblocks, split_dirblocks = self.paths_to_dirblocks(paths)
        for path in paths:
            self.assertBisect(dirblocks, split_dirblocks, path, cache=cache)


class TestCompiledBisectDirblock(TestBisectDirblock):
    """Test that bisect_dirblock() returns the expected values.

    bisect_dirblock is intended to work like bisect.bisect_left() except it
    knows it is working on dirblocks and that dirblocks are sorted by ('path',
    'to', 'foo') chunks rather than by raw 'path/to/foo'.

    This runs all the normal tests that TestBisectDirblock did, but uses the
    compiled version.
    """

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_bisect_dirblock(self):
        from bzrlib._dirstate_helpers_c import bisect_dirblock_c
        return bisect_dirblock_c


class TestCmpByDirs(tests.TestCase):

    def get_cmp_by_dirs(self):
        """Get a specific implementation of cmp_by_dirs."""
        from bzrlib._dirstate_helpers_py import cmp_by_dirs_py
        return cmp_by_dirs_py

    def assertPositive(self, val):
        """Assert that val is greater than 0."""
        self.assertTrue(val > 0, 'expected a positive value, but got %s' % val)

    def assertNegative(self, val):
        """Assert that val is less than 0."""
        self.assertTrue(val < 0, 'expected a negative value, but got %s' % val)

    def assertCmpByDirs(self, expected, str1, str2):
        """Compare the two strings, in both directions.

        :param expected: The expected comparison value. -1 means str1 comes
            first, 0 means they are equal, 1 means str2 comes first
        :param str1: string to compare
        :param str2: string to compare
        """
        cmp_by_dirs = self.get_cmp_by_dirs()
        if expected == 0:
            self.assertEqual(str1, str2)
            self.assertEqual(0, cmp_by_dirs(str1, str2))
            self.assertEqual(0, cmp_by_dirs(str2, str1))
        elif expected > 0:
            self.assertPositive(cmp_by_dirs(str1, str2))
            self.assertNegative(cmp_by_dirs(str2, str1))
        else:
            self.assertNegative(cmp_by_dirs(str1, str2))
            self.assertPositive(cmp_by_dirs(str2, str1))

    def test_cmp_empty(self):
        """Compare against the empty string."""
        self.assertCmpByDirs(0, '', '')
        self.assertCmpByDirs(1, 'a', '')
        self.assertCmpByDirs(1, 'ab', '')
        self.assertCmpByDirs(1, 'abc', '')
        self.assertCmpByDirs(1, 'abcd', '')
        self.assertCmpByDirs(1, 'abcde', '')
        self.assertCmpByDirs(1, 'abcdef', '')
        self.assertCmpByDirs(1, 'abcdefg', '')
        self.assertCmpByDirs(1, 'abcdefgh', '')
        self.assertCmpByDirs(1, 'abcdefghi', '')
        self.assertCmpByDirs(1, 'test/ing/a/path/', '')

    def test_cmp_same_str(self):
        """Compare the same string"""
        self.assertCmpByDirs(0, 'a', 'a')
        self.assertCmpByDirs(0, 'ab', 'ab')
        self.assertCmpByDirs(0, 'abc', 'abc')
        self.assertCmpByDirs(0, 'abcd', 'abcd')
        self.assertCmpByDirs(0, 'abcde', 'abcde')
        self.assertCmpByDirs(0, 'abcdef', 'abcdef')
        self.assertCmpByDirs(0, 'abcdefg', 'abcdefg')
        self.assertCmpByDirs(0, 'abcdefgh', 'abcdefgh')
        self.assertCmpByDirs(0, 'abcdefghi', 'abcdefghi')
        self.assertCmpByDirs(0, 'testing a long string', 'testing a long string')
        self.assertCmpByDirs(0, 'x'*10000, 'x'*10000)
        self.assertCmpByDirs(0, 'a/b', 'a/b')
        self.assertCmpByDirs(0, 'a/b/c', 'a/b/c')
        self.assertCmpByDirs(0, 'a/b/c/d', 'a/b/c/d')
        self.assertCmpByDirs(0, 'a/b/c/d/e', 'a/b/c/d/e')

    def test_simple_paths(self):
        """Compare strings that act like normal string comparison"""
        self.assertCmpByDirs(-1, 'a', 'b')
        self.assertCmpByDirs(-1, 'aa', 'ab')
        self.assertCmpByDirs(-1, 'ab', 'bb')
        self.assertCmpByDirs(-1, 'aaa', 'aab')
        self.assertCmpByDirs(-1, 'aab', 'abb')
        self.assertCmpByDirs(-1, 'abb', 'bbb')
        self.assertCmpByDirs(-1, 'aaaa', 'aaab')
        self.assertCmpByDirs(-1, 'aaab', 'aabb')
        self.assertCmpByDirs(-1, 'aabb', 'abbb')
        self.assertCmpByDirs(-1, 'abbb', 'bbbb')
        self.assertCmpByDirs(-1, 'aaaaa', 'aaaab')
        self.assertCmpByDirs(-1, 'a/a', 'a/b')
        self.assertCmpByDirs(-1, 'a/b', 'b/b')
        self.assertCmpByDirs(-1, 'a/a/a', 'a/a/b')
        self.assertCmpByDirs(-1, 'a/a/b', 'a/b/b')
        self.assertCmpByDirs(-1, 'a/b/b', 'b/b/b')
        self.assertCmpByDirs(-1, 'a/a/a/a', 'a/a/a/b')
        self.assertCmpByDirs(-1, 'a/a/a/b', 'a/a/b/b')
        self.assertCmpByDirs(-1, 'a/a/b/b', 'a/b/b/b')
        self.assertCmpByDirs(-1, 'a/b/b/b', 'b/b/b/b')
        self.assertCmpByDirs(-1, 'a/a/a/a/a', 'a/a/a/a/b')

    def test_tricky_paths(self):
        self.assertCmpByDirs(1, 'ab/cd/ef', 'ab/cc/ef')
        self.assertCmpByDirs(1, 'ab/cd/ef', 'ab/c/ef')
        self.assertCmpByDirs(-1, 'ab/cd/ef', 'ab/cd-ef')
        self.assertCmpByDirs(-1, 'ab/cd', 'ab/cd-')
        self.assertCmpByDirs(-1, 'ab/cd', 'ab-cd')


class TestCompiledCmpByDirs(TestCmpByDirs):
    """Test the pyrex implementation of cmp_by_dirs"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_cmp_by_dirs(self):
        from bzrlib._dirstate_helpers_c import cmp_by_dirs_c
        return cmp_by_dirs_c


class TestCmpPathByDirblock(tests.TestCase):

    def get_cmp_path_by_dirblock(self):
        """Get a specific implementation of cmp_path_by_dirblock."""
        from bzrlib._dirstate_helpers_py import cmp_path_by_dirblock_py
        return cmp_path_by_dirblock_py

    def assertCmpPathByDirblock(self, paths):
        """Compare all paths and make sure they evaluate to the correct order.

        This does N^2 comparisons. It is assumed that ``paths`` is properly
        sorted list.

        :param paths: a sorted list of paths to compare
        """
        # First, make sure the paths being passed in are correct
        def _key(p):
            dirname, basename = os.path.split(p)
            return dirname.split('/'), basename
        self.assertEqual(sorted(paths, key=_key), paths)

        cmp_path_by_dirblock = self.get_cmp_path_by_dirblock()
        for idx1, path1 in enumerate(paths):
            for idx2, path2 in enumerate(paths):
                cmp_val = cmp_path_by_dirblock(path1, path2)
                if idx1 < idx2:
                    self.assertTrue(cmp_val < 0,
                        '%s did not state that %r came before %r, cmp=%s'
                        % (cmp_path_by_dirblock.__name__,
                           path1, path2, cmp_val))
                elif idx1 > idx2:
                    self.assertTrue(cmp_val > 0,
                        '%s did not state that %r came after %r, cmp=%s'
                        % (cmp_path_by_dirblock.__name__,
                           path1, path2, cmp_val))
                else: # idx1 == idx2
                    self.assertTrue(cmp_val == 0,
                        '%s did not state that %r == %r, cmp=%s'
                        % (cmp_path_by_dirblock.__name__,
                           path1, path2, cmp_val))

    def test_cmp_simple_paths(self):
        """Compare against the empty string."""
        self.assertCmpPathByDirblock(['', 'a', 'ab', 'abc', 'a/b/c', 'b/d/e'])
        self.assertCmpPathByDirblock(['kl', 'ab/cd', 'ab/ef', 'gh/ij'])

    def test_tricky_paths(self):
        self.assertCmpPathByDirblock([
            # Contents of ''
            '', 'a', 'a-a', 'a=a', 'b',
            # Contents of 'a'
            'a/a', 'a/a-a', 'a/a=a', 'a/b',
            # Contents of 'a/a'
            'a/a/a', 'a/a/a-a', 'a/a/a=a',
            # Contents of 'a/a/a'
            'a/a/a/a', 'a/a/a/b',
            # Contents of 'a/a/a-a',
            'a/a/a-a/a', 'a/a/a-a/b',
            # Contents of 'a/a/a=a',
            'a/a/a=a/a', 'a/a/a=a/b',
            # Contents of 'a/a-a'
            'a/a-a/a',
            # Contents of 'a/a-a/a'
            'a/a-a/a/a', 'a/a-a/a/b',
            # Contents of 'a/a=a'
            'a/a=a/a',
            # Contents of 'a/b'
            'a/b/a', 'a/b/b',
            # Contents of 'a-a',
            'a-a/a', 'a-a/b',
            # Contents of 'a=a',
            'a=a/a', 'a=a/b',
            # Contents of 'b',
            'b/a', 'b/b',
            ])
        self.assertCmpPathByDirblock([
                 # content of '/'
                 '', 'a', 'a-a', 'a-z', 'a=a', 'a=z',
                 # content of 'a/'
                 'a/a', 'a/a-a', 'a/a-z',
                 'a/a=a', 'a/a=z',
                 'a/z', 'a/z-a', 'a/z-z',
                 'a/z=a', 'a/z=z',
                 # content of 'a/a/'
                 'a/a/a', 'a/a/z',
                 # content of 'a/a-a'
                 'a/a-a/a',
                 # content of 'a/a-z'
                 'a/a-z/z',
                 # content of 'a/a=a'
                 'a/a=a/a',
                 # content of 'a/a=z'
                 'a/a=z/z',
                 # content of 'a/z/'
                 'a/z/a', 'a/z/z',
                 # content of 'a-a'
                 'a-a/a',
                 # content of 'a-z'
                 'a-z/z',
                 # content of 'a=a'
                 'a=a/a',
                 # content of 'a=z'
                 'a=z/z',
                ])


class TestCompiledCmpPathByDirblock(TestCmpPathByDirblock):
    """Test the pyrex implementation of cmp_path_by_dirblock"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_cmp_by_dirs(self):
        from bzrlib._dirstate_helpers_c import cmp_path_by_dirblock_c
        return cmp_path_by_dirblock_c


class TestMemRChr(tests.TestCase):
    """Test the pyrex implementation of cmp_path_by_dirblock"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def assertMemRChr(self, expected, s, c):
        from bzrlib._dirstate_helpers_c import _py_memrchr
        self.assertEqual(expected, _py_memrchr(s, c))

    def test_missing(self):
        self.assertMemRChr(None, '', 'a')
        self.assertMemRChr(None, '', 'c')
        self.assertMemRChr(None, 'abcdefghijklm', 'q')
        self.assertMemRChr(None, 'aaaaaaaaaaaaaaaaaaaaaaa', 'b')

    def test_single_entry(self):
        self.assertMemRChr(0, 'abcdefghijklm', 'a')
        self.assertMemRChr(1, 'abcdefghijklm', 'b')
        self.assertMemRChr(2, 'abcdefghijklm', 'c')
        self.assertMemRChr(10, 'abcdefghijklm', 'k')
        self.assertMemRChr(11, 'abcdefghijklm', 'l')
        self.assertMemRChr(12, 'abcdefghijklm', 'm')

    def test_multiple(self):
        self.assertMemRChr(10, 'abcdefjklmabcdefghijklm', 'a')
        self.assertMemRChr(11, 'abcdefjklmabcdefghijklm', 'b')
        self.assertMemRChr(12, 'abcdefjklmabcdefghijklm', 'c')
        self.assertMemRChr(20, 'abcdefjklmabcdefghijklm', 'k')
        self.assertMemRChr(21, 'abcdefjklmabcdefghijklm', 'l')
        self.assertMemRChr(22, 'abcdefjklmabcdefghijklm', 'm')
        self.assertMemRChr(22, 'aaaaaaaaaaaaaaaaaaaaaaa', 'a')

    def test_with_nulls(self):
        self.assertMemRChr(10, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'a')
        self.assertMemRChr(11, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'b')
        self.assertMemRChr(12, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'c')
        self.assertMemRChr(20, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'k')
        self.assertMemRChr(21, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'l')
        self.assertMemRChr(22, 'abc\0\0\0jklmabc\0\0\0ghijklm', 'm')
        self.assertMemRChr(22, 'aaa\0\0\0aaaaaaa\0\0\0aaaaaaa', 'a')
        self.assertMemRChr(9, '\0\0\0\0\0\0\0\0\0\0', '\0')
