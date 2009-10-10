# Copyright (C) 2004, 2005, 2007 Canonical Ltd
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

"""Tests for branch.push behaviour."""

from cStringIO import StringIO
import os

from bzrlib import (
    branch,
    builtins,
    bzrdir,
    check,
    debug,
    errors,
    push,
    repository,
    tests,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.memorytree import MemoryTree
from bzrlib.revision import NULL_REVISION
from bzrlib.smart import client, server
from bzrlib.smart.repository import SmartServerRepositoryGetParentMap
from bzrlib.tests.per_branch.test_branch import TestCaseWithBranch
from bzrlib.transport import get_transport
from bzrlib.transport.local import LocalURLServer


class TestPush(TestCaseWithBranch):

    def test_push_convergence_simple(self):
        # when revisions are pushed, the left-most accessible parents must
        # become the revision-history.
        mine = self.make_branch_and_tree('mine')
        mine.commit('1st post', rev_id='P1', allow_pointless=True)
        other = mine.bzrdir.sprout('other').open_workingtree()
        other.commit('my change', rev_id='M1', allow_pointless=True)
        mine.merge_from_branch(other.branch)
        mine.commit('merge my change', rev_id='P2')
        result = mine.branch.push(other.branch)
        self.assertEqual(['P1', 'P2'], other.branch.revision_history())
        # result object contains some structured data
        self.assertEqual(result.old_revid, 'M1')
        self.assertEqual(result.new_revid, 'P2')
        # and it can be treated as an integer for compatibility
        self.assertEqual(int(result), 0)

    def test_push_merged_indirect(self):
        # it should be possible to do a push from one branch into another
        # when the tip of the target was merged into the source branch
        # via a third branch - so its buried in the ancestry and is not
        # directly accessible.
        mine = self.make_branch_and_tree('mine')
        mine.commit('1st post', rev_id='P1', allow_pointless=True)
        target = mine.bzrdir.sprout('target').open_workingtree()
        target.commit('my change', rev_id='M1', allow_pointless=True)
        other = mine.bzrdir.sprout('other').open_workingtree()
        other.merge_from_branch(target.branch)
        other.commit('merge my change', rev_id='O2')
        mine.merge_from_branch(other.branch)
        mine.commit('merge other', rev_id='P2')
        mine.branch.push(target.branch)
        self.assertEqual(['P1', 'P2'], target.branch.revision_history())

    def test_push_to_checkout_updates_master(self):
        """Pushing into a checkout updates the checkout and the master branch"""
        master_tree = self.make_branch_and_tree('master')
        checkout = self.make_branch_and_tree('checkout')
        try:
            checkout.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # cant bind this format, the test is irrelevant.
            return
        rev1 = checkout.commit('master')

        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        rev2 = other.commit('other commit')
        # now push, which should update both checkout and master.
        other.branch.push(checkout.branch)
        self.assertEqual([rev1, rev2], checkout.branch.revision_history())
        self.assertEqual([rev1, rev2], master_tree.branch.revision_history())

    def test_push_raises_specific_error_on_master_connection_error(self):
        master_tree = self.make_branch_and_tree('master')
        checkout = self.make_branch_and_tree('checkout')
        try:
            checkout.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # cant bind this format, the test is irrelevant.
            return
        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        # move the branch out of the way on disk to cause a connection
        # error.
        os.rename('master', 'master_gone')
        # try to push, which should raise a BoundBranchConnectionFailure.
        self.assertRaises(errors.BoundBranchConnectionFailure,
                other.branch.push, checkout.branch)

    def test_push_uses_read_lock(self):
        """Push should only need a read lock on the source side."""
        source = self.make_branch_and_tree('source')
        target = self.make_branch('target')

        self.build_tree(['source/a'])
        source.add(['a'])
        source.commit('a')

        source.branch.lock_read()
        try:
            target.lock_write()
            try:
                source.branch.push(target, stop_revision=source.last_revision())
            finally:
                target.unlock()
        finally:
            source.branch.unlock()

    def test_push_within_repository(self):
        """Push from one branch to another inside the same repository."""
        try:
            repo = self.make_repository('repo', shared=True)
        except (errors.IncompatibleFormat, errors.UninitializableFormat):
            # This Branch format cannot create shared repositories
            return
        # This is a little bit trickier because make_branch_and_tree will not
        # re-use a shared repository.
        a_bzrdir = self.make_bzrdir('repo/tree')
        try:
            a_branch = self.branch_format.initialize(a_bzrdir)
        except (errors.UninitializableFormat):
            # Cannot create these branches
            return
        try:
            tree = a_branch.bzrdir.create_workingtree()
        except errors.NotLocalUrl:
            if self.vfs_transport_factory is LocalURLServer:
                # the branch is colocated on disk, we cannot create a checkout.
                # hopefully callers will expect this.
                local_controldir= bzrdir.BzrDir.open(self.get_vfs_only_url('repo/tree'))
                tree = local_controldir.create_workingtree()
            else:
                tree = a_branch.create_checkout('repo/tree', lightweight=True)
        self.build_tree(['repo/tree/a'])
        tree.add(['a'])
        tree.commit('a')

        to_bzrdir = self.make_bzrdir('repo/branch')
        to_branch = self.branch_format.initialize(to_bzrdir)
        tree.branch.push(to_branch)

        self.assertEqual(tree.branch.last_revision(),
                         to_branch.last_revision())

    def test_push_overwrite_of_non_tip_with_stop_revision(self):
        """Combining the stop_revision and overwrite options works.

        This was <https://bugs.launchpad.net/bzr/+bug/234229>.
        """
        source = self.make_branch_and_tree('source')
        target = self.make_branch('target')

        source.commit('1st commit')
        source.branch.push(target)
        source.commit('2nd commit', rev_id='rev-2')
        source.commit('3rd commit')

        source.branch.push(target, stop_revision='rev-2', overwrite=True)
        self.assertEqual('rev-2', target.last_revision())

    def test_push_with_default_stacking_does_not_create_broken_branch(self):
        """Pushing a new standalone branch works even when there's a default
        stacking policy at the destination.

        The new branch will preserve the repo format (even if it isn't the
        default for the branch), and will be stacked when the repo format
        allows (which means that the branch format isn't necessarly preserved).
        """
        if isinstance(self.branch_format, branch.BzrBranchFormat4):
            raise tests.TestNotApplicable('Not a metadir format.')
        if isinstance(self.branch_format, branch.BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise tests.TestSkipped(
                "BranchBuilder can't make reference branches.")
        # Make a branch called "local" in a stackable repository
        # The branch has 3 revisions:
        #   - rev-1, adds a file
        #   - rev-2, no changes
        #   - rev-3, modifies the file.
        repo = self.make_repository('repo', shared=True, format='1.6')
        builder = self.make_branch_builder('repo/local')
        builder.start_series()
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'root-id', 'directory', '')),
            ('add', ('filename', 'f-id', 'file', 'content\n'))])
        builder.build_snapshot('rev-2', ['rev-1'], [])
        builder.build_snapshot('rev-3', ['rev-2'],
            [('modify', ('f-id', 'new-content\n'))])
        builder.finish_series()
        trunk = builder.get_branch()
        # Sprout rev-1 to "trunk", so that we can stack on it.
        trunk.bzrdir.sprout(self.get_url('trunk'), revision_id='rev-1')
        # Set a default stacking policy so that new branches will automatically
        # stack on trunk.
        self.make_bzrdir('.').get_config().set_default_stack_on('trunk')
        # Push rev-2 to a new branch "remote".  It will be stacked on "trunk".
        output = StringIO()
        push._show_push_branch(trunk, 'rev-2', self.get_url('remote'), output)
        # Push rev-3 onto "remote".  If "remote" not stacked and is missing the
        # fulltext record for f-id @ rev-1, then this will fail.
        remote_branch = Branch.open(self.get_url('remote'))
        trunk.push(remote_branch)
        check.check_dwim(remote_branch.base, False, True, True)

    def test_no_get_parent_map_after_insert_stream(self):
        # Effort test for bug 331823
        self.setup_smart_server_with_call_log()
        # Make a local branch with four revisions.  Four revisions because:
        # one to push, one there for _walk_to_common_revisions to find, one we
        # don't want to access, one for luck :)
        if isinstance(self.branch_format, branch.BranchReferenceFormat):
            # This test could in principle apply to BranchReferenceFormat, but
            # make_branch_builder doesn't support it.
            raise tests.TestSkipped(
                "BranchBuilder can't make reference branches.")
        try:
            builder = self.make_branch_builder('local')
        except (errors.TransportNotPossible, errors.UninitializableFormat):
            raise tests.TestNotApplicable('format not directly constructable')
        builder.start_series()
        builder.build_snapshot('first', None, [
            ('add', ('', 'root-id', 'directory', ''))])
        builder.build_snapshot('second', ['first'], [])
        builder.build_snapshot('third', ['second'], [])
        builder.build_snapshot('fourth', ['third'], [])
        builder.finish_series()
        local = builder.get_branch()
        local = branch.Branch.open(self.get_vfs_only_url('local'))
        # Initial push of three revisions
        remote_bzrdir = local.bzrdir.sprout(
            self.get_url('remote'), revision_id='third')
        remote = remote_bzrdir.open_branch()
        # Push fourth revision
        self.reset_smart_call_log()
        self.disableOptimisticGetParentMap()
        self.assertFalse(local.is_locked())
        local.push(remote)
        hpss_call_names = [item.call.method for item in self.hpss_calls]
        self.assertTrue('Repository.insert_stream_1.19' in hpss_call_names)
        insert_stream_idx = hpss_call_names.index(
            'Repository.insert_stream_1.19')
        calls_after_insert_stream = hpss_call_names[insert_stream_idx:]
        # After inserting the stream the client has no reason to query the
        # remote graph any further.
        self.assertEqual(
            ['Repository.insert_stream_1.19', 'Repository.insert_stream_1.19',
             'get', 'Branch.set_last_revision_info', 'Branch.unlock'],
            calls_after_insert_stream)

    def disableOptimisticGetParentMap(self):
        # Tweak some class variables to stop remote get_parent_map calls asking
        # for or receiving more data than the caller asked for.
        old_flag = SmartServerRepositoryGetParentMap.no_extra_results
        inter_class = repository.InterRepository
        old_batch_size = inter_class._walk_to_common_revisions_batch_size
        inter_class._walk_to_common_revisions_batch_size = 1
        SmartServerRepositoryGetParentMap.no_extra_results = True
        def reset_values():
            SmartServerRepositoryGetParentMap.no_extra_results = old_flag
            inter_class._walk_to_common_revisions_batch_size = old_batch_size
        self.addCleanup(reset_values)


