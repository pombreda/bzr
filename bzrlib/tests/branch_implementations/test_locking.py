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

"""Test locks across all branch implemenations"""

from bzrlib import errors
from bzrlib.branch import BzrBranchFormat4
from bzrlib.remote import RemoteBranchFormat
from bzrlib.tests import TestSkipped
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch
from bzrlib.tests.lock_helpers import TestPreventLocking, LockWrapper


class TestBranchLocking(TestCaseWithBranch):

    def setUp(self):
        TestCaseWithBranch.setUp(self)
        self.reduceLockdirTimeout()

    def get_instrumented_branch(self):
        """Get a Branch object which has been instrumented"""
        # TODO: jam 20060630 It may be that not all formats have a 
        # 'control_files' member. So we should fail gracefully if
        # not there. But assuming it has them lets us test the exact 
        # lock/unlock order.
        if isinstance(self.branch_format, RemoteBranchFormat):
            raise TestSkipped(
                "RemoteBranches don't have 'control_files'.")
        self.locks = []
        b = LockWrapper(self.locks, self.get_branch(), 'b')
        b.repository = LockWrapper(self.locks, b.repository, 'r')
        bcf = b.control_files
        rcf = b.repository.control_files

        # Look out for branch types that reuse their control files
        self.combined_control = bcf is rcf

        b.control_files = LockWrapper(self.locks, b.control_files, 'bc')
        b.repository.control_files = \
            LockWrapper(self.locks, b.repository.control_files, 'rc')
        return b

    def test_01_lock_read(self):
        # Test that locking occurs in the correct order
        b = self.get_instrumented_branch()

        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())
        b.lock_read()
        try:
            self.assertTrue(b.is_locked())
            self.assertTrue(b.repository.is_locked())
        finally:
            b.unlock()
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lr', True),
                          ('r', 'lr', True),
                          ('rc', 'lr', True),
                          ('bc', 'lr', True),
                          ('b', 'ul', True),
                          ('bc', 'ul', True),
                          ('r', 'ul', True),
                          ('rc', 'ul', True),
                         ], self.locks)

    def test_02_lock_write(self):
        # Test that locking occurs in the correct order
        b = self.get_instrumented_branch()

        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())
        b.lock_write()
        try:
            self.assertTrue(b.is_locked())
            self.assertTrue(b.repository.is_locked())
        finally:
            b.unlock()
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lw', True),
                          ('r', 'lw', True),
                          ('rc', 'lw', True),
                          ('bc', 'lw', True),
                          ('b', 'ul', True),
                          ('bc', 'ul', True),
                          ('r', 'ul', True),
                          ('rc', 'ul', True),
                         ], self.locks)

    def test_03_lock_fail_unlock_repo(self):
        # Make sure branch.unlock() is called, even if there is a
        # failure while unlocking the repository.
        b = self.get_instrumented_branch()
        b.repository.disable_unlock()

        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())
        b.lock_write()
        try:
            self.assertTrue(b.is_locked())
            self.assertTrue(b.repository.is_locked())
            self.assertRaises(TestPreventLocking, b.unlock)
            if self.combined_control:
                self.assertTrue(b.is_locked())
            else:
                self.assertFalse(b.is_locked())
            self.assertTrue(b.repository.is_locked())

            # We unlock the branch control files, even if 
            # we fail to unlock the repository
            self.assertEqual([('b', 'lw', True),
                              ('r', 'lw', True),
                              ('rc', 'lw', True),
                              ('bc', 'lw', True),
                              ('b', 'ul', True),
                              ('bc', 'ul', True),
                              ('r', 'ul', False), 
                             ], self.locks)

        finally:
            # For cleanup purposes, make sure we are unlocked
            b.repository._other.unlock()

    def test_04_lock_fail_unlock_control(self):
        # Make sure repository.unlock() is called, if we fail to unlock self
        b = self.get_instrumented_branch()
        b.control_files.disable_unlock()

        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())
        b.lock_write()
        try:
            self.assertTrue(b.is_locked())
            self.assertTrue(b.repository.is_locked())
            self.assertRaises(TestPreventLocking, b.unlock)
            self.assertTrue(b.is_locked())
            if self.combined_control:
                self.assertTrue(b.repository.is_locked())
            else:
                self.assertFalse(b.repository.is_locked())

            # We unlock the repository even if 
            # we fail to unlock the control files
            self.assertEqual([('b', 'lw', True),
                              ('r', 'lw', True),
                              ('rc', 'lw', True),
                              ('bc', 'lw', True),
                              ('b', 'ul', True),
                              ('bc', 'ul', False),
                              ('r', 'ul', True), 
                              ('rc', 'ul', True), 
                             ], self.locks)

        finally:
            # For cleanup purposes, make sure we are unlocked
            b.control_files._other.unlock()

    def test_05_lock_read_fail_repo(self):
        # Test that the branch is not locked if it cannot lock the repository
        b = self.get_instrumented_branch()
        b.repository.disable_lock_read()

        self.assertRaises(TestPreventLocking, b.lock_read)
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lr', True),
                          ('r', 'lr', False), 
                         ], self.locks)

    def test_06_lock_write_fail_repo(self):
        # Test that the branch is not locked if it cannot lock the repository
        b = self.get_instrumented_branch()
        b.repository.disable_lock_write()

        self.assertRaises(TestPreventLocking, b.lock_write)
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lw', True),
                          ('r', 'lw', False), 
                         ], self.locks)

    def test_07_lock_read_fail_control(self):
        # Test the repository is unlocked if we can't lock self
        b = self.get_instrumented_branch()
        b.control_files.disable_lock_read()

        self.assertRaises(TestPreventLocking, b.lock_read)
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lr', True),
                          ('r', 'lr', True),
                          ('rc', 'lr', True),
                          ('bc', 'lr', False),
                          ('r', 'ul', True),
                          ('rc', 'ul', True),
                         ], self.locks)

    def test_08_lock_write_fail_control(self):
        # Test the repository is unlocked if we can't lock self
        b = self.get_instrumented_branch()
        b.control_files.disable_lock_write()

        self.assertRaises(TestPreventLocking, b.lock_write)
        self.assertFalse(b.is_locked())
        self.assertFalse(b.repository.is_locked())

        self.assertEqual([('b', 'lw', True),
                          ('r', 'lw', True),
                          ('rc', 'lw', True),
                          ('bc', 'lw', False),
                          ('r', 'ul', True),
                          ('rc', 'ul', True),
                         ], self.locks)

    def test_lock_write_returns_None_refuses_token(self):
        branch = self.make_branch('b')
        token = branch.lock_write()
        try:
            if token is not None:
                # This test does not apply, because this lockable supports
                # tokens.
                return
            self.assertRaises(errors.TokenLockingNotSupported,
                              branch.lock_write, token='token')
        finally:
            branch.unlock()

    def test_reentering_lock_write_raises_on_token_mismatch(self):
        branch = self.make_branch('b')
        token = branch.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            different_branch_token = token + 'xxx'
            # Re-using the same lockable instance with a different branch token
            # will raise TokenMismatch.
            self.assertRaises(errors.TokenMismatch,
                              branch.lock_write,
                              token=different_branch_token)
        finally:
            branch.unlock()

    def test_lock_write_with_nonmatching_token(self):
        branch = self.make_branch('b')
        token = branch.lock_write()
        try:
            if token is None:
                # This test does not apply, because this branch refuses
                # tokens.
                return
            different_branch_token = token + 'xxx'

            new_branch = branch.bzrdir.open_branch()
            # We only want to test the relocking abilities of branch, so use the
            # existing repository object which is already locked.
            new_branch.repository = branch.repository
            self.assertRaises(errors.TokenMismatch,
                              new_branch.lock_write,
                              token=different_branch_token)
        finally:
            branch.unlock()


    def test_lock_write_with_matching_token(self):
        """Test that a branch can be locked with a token, if it is already
        locked by that token."""
        branch = self.make_branch('b')
        token = branch.lock_write()
        try:
            if token is None:
                # This test does not apply, because this branch refuses tokens.
                return
            # The same instance will accept a second lock_write if the specified
            # token matches.
            branch.lock_write(token=token)
            branch.unlock()
            # Calling lock_write on a new instance for the same lockable will
            # also succeed.
            new_branch = branch.bzrdir.open_branch()
            # We only want to test the relocking abilities of branch, so use the
            # existing repository object which is already locked.
            new_branch.repository = branch.repository
            new_branch.lock_write(token=token)
            new_branch.unlock()
        finally:
            branch.unlock()

    def test_unlock_after_lock_write_with_token(self):
        # If lock_write did not physically acquire the lock (because it was
        # passed some tokens), then unlock should not physically release it.
        branch = self.make_branch('b')
        token = branch.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            new_branch = branch.bzrdir.open_branch()
            # We only want to test the relocking abilities of branch, so use the
            # existing repository object which is already locked.
            new_branch.repository = branch.repository
            new_branch.lock_write(token=token)
            new_branch.unlock()
            self.assertTrue(branch.get_physical_lock_status()) #XXX
        finally:
            branch.unlock()

    def test_lock_write_with_token_fails_when_unlocked(self):
        # First, lock and then unlock to get superficially valid tokens.  This
        # mimics a likely programming error, where a caller accidentally tries
        # to lock with a token that is no longer valid (because the original
        # lock was released).
        branch = self.make_branch('b')
        token = branch.lock_write()
        branch.unlock()
        if token is None:
            # This test does not apply, because this lockable refuses
            # tokens.
            return

        self.assertRaises(errors.TokenMismatch,
                          branch.lock_write, token=token)

    def test_lock_write_reenter_with_token(self):
        branch = self.make_branch('b')
        token = branch.lock_write()
        try:
            if token is None:
                # This test does not apply, because this lockable refuses
                # tokens.
                return
            # Relock with a token.
            branch.lock_write(token=token)
            branch.unlock()
        finally:
            branch.unlock()
        # The lock should be unlocked on disk.  Verify that with a new lock
        # instance.
        new_branch = branch.bzrdir.open_branch()
        # Calling lock_write now should work, rather than raise LockContention.
        new_branch.lock_write()
        new_branch.unlock()

    def test_leave_lock_in_place(self):
        branch = self.make_branch('b')
        # Lock the branch, then use leave_lock_in_place so that when we
        # unlock the branch the lock is still held on disk.
        token = branch.lock_write()
        try:
            if token is None:
                # This test does not apply, because this repository refuses lock
                # tokens.
                self.assertRaises(NotImplementedError,
                                  branch.leave_lock_in_place)
                return
            branch.leave_lock_in_place()
        finally:
            branch.unlock()
        # We should be unable to relock the repo.
        self.assertRaises(errors.LockContention, branch.lock_write)

    def test_dont_leave_lock_in_place(self):
        branch = self.make_branch('b')
        # Create a lock on disk.
        token = branch.lock_write()
        try:
            if token is None:
                # This test does not apply, because this branch refuses lock
                # tokens.
                self.assertRaises(NotImplementedError,
                                  branch.dont_leave_lock_in_place)
                return
            try:
                branch.leave_lock_in_place()
            except NotImplementedError:
                # This branch doesn't support this API.
                return
            branch.repository.leave_lock_in_place()
            repo_token = branch.repository.lock_write()
            branch.repository.unlock()
        finally:
            branch.unlock()
        # Reacquire the lock (with a different branch object) by using the
        # tokens.
        new_branch = branch.bzrdir.open_branch()
        # We have to explicitly lock the repository first.
        new_branch.repository.lock_write(token=repo_token)
        new_branch.lock_write(token=token)
        # Now we don't need our own repository lock anymore (the branch is
        # holding it for us).
        new_branch.repository.unlock()
        # Call dont_leave_lock_in_place, so that the lock will be released by
        # this instance, even though the lock wasn't originally acquired by it.
        new_branch.dont_leave_lock_in_place()
        new_branch.repository.dont_leave_lock_in_place()
        new_branch.unlock()
        # Now the branch (and repository) is unlocked.  Test this by locking it
        # without tokens.
        branch.lock_write()
        branch.unlock()

    def test_lock_read_then_unlock(self):
        # Calling lock_read then unlocking should work without errors.
        branch = self.make_branch('b')
        branch.lock_read()
        branch.unlock()

    def test_lock_write_locks_repo_too(self):
        if isinstance(self.branch_format, BzrBranchFormat4):
            # Branch format 4 is combined with the repository, so this test
            # doesn't apply.
            return
        branch = self.make_branch('b')
        branch = branch.bzrdir.open_branch()
        branch.lock_write()
        try:
            # Now the branch.repository is locked, so we can't lock it with a new
            # repository without a token.
            new_repo = branch.bzrdir.open_repository()
            self.assertRaises(errors.LockContention, new_repo.lock_write)
            # We can call lock_write on the original repository object though,
            # because it is already locked.
            branch.repository.lock_write()
            branch.repository.unlock()
        finally:
            branch.unlock()
