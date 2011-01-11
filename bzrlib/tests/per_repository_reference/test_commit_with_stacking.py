# Copyright (C) 2010, 2011 Canonical Ltd
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


from bzrlib import (
    errors,
    remote,
    urlutils,
    )
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestCommitWithStacking(TestCaseWithRepository):

    r1_key = ('rev1-id',)
    r2_key = ('rev2-id',)

    def make_stacked_target(self):
        base_tree = self.make_branch_and_tree('base')
        self.build_tree(['base/f1.txt'])
        base_tree.add(['f1.txt'], ['f1.txt-id'])
        base_tree.commit('initial', rev_id=self.r1_key[0])
        self.build_tree(['base/f2.txt'])
        base_tree.add(['f2.txt'], ['f2.txt-id'])
        base_tree.commit('base adds f2', rev_id=self.r2_key[0])
        stacked_url = urlutils.join(base_tree.branch.base, '../stacked')
        stacked_bzrdir = base_tree.bzrdir.sprout(stacked_url,
            stacked=True)
        if isinstance(stacked_bzrdir, remote.RemoteBzrDir):
            stacked_branch = stacked_bzrdir.open_branch()
            stacked_tree = stacked_branch.create_checkout('stacked',
                lightweight=True)
        else:
            stacked_tree = stacked_bzrdir.open_workingtree()
        return base_tree, stacked_tree

    def get_only_repo(self, tree):
        """Open just the repository used by this tree.

        This returns a read locked Repository object without any stacking
        fallbacks.
        """
        repo = tree.branch.repository.bzrdir.open_repository()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        return repo

    def assertPresent(self, expected, vf, keys):
        """Check which of the supplied keys are present."""
        parent_map = vf.get_parent_map(keys)
        self.assertEqual(sorted(expected), sorted(parent_map))

    def test_simple_commit(self):
        base_tree, stacked_tree = self.make_stacked_target()
        self.assertEqual(1,
                len(stacked_tree.branch.repository._fallback_repositories))
        self.build_tree_contents([('stacked/f1.txt', 'new content\n')])
        stacked_tree.commit('new content', rev_id='new-rev-id')
        # We open the repository without fallbacks to ensure the data is
        # locally true
        stacked_only_repo = self.get_only_repo(stacked_tree)
        # We should have the immediate parent inventory available, but not the
        # grandparent's
        self.assertPresent([self.r2_key],
            stacked_only_repo.inventories, [self.r1_key, self.r2_key])
        # And we should be able to pull this revision into another stacked
        # branch
        stacked2_branch = base_tree.bzrdir.sprout('stacked2',
                                                  stacked=True).open_branch()
        stacked2_branch.repository.fetch(stacked_only_repo,
                                         revision_id='new-rev-id')

    def test_merge_commit(self):
        base_tree, stacked_tree = self.make_stacked_target()
        self.build_tree_contents([('base/f1.txt', 'new content\n')])
        r3_key = ('rev3-id',)
        base_tree.commit('second base', rev_id=r3_key[0])
        to_be_merged_tree = base_tree.bzrdir.sprout('merged'
            ).open_workingtree()
        self.build_tree(['merged/f2.txt'])
        to_be_merged_tree.add(['f2.txt'], ['f2.txt-id'])
        to_merge_key = ('to-merge-rev-id',)
        to_be_merged_tree.commit('new-to-be-merged', rev_id=to_merge_key[0])
        stacked_tree.merge_from_branch(to_be_merged_tree.branch)
        merged_key = ('merged-rev-id',)
        stacked_tree.commit('merge', rev_id=merged_key[0])
        # to-merge isn't in base, so it should be in stacked.
        # rev3-id is a parent of a revision we have, so we should have the
        # inventory, but not the revision.
        # merged has a parent of r2, so we should also have r2's
        # inventory-but-not-revision.
        # Nothing has r1 directly, so we shouldn't have anything present for it
        stacked_only_repo = self.get_only_repo(stacked_tree)
        all_keys = [self.r1_key, self.r2_key, r3_key, to_merge_key, merged_key]
        self.assertPresent([to_merge_key, merged_key],
                           stacked_only_repo.revisions, all_keys)
        self.assertPresent([self.r2_key, r3_key, to_merge_key, merged_key],
                           stacked_only_repo.inventories, all_keys)

    def test_merge_from_master(self):
        base_tree, stacked_tree = self.make_stacked_target()
        self.build_tree_contents([('base/f1.txt', 'new content\n')])
        r3_key = ('rev3-id',)
        base_tree.commit('second base', rev_id=r3_key[0])
        stacked_tree.merge_from_branch(base_tree.branch)
        merged_key = ('merged-rev-id',)
        stacked_tree.commit('merge', rev_id=merged_key[0])
        all_keys = [self.r1_key, self.r2_key, r3_key, merged_key]
        # We shouldn't have any of the base revisions in the local repo, but we
        # should have both base inventories.
        stacked_only_repo = self.get_only_repo(stacked_tree)
        self.assertPresent([merged_key],
                           stacked_only_repo.revisions, all_keys)
        self.assertPresent([self.r2_key, r3_key, merged_key],
                           stacked_only_repo.inventories, all_keys)

    def test_multi_stack(self):
        """base + stacked + stacked-on-stacked"""
        base_tree, stacked_tree = self.make_stacked_target()
        self.build_tree(['stacked/f3.txt'])
        stacked_tree.add(['f3.txt'], ['f3.txt-id'])
        stacked_key = ('stacked-rev-id',)
        stacked_tree.commit('add f3', rev_id=stacked_key[0])
        stacked_only_repo = self.get_only_repo(stacked_tree)
        self.assertPresent([self.r2_key], stacked_only_repo.inventories,
                           [self.r1_key, self.r2_key])
        # This ensures we get a Remote URL, rather than a local one.
        stacked2_url = urlutils.join(base_tree.branch.base, '../stacked2')
        stacked2_bzrdir = stacked_tree.bzrdir.sprout(stacked2_url,
                            revision_id=self.r1_key[0],
                            stacked=True)
        if isinstance(stacked2_bzrdir, remote.RemoteBzrDir):
            stacked2_branch = stacked2_bzrdir.open_branch()
            stacked2_tree = stacked2_branch.create_checkout('stacked2',
                lightweight=True)
        else:
            stacked2_tree = stacked2_bzrdir.open_workingtree()
        # stacked2 is stacked on stacked, but its content is rev1, so
        # it needs to pull the basis information from a fallback-of-fallback.
        self.build_tree(['stacked2/f3.txt'])
        stacked2_only_repo = self.get_only_repo(stacked2_tree)
        self.assertPresent([], stacked2_only_repo.inventories,
                           [self.r1_key, self.r2_key])
        stacked2_tree.add(['f3.txt'], ['f3.txt-id'])
        stacked2_tree.commit('add f3', rev_id='stacked2-rev-id')
        # We added data to this read-locked repo, so refresh it
        stacked2_only_repo.refresh_data()
        self.assertPresent([self.r1_key], stacked2_only_repo.inventories,
                           [self.r1_key, self.r2_key])

    def test_commit_with_ghosts_fails(self):
        base_tree, stacked_tree = self.make_stacked_target()
        stacked_tree.set_parent_ids([stacked_tree.last_revision(),
                                     'ghost-rev-id'])
        self.assertRaises(errors.BzrError,
            stacked_tree.commit, 'failed_commit')
