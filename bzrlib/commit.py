# Copyright (C) 2005 Canonical Ltd
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


# XXX: Can we do any better about making interrupted commits change
# nothing?  Perhaps the best approach is to integrate commit of
# AtomicFiles with releasing the lock on the Branch.

# TODO: Separate 'prepare' phase where we find a list of potentially
# committed files.  We then can then pause the commit to prompt for a
# commit message, knowing the summary will be the same as what's
# actually used for the commit.  (But perhaps simpler to simply get
# the tree status, then use that for a selective commit?)

# The newly committed revision is going to have a shape corresponding
# to that of the working inventory.  Files that are not in the
# working tree and that were in the predecessor are reported as
# removed --- this can include files that were either removed from the
# inventory or deleted in the working tree.  If they were only
# deleted from disk, they are removed from the working inventory.

# We then consider the remaining entries, which will be in the new
# version.  Directory entries are simply copied across.  File entries
# must be checked to see if a new version of the file should be
# recorded.  For each parent revision inventory, we check to see what
# version of the file was present.  If the file was present in at
# least one tree, and if it was the same version in all the trees,
# then we can just refer to that version.  Otherwise, a new version
# representing the merger of the file versions must be added.

# TODO: Update hashcache before and after - or does the WorkingTree
# look after that?

# This code requires all merge parents to be present in the branch.
# We could relax this but for the sake of simplicity the constraint is
# here for now.  It's not totally clear to me how we'd know which file
# need new text versions if some parents are absent.  -- mbp 20050915

# TODO: Rather than mashing together the ancestry and storing it back,
# perhaps the weave should have single method which does it all in one
# go, avoiding a lot of redundant work.

# TODO: Perhaps give a warning if one of the revisions marked as
# merged is already in the ancestry, and then don't record it as a
# distinct parent.

# TODO: If the file is newly merged but unchanged from the version it
# merges from, then it should still be reported as newly added
# relative to the basis revision.


import os
import re
import sys
import time
import pdb

from binascii import hexlify
from cStringIO import StringIO

from bzrlib.osutils import (local_time_offset, username,
                            rand_bytes, compact_date, user_email,
                            kind_marker, is_inside_any, quotefn,
                            sha_string, sha_strings, sha_file, isdir, isfile,
                            split_lines)
from bzrlib.branch import gen_file_id
from bzrlib.errors import (BzrError, PointlessCommit,
                           HistoryMissing,
                           ConflictsInTree
                           )
from bzrlib.revision import Revision
from bzrlib.trace import mutter, note, warning
from bzrlib.xml5 import serializer_v5
from bzrlib.inventory import Inventory
from bzrlib.weave import Weave
from bzrlib.weavefile import read_weave, write_weave_v5
from bzrlib.atomicfile import AtomicFile


def commit(*args, **kwargs):
    """Commit a new revision to a branch.

    Function-style interface for convenience of old callers.

    New code should use the Commit class instead.
    """
    ## XXX: Remove this in favor of Branch.commit?
    Commit().commit(*args, **kwargs)


class NullCommitReporter(object):
    """I report on progress of a commit."""
    def added(self, path):
        pass

    def removed(self, path):
        pass

    def renamed(self, old_path, new_path):
        pass


class ReportCommitToLog(NullCommitReporter):
    def added(self, path):
        note('added %s', path)

    def removed(self, path):
        note('removed %s', path)

    def renamed(self, old_path, new_path):
        note('renamed %s => %s', old_path, new_path)


