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

"""Tests for repository write groups."""

import sys

from bzrlib import errors
from bzrlib.transport import local, memory
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestWriteGroup(TestCaseWithRepository):

    def test_start_write_group_unlocked_needs_write_lock(self):
        repo = self.make_repository('.')
        self.assertRaises(errors.NotWriteLocked, repo.start_write_group)

    def test_start_write_group_read_locked_needs_write_lock(self):
        repo = self.make_repository('.')
        repo.lock_read()
        try:
            self.assertRaises(errors.NotWriteLocked, repo.start_write_group)
        finally:
            repo.unlock()

    def test_start_write_group_write_locked_gets_None(self):
        repo = self.make_repository('.')
        repo.lock_write()
        self.assertEqual(None, repo.start_write_group())
        repo.commit_write_group()
        repo.unlock()

    def test_start_write_group_twice_errors(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        try:
            # don't need a specific exception for now - this is
            # really to be sure it's used right, not for signalling
            # semantic information.
            self.assertRaises(errors.BzrError, repo.start_write_group)
        finally:
            repo.commit_write_group()
            repo.unlock()

    def test_commit_write_group_gets_None(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        self.assertEqual(None, repo.commit_write_group())
        repo.unlock()

    def test_unlock_in_write_group(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        # don't need a specific exception for now - this is
        # really to be sure it's used right, not for signalling
        # semantic information.
        self.assertRaises(errors.BzrError, repo.unlock)
        # after this error occurs, the repository is unlocked, and the write
        # group is gone.  you've had your chance, and you blew it. ;-)
        self.assertFalse(repo.is_locked())
        self.assertRaises(errors.BzrError, repo.commit_write_group)
        self.assertRaises(errors.BzrError, repo.unlock)

    def test_is_in_write_group(self):
        repo = self.make_repository('.')
        self.assertFalse(repo.is_in_write_group())
        repo.lock_write()
        repo.start_write_group()
        self.assertTrue(repo.is_in_write_group())
        repo.commit_write_group()
        self.assertFalse(repo.is_in_write_group())
        # abort also removes the in_write_group status.
        repo.start_write_group()
        self.assertTrue(repo.is_in_write_group())
        repo.abort_write_group()
        self.assertFalse(repo.is_in_write_group())
        repo.unlock()

    def test_abort_write_group_gets_None(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        self.assertEqual(None, repo.abort_write_group())
        repo.unlock()

    def test_abort_write_group_does_not_raise_when_suppressed(self):
        if self.transport_server is local.LocalURLServer:
            self.transport_server = None
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository('repo')
        token = repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        # Damage the repository on the filesystem
        self.get_transport('').rename('repo', 'foo')
        # abort_write_group will not raise an error, because either an
        # exception was not generated, or the exception was caught and
        # suppressed.  See also test_pack_repository's test of the same name.
        self.assertEqual(None, repo.abort_write_group(suppress_errors=True))
        if token is not None:
            repo.leave_lock_in_place()


class TestResumeableWriteGroup(TestCaseWithRepository):

    def make_write_locked_repo(self, relpath='repo'):
        repo = self.make_repository(relpath)
        repo.lock_write()
        self.addCleanup(repo.unlock)
        return repo

    def reopen_repo(self, repo):
        same_repo = repo.bzrdir.open_repository()
        same_repo.lock_write()
        self.addCleanup(same_repo.unlock)
        return same_repo

    def require_suspendable_write_groups(self, reason):
        repo = self.make_repository('__suspend_test')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        try:
            wg_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            repo.abort_write_group()
            raise TestNotApplicable(reason)

    def test_suspend_write_group(self):
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        repo.texts.add_lines(('file-id', 'revid'), (), ['lines'])
        try:
            wg_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            # The contract for repos that don't support suspending write groups
            # is that suspend_write_group raises UnsuspendableWriteGroup, but
            # is otherwise a no-op.  So we can still e.g. abort the write group
            # as usual.
            self.assertTrue(repo.is_in_write_group())
            repo.abort_write_group()
        else:
            # After suspending a write group we are no longer in a write group
            self.assertFalse(repo.is_in_write_group())
            # suspend_write_group returns a list of tokens, which are strs.  If
            # no other write groups were resumed, there will only be one token.
            self.assertEqual(1, len(wg_tokens))
            self.assertIsInstance(wg_tokens[0], str)
            # See also test_pack_repository's test of the same name.

    def test_resume_write_group_then_abort(self):
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        try:
            wg_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            # If the repo does not support suspending write groups, it doesn't
            # support resuming them either.
            repo.abort_write_group()
            self.assertRaises(
                errors.UnsuspendableWriteGroup, repo.resume_write_group, [])
        else:
            #self.assertEqual([], list(repo.texts.keys()))
            same_repo = self.reopen_repo(repo)
            same_repo.resume_write_group(wg_tokens)
            self.assertEqual([text_key], list(same_repo.texts.keys()))
            self.assertTrue(same_repo.is_in_write_group())
            same_repo.abort_write_group()
            self.assertEqual([], list(repo.texts.keys()))
            # See also test_pack_repository's test of the same name.

    def test_multiple_resume_write_group(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        first_key = ('file-id', 'revid')
        repo.texts.add_lines(first_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertTrue(same_repo.is_in_write_group())
        second_key = ('file-id', 'second-revid')
        same_repo.texts.add_lines(second_key, (first_key,), ['more lines'])
        try:
            new_wg_tokens = same_repo.suspend_write_group()
        except:
            e = sys.exc_info()
            same_repo.abort_write_group(suppress_errors=True)
            raise e[0], e[1], e[2]
        self.assertEqual(2, len(new_wg_tokens))
        self.assertSubset(wg_tokens, new_wg_tokens)
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(new_wg_tokens)
        both_keys = set([first_key, second_key])
        self.assertEqual(both_keys, same_repo.texts.keys())
        same_repo.abort_write_group()

    def test_no_op_suspend_resume(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        new_wg_tokens = same_repo.suspend_write_group()
        self.assertEqual(wg_tokens, new_wg_tokens)
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertEqual([text_key], list(same_repo.texts.keys()))
        same_repo.abort_write_group()

    def test_read_after_suspend_fails(self):
        self.require_suspendable_write_groups(
            'Cannot test suspend on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        self.assertEqual([], list(repo.texts.keys()))

    def test_read_after_second_suspend_fails(self):
        self.require_suspendable_write_groups(
            'Cannot test suspend on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.suspend_write_group()
        self.assertEqual([], list(same_repo.texts.keys()))

    def test_read_after_resume_abort_fails(self):
        self.require_suspendable_write_groups(
            'Cannot test suspend on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.abort_write_group()
        self.assertEqual([], list(same_repo.texts.keys()))

    def test_cannot_resume_aborted_write_group(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.abort_write_group()
        same_repo = self.reopen_repo(repo)
        self.assertRaises(
            errors.UnresumableWriteGroup, same_repo.resume_write_group,
            wg_tokens)

    def test_commit_resumed_write_group_no_new_data(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.commit_write_group()
        self.assertEqual([text_key], list(same_repo.texts.keys()))
        self.assertEqual(
            'lines', same_repo.texts.get_record_stream([text_key],
                'unordered', True).next().get_bytes_as('fulltext'))
        self.assertRaises(
            errors.UnresumableWriteGroup, same_repo.resume_write_group,
            wg_tokens)

    def test_commit_resumed_write_group_plus_new_data(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        first_key = ('file-id', 'revid')
        repo.texts.add_lines(first_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        second_key = ('file-id', 'second-revid')
        same_repo.texts.add_lines(second_key, (first_key,), ['more lines'])
        same_repo.commit_write_group()
        self.assertEqual(
            set([first_key, second_key]), set(same_repo.texts.keys()))
        self.assertEqual(
            'lines', same_repo.texts.get_record_stream([first_key],
                'unordered', True).next().get_bytes_as('fulltext'))
        self.assertEqual(
            'more lines', same_repo.texts.get_record_stream([second_key],
                'unordered', True).next().get_bytes_as('fulltext'))

    def make_source_with_delta_record(self):
        # Make a source repository with a delta record in it.
        source_repo = self.make_write_locked_repo('source')
        source_repo.start_write_group()
        key_base = ('file-id', 'base')
        key_delta = ('file-id', 'delta')
        source_repo.texts.add_lines(key_base, (), ['lines\n'])
        source_repo.texts.add_lines(
            key_delta, (key_base,), ['more\n', 'lines\n'])
        source_repo.commit_write_group()
        return source_repo

    def test_commit_resumed_write_group_with_missing_parents(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        source_repo = self.make_source_with_delta_record()
        key_base = ('file-id', 'base')
        key_delta = ('file-id', 'delta')
        # Start a write group, insert just a delta.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        stream = source_repo.texts.get_record_stream(
            [key_delta], 'unordered', False)
        repo.texts.insert_record_stream(stream)
        # It's not commitable due to the missing compression parent.
        self.assertRaises(
            errors.BzrCheckError, repo.commit_write_group)
        # Merely suspending and resuming doesn't make it commitable either.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertRaises(
            errors.BzrCheckError, same_repo.commit_write_group)
        same_repo.abort_write_group()

    def test_commit_resumed_write_group_adding_missing_parents(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        source_repo = self.make_source_with_delta_record()
        key_base = ('file-id', 'base')
        key_delta = ('file-id', 'delta')
        # Start a write group.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        # Suspend it, then resume it.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        # Add a record with a missing compression parent
        stream = source_repo.texts.get_record_stream(
            [key_delta], 'unordered', False)
        same_repo.texts.insert_record_stream(stream)
        # Just like if we'd added that record without a suspend/resume cycle,
        # commit_write_group fails.
        self.assertRaises(
            errors.BzrCheckError, same_repo.commit_write_group)
        same_repo.abort_write_group()

    def test_add_missing_parent_after_resume(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        source_repo = self.make_source_with_delta_record()
        key_base = ('file-id', 'base')
        key_delta = ('file-id', 'delta')
        # Start a write group, insert just a delta.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        stream = source_repo.texts.get_record_stream(
            [key_delta], 'unordered', False)
        repo.texts.insert_record_stream(stream)
        # Suspend it, then resume it.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        # Fill in the missing compression parent.
        stream = source_repo.texts.get_record_stream(
            [key_base], 'unordered', False)
        same_repo.texts.insert_record_stream(stream)
        same_repo.commit_write_group()

    def test_suspend_empty_initial_write_group(self):
        """Suspending a write group with no writes returns an empty token
        list.
        """
        self.require_suspendable_write_groups(
            'Cannot test suspend on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        wg_tokens = repo.suspend_write_group()
        self.assertEqual([], wg_tokens)

    def test_suspend_empty_initial_write_group(self):
        """Resuming an empty token list is equivalent to start_write_group."""
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.resume_write_group([])
        repo.abort_write_group()