class TestPushHook(TestCaseWithBranch):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithBranch.setUp(self)

    def capture_post_push_hook(self, result):
        """Capture post push hook calls to self.hook_calls.

        The call is logged, as is some state of the two branches.
        """
        if result.local_branch:
            local_locked = result.local_branch.is_locked()
            local_base = result.local_branch.base
        else:
            local_locked = None
            local_base = None
        self.hook_calls.append(
            ('post_push', result.source_branch, local_base,
             result.master_branch.base,
             result.old_revno, result.old_revid,
             result.new_revno, result.new_revid,
             result.source_branch.is_locked(), local_locked,
             result.master_branch.is_locked()))

    def test_post_push_empty_history(self):
        target = self.make_branch('target')
        source = self.make_branch('source')
        Branch.hooks.install_named_hook('post_push',
                                        self.capture_post_push_hook, None)
        source.push(target)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_push', source, None, target.base, 0, NULL_REVISION,
             0, NULL_REVISION, True, None, True)
            ],
            self.hook_calls)

    def test_post_push_bound_branch(self):
        # pushing to a bound branch should pass in the master branch to the
        # hook, allowing the correct number of emails to be sent, while still
        # allowing hooks that want to modify the target to do so to both
        # instances.
        target = self.make_branch('target')
        local = self.make_branch('local')
        try:
            local.bind(target)
        except errors.UpgradeRequired:
            # We can't bind this format to itself- typically it is the local
            # branch that doesn't support binding.  As of May 2007
            # remotebranches can't be bound.  Let's instead make a new local
            # branch of the default type, which does allow binding.
            # See https://bugs.launchpad.net/bzr/+bug/112020
            local = BzrDir.create_branch_convenience('local2')
            local.bind(target)
        source = self.make_branch('source')
        Branch.hooks.install_named_hook('post_push',
                                        self.capture_post_push_hook, None)
        source.push(local)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_push', source, local.base, target.base, 0, NULL_REVISION,
             0, NULL_REVISION, True, True, True)
            ],
            self.hook_calls)

    def test_post_push_nonempty_history(self):
        target = self.make_branch_and_memory_tree('target')
        target.lock_write()
        target.add('')
        rev1 = target.commit('rev 1')
        target.unlock()
        sourcedir = target.bzrdir.clone(self.get_url('source'))
        source = MemoryTree.create_on_branch(sourcedir.open_branch())
        rev2 = source.commit('rev 2')
        Branch.hooks.install_named_hook('post_push',
                                        self.capture_post_push_hook, None)
        source.branch.push(target.branch)
        # with nothing there we should still get a notification, and
        # have both branches locked at the notification time.
        self.assertEqual([
            ('post_push', source.branch, None, target.branch.base, 1, rev1,
             2, rev2, True, None, True)
            ],
            self.hook_calls)