class Commit(object):
    """Task of committing a new revision.

    This is a MethodObject: it accumulates state as the commit is
    prepared, and then it is discarded.  It doesn't represent
    historical revisions, just the act of recording a new one.

            missing_ids
            Modified to hold a list of files that have been deleted from
            the working directory; these should be removed from the
            working inventory.
    """
    def __init__(self,
                 reporter=None):
        if reporter is not None:
            self.reporter = reporter
        else:
            self.reporter = NullCommitReporter()

        
    def commit(self,
               branch, message,
               timestamp=None,
               timezone=None,
               committer=None,
               specific_files=None,
               rev_id=None,
               allow_pointless=True,
               verbose=False):
        """Commit working copy as a new revision.

        timestamp -- if not None, seconds-since-epoch for a
             postdated/predated commit.

        specific_files -- If true, commit only those files.

        rev_id -- If set, use this as the new revision id.
            Useful for test or import commands that need to tightly
            control what revisions are assigned.  If you duplicate
            a revision id that exists elsewhere it is your own fault.
            If null (default), a time/random revision id is generated.

        allow_pointless -- If true (default), commit even if nothing
            has changed and no merges are recorded.
        """
        mutter('preparing to commit')

        self.branch = branch
        self.weave_store = branch.weave_store
        self.rev_id = rev_id
        self.specific_files = specific_files
        self.allow_pointless = allow_pointless

        if timestamp is None:
            self.timestamp = time.time()
        else:
            self.timestamp = long(timestamp)
            
        if rev_id is None:
            self.rev_id = _gen_revision_id(self.branch, self.timestamp)
        else:
            self.rev_id = rev_id

        if committer is None:
            self.committer = username(self.branch)
        else:
            assert isinstance(committer, basestring), type(committer)
            self.committer = committer

        if timezone is None:
            self.timezone = local_time_offset()
        else:
            self.timezone = int(timezone)

        assert isinstance(message, basestring), type(message)
        self.message = message
        self._escape_commit_message()

        self.branch.lock_write()
        try:
            self.work_tree = self.branch.working_tree()
            self.work_inv = self.work_tree.inventory
            self.basis_tree = self.branch.basis_tree()
            self.basis_inv = self.basis_tree.inventory

            self._gather_parents()
            if len(self.parents) > 1 and self.specific_files:
                raise NotImplementedError('selected-file commit of merges is not supported yet')
            self._check_parents_present()
            
            self._remove_deleted()
            self._populate_new_inv()
            self._store_snapshot()
            self._report_deletes()

            if not (self.allow_pointless
                    or len(self.parents) > 1
                    or self.new_inv != self.basis_inv):
                raise PointlessCommit()

            if len(list(self.work_tree.iter_conflicts()))>0:
                raise ConflictsInTree

            self._record_inventory()
            self._record_ancestry()
            self._make_revision()
            note('committed r%d {%s}', (self.branch.revno() + 1),
                 self.rev_id)
            self.branch.append_revision(self.rev_id)
            self.branch.set_pending_merges([])
        finally:
            self.branch.unlock()

    def _record_inventory(self):
        """Store the inventory for the new revision."""
        inv_text = serializer_v5.write_inventory_to_string(self.new_inv)
        self.inv_sha1 = sha_string(inv_text)
        s = self.branch.control_weaves
        s.add_text('inventory', self.rev_id,
                   split_lines(inv_text), self.present_parents)

    def _escape_commit_message(self):
        """Replace xml-incompatible control characters."""
        # Python strings can include characters that can't be
        # represented in well-formed XML; escape characters that
        # aren't listed in the XML specification
        # (http://www.w3.org/TR/REC-xml/#NT-Char).
        if isinstance(self.message, unicode):
            char_pattern = u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]'
        else:
            # Use a regular 'str' as pattern to avoid having re.subn
            # return 'unicode' results.
            char_pattern = '[^x09\x0A\x0D\x20-\xFF]'
        self.message, escape_count = re.subn(
            char_pattern,
            lambda match: match.group(0).encode('unicode_escape'),
            self.message)
        if escape_count:
            note("replaced %d control characters in message", escape_count)

    def _record_ancestry(self):
        """Append merged revision ancestry to the ancestry file.

        This should be the merged ancestry of all parents, plus the
        new revision id."""
        s = self.branch.control_weaves
        w = s.get_weave_or_empty('ancestry')
        lines = self._make_ancestry(w)
        w.add(self.rev_id, self.present_parents, lines)
        s.put_weave('ancestry', w)

    def _make_ancestry(self, ancestry_weave):
        """Return merged ancestry lines.

        The lines are revision-ids followed by newlines."""
        parent_ancestries = [ancestry_weave.get(p) for p in self.present_parents]
        new_lines = merge_ancestry_lines(self.rev_id, parent_ancestries)
        mutter('merged ancestry of {%s}:\n%s', self.rev_id, ''.join(new_lines))
        return new_lines

    def _gather_parents(self):
        """Record the parents of a merge for merge detection."""
        pending_merges = self.branch.pending_merges()
        self.parents = []
        self.parent_trees = []
        self.present_parents = []
        precursor_id = self.branch.last_revision()
        if precursor_id:
            self.parents.append(precursor_id)
        self.parents += pending_merges
        for revision in self.parents:
            if self.branch.has_revision(revision):
                self.parent_trees.append(self.branch.revision_tree(revision))
                self.present_parents.append(revision)

    def _check_parents_present(self):
        for parent_id in self.parents:
            mutter('commit parent revision {%s}', parent_id)
            if not self.branch.has_revision(parent_id):
                if parent_id == self.branch.last_revision():
                    warning("parent is pissing %r", parent_id)
                    raise HistoryMissing(self.branch, 'revision', parent_id)
                else:
                    mutter("commit will ghost revision %r", parent_id)
            
    def _make_revision(self):
        """Record a new revision object for this commit."""
        self.rev = Revision(timestamp=self.timestamp,
                            timezone=self.timezone,
                            committer=self.committer,
                            message=self.message,
                            inventory_sha1=self.inv_sha1,
                            revision_id=self.rev_id)
        self.rev.parent_ids = self.parents
        rev_tmp = StringIO()
        serializer_v5.write_revision(self.rev, rev_tmp)
        rev_tmp.seek(0)
        self.branch.revision_store.add(rev_tmp, self.rev_id)
        mutter('new revision_id is {%s}', self.rev_id)


    def _remove_deleted(self):
        """Remove deleted files from the working inventories.

        This is done prior to taking the working inventory as the
        basis for the new committed inventory.

        This returns true if any files
        *that existed in the basis inventory* were deleted.
        Files that were added and deleted
        in the working copy don't matter.
        """
        specific = self.specific_files
        deleted_ids = []
        for path, ie in self.work_inv.iter_entries():
            if specific and not is_inside_any(specific, path):
                continue
            if not self.work_tree.has_filename(path):
                note('missing %s', path)
                deleted_ids.append((path, ie.file_id))
        if deleted_ids:
            deleted_ids.sort(reverse=True)
            for path, file_id in deleted_ids:
                del self.work_inv[file_id]
            self.branch._write_inventory(self.work_inv)


    def _find_entry_parents(self, file_id):
        """Return the text versions and hashes for all file parents.

        Returned as a map from text version to inventory entry.

        This is a set containing the file versions in all parents
        revisions containing the file.  If the file is new, the set
        will be empty."""
        r = {}
        for tree in self.parent_trees:
            if file_id in tree.inventory:
                ie = tree.inventory[file_id]
                assert ie.file_id == file_id
                if ie.revision in r:
                    assert r[ie.revision] == ie
                else:
                    r[ie.revision] = ie
        return r

    def _store_snapshot(self):
        """Pass over inventory and record a snapshot.

        Entries get a new revision when they are modified in 
        any way, which includes a merge with a new set of
        parents that have the same entry. Currently we do not
        check for that set being ancestors of each other - and
        we should - only parallel children should count for this
        test see find_entry_parents to correct this. FIXME <---
        I.e. if we are merging in revision FOO, and our
        copy of file id BAR is identical to FOO.BAR, we should
        generate a new revision of BAR IF and only IF FOO is
        neither a child of our current tip, nor an ancestor of
        our tip. The presence of FOO in our store should not 
        affect this logic UNLESS we are doing a merge of FOO,
        or a child of FOO.
        """
        # XXX: Need to think more here about when the user has
        # made a specific decision on a particular value -- c.f.
        # mark-merge.  
        for path, ie in self.new_inv.iter_entries():
            previous_entries = self._find_entry_parents(ie. file_id)
            if ie.revision is None:
                change = ie.snapshot(self.rev_id, path, previous_entries,
                                     self.work_tree, self.weave_store)
            else:
                change = "unchanged"
            note("%s %s", change, path)

    def _populate_new_inv(self):
        """Build revision inventory.

        This creates a new empty inventory. Depending on
        which files are selected for commit, and what is present in the
        current tree, the new inventory is populated. inventory entries 
        which are candidates for modification have their revision set to
        None; inventory entries that are carried over untouched have their
        revision set to their prior value.
        """
        mutter("Selecting files for commit with filter %s", self.specific_files)
        self.new_inv = Inventory()
        for path, new_ie in self.work_inv.iter_entries():
            file_id = new_ie.file_id
            mutter('check %s {%s}', path, new_ie.file_id)
            if self.specific_files:
                if not is_inside_any(self.specific_files, path):
                    mutter('%s not selected for commit', path)
                    self._carry_file(file_id)
                    continue
            mutter('%s selected for commit', path)
            ie = new_ie.copy()
            ie.revision = None
            self.new_inv.add(ie)

    def _carry_file(self, file_id):
        """Carry the file unchanged from the basis revision."""
        if self.basis_inv.has_id(file_id):
            self.new_inv.add(self.basis_inv[file_id].copy())

    def _report_deletes(self):
        for file_id in self.basis_inv:
            if file_id not in self.new_inv:
                note('deleted %s', self.basis_inv.id2path(file_id))



def _gen_revision_id(branch, when):
    """Return new revision-id."""
    s = '%s-%s-' % (user_email(branch), compact_date(when))
    s += hexlify(rand_bytes(8))
    return s



    
def merge_ancestry_lines(rev_id, ancestries):
    """Return merged ancestry lines.

    rev_id -- id of the new revision
    
    ancestries -- a sequence of ancestries for parent revisions,
        as newline-terminated line lists.
    """
    if len(ancestries) == 0:
        return [rev_id + '\n']
    seen = set(ancestries[0])
    ancs = ancestries[0][:]    
    for parent_ancestry in ancestries[1:]:
        for line in parent_ancestry:
            assert line[-1] == '\n'
            if line not in seen:
                ancs.append(line)
                seen.add(line)
    r = rev_id + '\n'
    assert r not in seen
    ancs.append(r)
    return ancs