class EmptyPushSmartEffortTests(TestCaseWithBranch):
    """Tests that a push of 0 revisions should make a limited number of smart
    protocol RPCs.
    """

    def setUp(self):
        # Skip some scenarios that don't apply to these tests.
        if (self.transport_server is not None and
            issubclass(self.transport_server, server.SmartTCPServer)):
            raise tests.TestNotApplicable(
                'Does not apply when remote backing branch is also '
                'a smart branch')
        if isinstance(self.branch_format, branch.BzrBranchFormat4):
            raise tests.TestNotApplicable(
                'Branch format 4 is not usable via HPSS.')
        super(EmptyPushSmartEffortTests, self).setUp()
        # Create a smart server that publishes whatever the backing VFS server
        # does.
        self.smart_server = server.SmartTCPServer_for_testing()
        self.start_server(self.smart_server, self.get_server())
        # Make two empty branches, 'empty' and 'target'.
        self.empty_branch = self.make_branch('empty')
        self.make_branch('target')
        # Log all HPSS calls into self.hpss_calls.
        client._SmartClient.hooks.install_named_hook(
            'call', self.capture_hpss_call, None)
        self.hpss_calls = []

    def capture_hpss_call(self, params):
        self.hpss_calls.append(params.method)

    def test_empty_branch_api(self):
        """The branch_obj.push API should make a limited number of HPSS calls.
        """
        transport = get_transport(self.smart_server.get_url()).clone('target')
        target = Branch.open_from_transport(transport)
        self.empty_branch.push(target)
        self.assertEqual(
            ['BzrDir.open_2.1',
             'BzrDir.open_branchV2',
             'BzrDir.find_repositoryV3',
             'Branch.get_stacked_on_url',
             'Branch.lock_write',
             'Branch.last_revision_info',
             'Branch.unlock'],
            self.hpss_calls)

    def test_empty_branch_command(self):
        """The 'bzr push' command should make a limited number of HPSS calls.
        """
        cmd = builtins.cmd_push()
        cmd.outf = tests.StringIOWrapper()
        cmd.run(
            directory=self.get_url('empty'),
            location=self.smart_server.get_url() + 'target')
        # HPSS calls as of 2008/09/22:
        # [BzrDir.open, BzrDir.open_branch, BzrDir.find_repositoryV2,
        # Branch.get_stacked_on_url, get, get, Branch.lock_write,
        # Branch.last_revision_info, Branch.unlock]
        self.assertTrue(len(self.hpss_calls) <= 9, self.hpss_calls)


class TestLossyPush(TestCaseWithBranch):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithBranch.setUp(self)

    def test_lossy_push_raises_same_vcs(self):
        target = self.make_branch('target')
        source = self.make_branch('source')
        self.assertRaises(errors.LossyPushToSameVCS, source.lossy_push, target)
