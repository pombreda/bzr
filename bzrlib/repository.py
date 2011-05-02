# Copyright (C) 2005-2011 Canonical Ltd
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

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import time

from bzrlib import (
    bzrdir,
    check,
    config,
    controldir,
    debug,
    generate_ids,
    graph,
    lockable_files,
    lockdir,
    osutils,
    revision as _mod_revision,
    tsort,
    )
from bzrlib.bundle import serializer
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.testament import Testament
""")

from bzrlib import (
    errors,
    registry,
    symbol_versioning,
    ui,
    )
from bzrlib.decorators import needs_read_lock, needs_write_lock, only_raises
from bzrlib.inter import InterObject
from bzrlib.inventory import (
    Inventory,
    InventoryDirectory,
    ROOT_ID,
    entry_factory,
    )
from bzrlib.lock import _RelockDebugMixin, LogicalLockResult
from bzrlib.trace import (
    log_exception_quietly, note, mutter, mutter_callsite, warning)


# Old formats display a warning, but only once
_deprecation_warning_done = False


class IsInWriteGroupError(errors.InternalBzrError):

    _fmt = "May not refresh_data of repo %(repo)s while in a write group."

    def __init__(self, repo):
        errors.InternalBzrError.__init__(self, repo=repo)


class CommitBuilder(object):
    """Provides an interface to build up a commit.

    This allows describing a tree to be committed without needing to
    know the internals of the format of the repository.
    """

    # all clients should supply tree roots.
    record_root_entry = True
    # the default CommitBuilder does not manage trees whose root is versioned.
    _versioned_root = False
    # this commit builder supports the record_entry_contents interface
    supports_record_entry_contents = True

    def __init__(self, repository, parents, config, timestamp=None,
                 timezone=None, committer=None, revprops=None,
                 revision_id=None, lossy=False):
        """Initiate a CommitBuilder.

        :param repository: Repository to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        :param lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS 
        """
        self._config = config
        self._lossy = lossy

        if committer is None:
            self._committer = self._config.username()
        elif not isinstance(committer, unicode):
            self._committer = committer.decode() # throw if non-ascii
        else:
            self._committer = committer

        self.new_inventory = Inventory(None)
        self._new_revision_id = revision_id
        self.parents = parents
        self.repository = repository

        self._revprops = {}
        if revprops is not None:
            self._validate_revprops(revprops)
            self._revprops.update(revprops)

        if timestamp is None:
            timestamp = time.time()
        # Restrict resolution to 1ms
        self._timestamp = round(timestamp, 3)

        if timezone is None:
            self._timezone = osutils.local_time_offset()
        else:
            self._timezone = int(timezone)

        self._generate_revision_if_needed()
        self.__heads = graph.HeadsCache(repository.get_graph()).heads
        self._basis_delta = []
        # API compatibility, older code that used CommitBuilder did not call
        # .record_delete(), which means the delta that is computed would not be
        # valid. Callers that will call record_delete() should call
        # .will_record_deletes() to indicate that.
        self._recording_deletes = False
        # memo'd check for no-op commits.
        self._any_changes = False

    def any_changes(self):
        """Return True if any entries were changed.
        
        This includes merge-only changes. It is the core for the --unchanged
        detection in commit.

        :return: True if any changes have occured.
        """
        return self._any_changes

    def _validate_unicode_text(self, text, context):
        """Verify things like commit messages don't have bogus characters."""
        if '\r' in text:
            raise ValueError('Invalid value for %s: %r' % (context, text))

    def _validate_revprops(self, revprops):
        for key, value in revprops.iteritems():
            # We know that the XML serializers do not round trip '\r'
            # correctly, so refuse to accept them
            if not isinstance(value, basestring):
                raise ValueError('revision property (%s) is not a valid'
                                 ' (unicode) string: %r' % (key, value))
            self._validate_unicode_text(value,
                                        'revision property (%s)' % (key,))

    def _ensure_fallback_inventories(self):
        """Ensure that appropriate inventories are available.

        This only applies to repositories that are stacked, and is about
        enusring the stacking invariants. Namely, that for any revision that is
        present, we either have all of the file content, or we have the parent
        inventory and the delta file content.
        """
        if not self.repository._fallback_repositories:
            return
        if not self.repository._format.supports_chks:
            raise errors.BzrError("Cannot commit directly to a stacked branch"
                " in pre-2a formats. See "
                "https://bugs.launchpad.net/bzr/+bug/375013 for details.")
        # This is a stacked repo, we need to make sure we have the parent
        # inventories for the parents.
        parent_keys = [(p,) for p in self.parents]
        parent_map = self.repository.inventories._index.get_parent_map(parent_keys)
        missing_parent_keys = set([pk for pk in parent_keys
                                       if pk not in parent_map])
        fallback_repos = list(reversed(self.repository._fallback_repositories))
        missing_keys = [('inventories', pk[0])
                        for pk in missing_parent_keys]
        resume_tokens = []
        while missing_keys and fallback_repos:
            fallback_repo = fallback_repos.pop()
            source = fallback_repo._get_source(self.repository._format)
            sink = self.repository._get_sink()
            stream = source.get_stream_for_missing_keys(missing_keys)
            missing_keys = sink.insert_stream_without_locking(stream,
                self.repository._format)
        if missing_keys:
            raise errors.BzrError('Unable to fill in parent inventories for a'
                                  ' stacked branch')

    def commit(self, message):
        """Make the actual commit.

        :return: The revision id of the recorded revision.
        """
        self._validate_unicode_text(message, 'commit message')
        rev = _mod_revision.Revision(
                       timestamp=self._timestamp,
                       timezone=self._timezone,
                       committer=self._committer,
                       message=message,
                       inventory_sha1=self.inv_sha1,
                       revision_id=self._new_revision_id,
                       properties=self._revprops)
        rev.parent_ids = self.parents
        self.repository.add_revision(self._new_revision_id, rev,
            self.new_inventory, self._config)
        self._ensure_fallback_inventories()
        self.repository.commit_write_group()
        return self._new_revision_id

    def abort(self):
        """Abort the commit that is being built.
        """
        self.repository.abort_write_group()

    def revision_tree(self):
        """Return the tree that was just committed.

        After calling commit() this can be called to get a
        RevisionTree representing the newly committed tree. This is
        preferred to calling Repository.revision_tree() because that may
        require deserializing the inventory, while we already have a copy in
        memory.
        """
        if self.new_inventory is None:
            self.new_inventory = self.repository.get_inventory(
                self._new_revision_id)
        return InventoryRevisionTree(self.repository, self.new_inventory,
            self._new_revision_id)

    def finish_inventory(self):
        """Tell the builder that the inventory is finished.

        :return: The inventory id in the repository, which can be used with
            repository.get_inventory.
        """
        if self.new_inventory is None:
            # an inventory delta was accumulated without creating a new
            # inventory.
            basis_id = self.basis_delta_revision
            # We ignore the 'inventory' returned by add_inventory_by_delta
            # because self.new_inventory is used to hint to the rest of the
            # system what code path was taken
            self.inv_sha1, _ = self.repository.add_inventory_by_delta(
                basis_id, self._basis_delta, self._new_revision_id,
                self.parents)
        else:
            if self.new_inventory.root is None:
                raise AssertionError('Root entry should be supplied to'
                    ' record_entry_contents, as of bzr 0.10.')
                self.new_inventory.add(InventoryDirectory(ROOT_ID, '', None))
            self.new_inventory.revision_id = self._new_revision_id
            self.inv_sha1 = self.repository.add_inventory(
                self._new_revision_id,
                self.new_inventory,
                self.parents
                )
        return self._new_revision_id

    def _gen_revision_id(self):
        """Return new revision-id."""
        return generate_ids.gen_revision_id(self._committer, self._timestamp)

    def _generate_revision_if_needed(self):
        """Create a revision id if None was supplied.

        If the repository can not support user-specified revision ids
        they should override this function and raise CannotSetRevisionId
        if _new_revision_id is not None.

        :raises: CannotSetRevisionId
        """
        if self._new_revision_id is None:
            self._new_revision_id = self._gen_revision_id()
            self.random_revid = True
        else:
            self.random_revid = False

    def _heads(self, file_id, revision_ids):
        """Calculate the graph heads for revision_ids in the graph of file_id.

        This can use either a per-file graph or a global revision graph as we
        have an identity relationship between the two graphs.
        """
        return self.__heads(revision_ids)

    def _check_root(self, ie, parent_invs, tree):
        """Helper for record_entry_contents.

        :param ie: An entry being added.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param tree: The tree that is being committed.
        """
        # In this revision format, root entries have no knit or weave When
        # serializing out to disk and back in root.revision is always
        # _new_revision_id
        ie.revision = self._new_revision_id

    def _require_root_change(self, tree):
        """Enforce an appropriate root object change.

        This is called once when record_iter_changes is called, if and only if
        the root was not in the delta calculated by record_iter_changes.

        :param tree: The tree which is being committed.
        """
        if len(self.parents) == 0:
            raise errors.RootMissing()
        entry = entry_factory['directory'](tree.path2id(''), '',
            None)
        entry.revision = self._new_revision_id
        self._basis_delta.append(('', '', entry.file_id, entry))

    def _get_delta(self, ie, basis_inv, path):
        """Get a delta against the basis inventory for ie."""
        if ie.file_id not in basis_inv:
            # add
            result = (None, path, ie.file_id, ie)
            self._basis_delta.append(result)
            return result
        elif ie != basis_inv[ie.file_id]:
            # common but altered
            # TODO: avoid tis id2path call.
            result = (basis_inv.id2path(ie.file_id), path, ie.file_id, ie)
            self._basis_delta.append(result)
            return result
        else:
            # common, unaltered
            return None

    def get_basis_delta(self):
        """Return the complete inventory delta versus the basis inventory.

        This has been built up with the calls to record_delete and
        record_entry_contents. The client must have already called
        will_record_deletes() to indicate that they will be generating a
        complete delta.

        :return: An inventory delta, suitable for use with apply_delta, or
            Repository.add_inventory_by_delta, etc.
        """
        if not self._recording_deletes:
            raise AssertionError("recording deletes not activated.")
        return self._basis_delta

    def record_delete(self, path, file_id):
        """Record that a delete occured against a basis tree.

        This is an optional API - when used it adds items to the basis_delta
        being accumulated by the commit builder. It cannot be called unless the
        method will_record_deletes() has been called to inform the builder that
        a delta is being supplied.

        :param path: The path of the thing deleted.
        :param file_id: The file id that was deleted.
        """
        if not self._recording_deletes:
            raise AssertionError("recording deletes not activated.")
        delta = (path, None, file_id, None)
        self._basis_delta.append(delta)
        self._any_changes = True
        return delta

    def will_record_deletes(self):
        """Tell the commit builder that deletes are being notified.

        This enables the accumulation of an inventory delta; for the resulting
        commit to be valid, deletes against the basis MUST be recorded via
        builder.record_delete().
        """
        self._recording_deletes = True
        try:
            basis_id = self.parents[0]
        except IndexError:
            basis_id = _mod_revision.NULL_REVISION
        self.basis_delta_revision = basis_id

    def record_entry_contents(self, ie, parent_invs, path, tree,
        content_summary):
        """Record the content of ie from tree into the commit if needed.

        Side effect: sets ie.revision when unchanged

        :param ie: An inventory entry present in the commit.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param path: The path the entry is at in the tree.
        :param tree: The tree which contains this entry and should be used to
            obtain content.
        :param content_summary: Summary data from the tree about the paths
            content - stat, length, exec, sha/link target. This is only
            accessed when the entry has a revision of None - that is when it is
            a candidate to commit.
        :return: A tuple (change_delta, version_recorded, fs_hash).
            change_delta is an inventory_delta change for this entry against
            the basis tree of the commit, or None if no change occured against
            the basis tree.
            version_recorded is True if a new version of the entry has been
            recorded. For instance, committing a merge where a file was only
            changed on the other side will return (delta, False).
            fs_hash is either None, or the hash details for the path (currently
            a tuple of the contents sha1 and the statvalue returned by
            tree.get_file_with_stat()).
        """
        if self.new_inventory.root is None:
            if ie.parent_id is not None:
                raise errors.RootMissing()
            self._check_root(ie, parent_invs, tree)
        if ie.revision is None:
            kind = content_summary[0]
        else:
            # ie is carried over from a prior commit
            kind = ie.kind
        # XXX: repository specific check for nested tree support goes here - if
        # the repo doesn't want nested trees we skip it ?
        if (kind == 'tree-reference' and
            not self.repository._format.supports_tree_reference):
            # mismatch between commit builder logic and repository:
            # this needs the entry creation pushed down into the builder.
            raise NotImplementedError('Missing repository subtree support.')
        self.new_inventory.add(ie)

        # TODO: slow, take it out of the inner loop.
        try:
            basis_inv = parent_invs[0]
        except IndexError:
            basis_inv = Inventory(root_id=None)

        # ie.revision is always None if the InventoryEntry is considered
        # for committing. We may record the previous parents revision if the
        # content is actually unchanged against a sole head.
        if ie.revision is not None:
            if not self._versioned_root and path == '':
                # repositories that do not version the root set the root's
                # revision to the new commit even when no change occurs (more
                # specifically, they do not record a revision on the root; and
                # the rev id is assigned to the root during deserialisation -
                # this masks when a change may have occurred against the basis.
                # To match this we always issue a delta, because the revision
                # of the root will always be changing.
                if ie.file_id in basis_inv:
                    delta = (basis_inv.id2path(ie.file_id), path,
                        ie.file_id, ie)
                else:
                    # add
                    delta = (None, path, ie.file_id, ie)
                self._basis_delta.append(delta)
                return delta, False, None
            else:
                # we don't need to commit this, because the caller already
                # determined that an existing revision of this file is
                # appropriate. If it's not being considered for committing then
                # it and all its parents to the root must be unaltered so
                # no-change against the basis.
                if ie.revision == self._new_revision_id:
                    raise AssertionError("Impossible situation, a skipped "
                        "inventory entry (%r) claims to be modified in this "
                        "commit (%r).", (ie, self._new_revision_id))
                return None, False, None
        # XXX: Friction: parent_candidates should return a list not a dict
        #      so that we don't have to walk the inventories again.
        parent_candiate_entries = ie.parent_candidates(parent_invs)
        head_set = self._heads(ie.file_id, parent_candiate_entries.keys())
        heads = []
        for inv in parent_invs:
            if ie.file_id in inv:
                old_rev = inv[ie.file_id].revision
                if old_rev in head_set:
                    heads.append(inv[ie.file_id].revision)
                    head_set.remove(inv[ie.file_id].revision)

        store = False
        # now we check to see if we need to write a new record to the
        # file-graph.
        # We write a new entry unless there is one head to the ancestors, and
        # the kind-derived content is unchanged.

        # Cheapest check first: no ancestors, or more the one head in the
        # ancestors, we write a new node.
        if len(heads) != 1:
            store = True
        if not store:
            # There is a single head, look it up for comparison
            parent_entry = parent_candiate_entries[heads[0]]
            # if the non-content specific data has changed, we'll be writing a
            # node:
            if (parent_entry.parent_id != ie.parent_id or
                parent_entry.name != ie.name):
                store = True
        # now we need to do content specific checks:
        if not store:
            # if the kind changed the content obviously has
            if kind != parent_entry.kind:
                store = True
        # Stat cache fingerprint feedback for the caller - None as we usually
        # don't generate one.
        fingerprint = None
        if kind == 'file':
            if content_summary[2] is None:
                raise ValueError("Files must not have executable = None")
            if not store:
                # We can't trust a check of the file length because of content
                # filtering...
                if (# if the exec bit has changed we have to store:
                    parent_entry.executable != content_summary[2]):
                    store = True
                elif parent_entry.text_sha1 == content_summary[3]:
                    # all meta and content is unchanged (using a hash cache
                    # hit to check the sha)
                    ie.revision = parent_entry.revision
                    ie.text_size = parent_entry.text_size
                    ie.text_sha1 = parent_entry.text_sha1
                    ie.executable = parent_entry.executable
                    return self._get_delta(ie, basis_inv, path), False, None
                else:
                    # Either there is only a hash change(no hash cache entry,
                    # or same size content change), or there is no change on
                    # this file at all.
                    # Provide the parent's hash to the store layer, so that the
                    # content is unchanged we will not store a new node.
                    nostore_sha = parent_entry.text_sha1
            if store:
                # We want to record a new node regardless of the presence or
                # absence of a content change in the file.
                nostore_sha = None
            ie.executable = content_summary[2]
            file_obj, stat_value = tree.get_file_with_stat(ie.file_id, path)
            try:
                text = file_obj.read()
            finally:
                file_obj.close()
            try:
                ie.text_sha1, ie.text_size = self._add_text_to_weave(
                    ie.file_id, text, heads, nostore_sha)
                # Let the caller know we generated a stat fingerprint.
                fingerprint = (ie.text_sha1, stat_value)
            except errors.ExistingContent:
                # Turns out that the file content was unchanged, and we were
                # only going to store a new node if it was changed. Carry over
                # the entry.
                ie.revision = parent_entry.revision
                ie.text_size = parent_entry.text_size
                ie.text_sha1 = parent_entry.text_sha1
                ie.executable = parent_entry.executable
                return self._get_delta(ie, basis_inv, path), False, None
        elif kind == 'directory':
            if not store:
                # all data is meta here, nothing specific to directory, so
                # carry over:
                ie.revision = parent_entry.revision
                return self._get_delta(ie, basis_inv, path), False, None
            self._add_text_to_weave(ie.file_id, '', heads, None)
        elif kind == 'symlink':
            current_link_target = content_summary[3]
            if not store:
                # symlink target is not generic metadata, check if it has
                # changed.
                if current_link_target != parent_entry.symlink_target:
                    store = True
            if not store:
                # unchanged, carry over.
                ie.revision = parent_entry.revision
                ie.symlink_target = parent_entry.symlink_target
                return self._get_delta(ie, basis_inv, path), False, None
            ie.symlink_target = current_link_target
            self._add_text_to_weave(ie.file_id, '', heads, None)
        elif kind == 'tree-reference':
            if not store:
                if content_summary[3] != parent_entry.reference_revision:
                    store = True
            if not store:
                # unchanged, carry over.
                ie.reference_revision = parent_entry.reference_revision
                ie.revision = parent_entry.revision
                return self._get_delta(ie, basis_inv, path), False, None
            ie.reference_revision = content_summary[3]
            if ie.reference_revision is None:
                raise AssertionError("invalid content_summary for nested tree: %r"
                    % (content_summary,))
            self._add_text_to_weave(ie.file_id, '', heads, None)
        else:
            raise NotImplementedError('unknown kind')
        ie.revision = self._new_revision_id
        self._any_changes = True
        return self._get_delta(ie, basis_inv, path), True, fingerprint

    def record_iter_changes(self, tree, basis_revision_id, iter_changes,
        _entry_factory=entry_factory):
        """Record a new tree via iter_changes.

        :param tree: The tree to obtain text contents from for changed objects.
        :param basis_revision_id: The revision id of the tree the iter_changes
            has been generated against. Currently assumed to be the same
            as self.parents[0] - if it is not, errors may occur.
        :param iter_changes: An iter_changes iterator with the changes to apply
            to basis_revision_id. The iterator must not include any items with
            a current kind of None - missing items must be either filtered out
            or errored-on beefore record_iter_changes sees the item.
        :param _entry_factory: Private method to bind entry_factory locally for
            performance.
        :return: A generator of (file_id, relpath, fs_hash) tuples for use with
            tree._observed_sha1.
        """
        # Create an inventory delta based on deltas between all the parents and
        # deltas between all the parent inventories. We use inventory delta's 
        # between the inventory objects because iter_changes masks
        # last-changed-field only changes.
        # Working data:
        # file_id -> change map, change is fileid, paths, changed, versioneds,
        # parents, names, kinds, executables
        merged_ids = {}
        # {file_id -> revision_id -> inventory entry, for entries in parent
        # trees that are not parents[0]
        parent_entries = {}
        ghost_basis = False
        try:
            revtrees = list(self.repository.revision_trees(self.parents))
        except errors.NoSuchRevision:
            # one or more ghosts, slow path.
            revtrees = []
            for revision_id in self.parents:
                try:
                    revtrees.append(self.repository.revision_tree(revision_id))
                except errors.NoSuchRevision:
                    if not revtrees:
                        basis_revision_id = _mod_revision.NULL_REVISION
                        ghost_basis = True
                    revtrees.append(self.repository.revision_tree(
                        _mod_revision.NULL_REVISION))
        # The basis inventory from a repository 
        if revtrees:
            basis_inv = revtrees[0].inventory
        else:
            basis_inv = self.repository.revision_tree(
                _mod_revision.NULL_REVISION).inventory
        if len(self.parents) > 0:
            if basis_revision_id != self.parents[0] and not ghost_basis:
                raise Exception(
                    "arbitrary basis parents not yet supported with merges")
            for revtree in revtrees[1:]:
                for change in revtree.inventory._make_delta(basis_inv):
                    if change[1] is None:
                        # Not present in this parent.
                        continue
                    if change[2] not in merged_ids:
                        if change[0] is not None:
                            basis_entry = basis_inv[change[2]]
                            merged_ids[change[2]] = [
                                # basis revid
                                basis_entry.revision,
                                # new tree revid
                                change[3].revision]
                            parent_entries[change[2]] = {
                                # basis parent
                                basis_entry.revision:basis_entry,
                                # this parent 
                                change[3].revision:change[3],
                                }
                        else:
                            merged_ids[change[2]] = [change[3].revision]
                            parent_entries[change[2]] = {change[3].revision:change[3]}
                    else:
                        merged_ids[change[2]].append(change[3].revision)
                        parent_entries[change[2]][change[3].revision] = change[3]
        else:
            merged_ids = {}
        # Setup the changes from the tree:
        # changes maps file_id -> (change, [parent revision_ids])
        changes= {}
        for change in iter_changes:
            # This probably looks up in basis_inv way to much.
            if change[1][0] is not None:
                head_candidate = [basis_inv[change[0]].revision]
            else:
                head_candidate = []
            changes[change[0]] = change, merged_ids.get(change[0],
                head_candidate)
        unchanged_merged = set(merged_ids) - set(changes)
        # Extend the changes dict with synthetic changes to record merges of
        # texts.
        for file_id in unchanged_merged:
            # Record a merged version of these items that did not change vs the
            # basis. This can be either identical parallel changes, or a revert
            # of a specific file after a merge. The recorded content will be
            # that of the current tree (which is the same as the basis), but
            # the per-file graph will reflect a merge.
            # NB:XXX: We are reconstructing path information we had, this
            # should be preserved instead.
            # inv delta  change: (file_id, (path_in_source, path_in_target),
            #   changed_content, versioned, parent, name, kind,
            #   executable)
            try:
                basis_entry = basis_inv[file_id]
            except errors.NoSuchId:
                # a change from basis->some_parents but file_id isn't in basis
                # so was new in the merge, which means it must have changed
                # from basis -> current, and as it hasn't the add was reverted
                # by the user. So we discard this change.
                pass
            else:
                change = (file_id,
                    (basis_inv.id2path(file_id), tree.id2path(file_id)),
                    False, (True, True),
                    (basis_entry.parent_id, basis_entry.parent_id),
                    (basis_entry.name, basis_entry.name),
                    (basis_entry.kind, basis_entry.kind),
                    (basis_entry.executable, basis_entry.executable))
                changes[file_id] = (change, merged_ids[file_id])
        # changes contains tuples with the change and a set of inventory
        # candidates for the file.
        # inv delta is:
        # old_path, new_path, file_id, new_inventory_entry
        seen_root = False # Is the root in the basis delta?
        inv_delta = self._basis_delta
        modified_rev = self._new_revision_id
        for change, head_candidates in changes.values():
            if change[3][1]: # versioned in target.
                # Several things may be happening here:
                # We may have a fork in the per-file graph
                #  - record a change with the content from tree
                # We may have a change against < all trees  
                #  - carry over the tree that hasn't changed
                # We may have a change against all trees
                #  - record the change with the content from tree
                kind = change[6][1]
                file_id = change[0]
                entry = _entry_factory[kind](file_id, change[5][1],
                    change[4][1])
                head_set = self._heads(change[0], set(head_candidates))
                heads = []
                # Preserve ordering.
                for head_candidate in head_candidates:
                    if head_candidate in head_set:
                        heads.append(head_candidate)
                        head_set.remove(head_candidate)
                carried_over = False
                if len(heads) == 1:
                    # Could be a carry-over situation:
                    parent_entry_revs = parent_entries.get(file_id, None)
                    if parent_entry_revs:
                        parent_entry = parent_entry_revs.get(heads[0], None)
                    else:
                        parent_entry = None
                    if parent_entry is None:
                        # The parent iter_changes was called against is the one
                        # that is the per-file head, so any change is relevant
                        # iter_changes is valid.
                        carry_over_possible = False
                    else:
                        # could be a carry over situation
                        # A change against the basis may just indicate a merge,
                        # we need to check the content against the source of the
                        # merge to determine if it was changed after the merge
                        # or carried over.
                        if (parent_entry.kind != entry.kind or
                            parent_entry.parent_id != entry.parent_id or
                            parent_entry.name != entry.name):
                            # Metadata common to all entries has changed
                            # against per-file parent
                            carry_over_possible = False
                        else:
                            carry_over_possible = True
                        # per-type checks for changes against the parent_entry
                        # are done below.
                else:
                    # Cannot be a carry-over situation
                    carry_over_possible = False
                # Populate the entry in the delta
                if kind == 'file':
                    # XXX: There is still a small race here: If someone reverts the content of a file
                    # after iter_changes examines and decides it has changed,
                    # we will unconditionally record a new version even if some
                    # other process reverts it while commit is running (with
                    # the revert happening after iter_changes did its
                    # examination).
                    if change[7][1]:
                        entry.executable = True
                    else:
                        entry.executable = False
                    if (carry_over_possible and
                        parent_entry.executable == entry.executable):
                            # Check the file length, content hash after reading
                            # the file.
                            nostore_sha = parent_entry.text_sha1
                    else:
                        nostore_sha = None
                    file_obj, stat_value = tree.get_file_with_stat(file_id, change[1][1])
                    try:
                        text = file_obj.read()
                    finally:
                        file_obj.close()
                    try:
                        entry.text_sha1, entry.text_size = self._add_text_to_weave(
                            file_id, text, heads, nostore_sha)
                        yield file_id, change[1][1], (entry.text_sha1, stat_value)
                    except errors.ExistingContent:
                        # No content change against a carry_over parent
                        # Perhaps this should also yield a fs hash update?
                        carried_over = True
                        entry.text_size = parent_entry.text_size
                        entry.text_sha1 = parent_entry.text_sha1
                elif kind == 'symlink':
                    # Wants a path hint?
                    entry.symlink_target = tree.get_symlink_target(file_id)
                    if (carry_over_possible and
                        parent_entry.symlink_target == entry.symlink_target):
                        carried_over = True
                    else:
                        self._add_text_to_weave(change[0], '', heads, None)
                elif kind == 'directory':
                    if carry_over_possible:
                        carried_over = True
                    else:
                        # Nothing to set on the entry.
                        # XXX: split into the Root and nonRoot versions.
                        if change[1][1] != '' or self.repository.supports_rich_root():
                            self._add_text_to_weave(change[0], '', heads, None)
                elif kind == 'tree-reference':
                    if not self.repository._format.supports_tree_reference:
                        # This isn't quite sane as an error, but we shouldn't
                        # ever see this code path in practice: tree's don't
                        # permit references when the repo doesn't support tree
                        # references.
                        raise errors.UnsupportedOperation(tree.add_reference,
                            self.repository)
                    reference_revision = tree.get_reference_revision(change[0])
                    entry.reference_revision = reference_revision
                    if (carry_over_possible and
                        parent_entry.reference_revision == reference_revision):
                        carried_over = True
                    else:
                        self._add_text_to_weave(change[0], '', heads, None)
                else:
                    raise AssertionError('unknown kind %r' % kind)
                if not carried_over:
                    entry.revision = modified_rev
                else:
                    entry.revision = parent_entry.revision
            else:
                entry = None
            new_path = change[1][1]
            inv_delta.append((change[1][0], new_path, change[0], entry))
            if new_path == '':
                seen_root = True
        self.new_inventory = None
        if len(inv_delta):
            # This should perhaps be guarded by a check that the basis we
            # commit against is the basis for the commit and if not do a delta
            # against the basis.
            self._any_changes = True
        if not seen_root:
            # housekeeping root entry changes do not affect no-change commits.
            self._require_root_change(tree)
        self.basis_delta_revision = basis_revision_id

    def _add_text_to_weave(self, file_id, new_text, parents, nostore_sha):
        parent_keys = tuple([(file_id, parent) for parent in parents])
        return self.repository.texts._add_text(
            (file_id, self._new_revision_id), parent_keys, new_text,
            nostore_sha=nostore_sha, random_id=self.random_revid)[0:2]


class RootCommitBuilder(CommitBuilder):
    """This commitbuilder actually records the root id"""

    # the root entry gets versioned properly by this builder.
    _versioned_root = True

    def _check_root(self, ie, parent_invs, tree):
        """Helper for record_entry_contents.

        :param ie: An entry being added.
        :param parent_invs: The inventories of the parent revisions of the
            commit.
        :param tree: The tree that is being committed.
        """

    def _require_root_change(self, tree):
        """Enforce an appropriate root object change.

        This is called once when record_iter_changes is called, if and only if
        the root was not in the delta calculated by record_iter_changes.

        :param tree: The tree which is being committed.
        """
        # versioned roots do not change unless the tree found a change.


class RepositoryWriteLockResult(LogicalLockResult):
    """The result of write locking a repository.

    :ivar repository_token: The token obtained from the underlying lock, or
        None.
    :ivar unlock: A callable which will unlock the lock.
    """

    def __init__(self, unlock, repository_token):
        LogicalLockResult.__init__(self, unlock)
        self.repository_token = repository_token

    def __repr__(self):
        return "RepositoryWriteLockResult(%s, %s)" % (self.repository_token,
            self.unlock)


######################################################################
# Repositories


class Repository(_RelockDebugMixin, controldir.ControlComponent):
    """Repository holding history for one or more branches.

    The repository holds and retrieves historical information including
    revisions and file history.  It's normally accessed only by the Branch,
    which views a particular line of development through that history.

    See VersionedFileRepository in bzrlib.vf_repository for the
    base class for most Bazaar repositories.
    """

    # What class to use for a CommitBuilder. Often it's simpler to change this
    # in a Repository class subclass rather than to override
    # get_commit_builder.
    _commit_builder_class = CommitBuilder

    def abort_write_group(self, suppress_errors=False):
        """Commit the contents accrued within the current write group.

        :param suppress_errors: if true, abort_write_group will catch and log
            unexpected errors that happen during the abort, rather than
            allowing them to propagate.  Defaults to False.

        :seealso: start_write_group.
        """
        if self._write_group is not self.get_transaction():
            # has an unlock or relock occured ?
            if suppress_errors:
                mutter(
                '(suppressed) mismatched lock context and write group. %r, %r',
                self._write_group, self.get_transaction())
                return
            raise errors.BzrError(
                'mismatched lock context and write group. %r, %r' %
                (self._write_group, self.get_transaction()))
        try:
            self._abort_write_group()
        except Exception, exc:
            self._write_group = None
            if not suppress_errors:
                raise
            mutter('abort_write_group failed')
            log_exception_quietly()
            note('bzr: ERROR (ignored): %s', exc)
        self._write_group = None

    def _abort_write_group(self):
        """Template method for per-repository write group cleanup.

        This is called during abort before the write group is considered to be
        finished and should cleanup any internal state accrued during the write
        group. There is no requirement that data handed to the repository be
        *not* made available - this is not a rollback - but neither should any
        attempt be made to ensure that data added is fully commited. Abort is
        invoked when an error has occured so futher disk or network operations
        may not be possible or may error and if possible should not be
        attempted.
        """

    def add_fallback_repository(self, repository):
        """Add a repository to use for looking up data not held locally.

        :param repository: A repository.
        """
        raise NotImplementedError(self.add_fallback_repository)

    def _check_fallback_repository(self, repository):
        """Check that this repository can fallback to repository safely.

        Raise an error if not.

        :param repository: A repository to fallback to.
        """
        return InterRepository._assert_same_model(self, repository)

    def all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        This is conceptually deprecated because code should generally work on
        the graph reachable from a particular revision, and ignore any other
        revisions that might be present.  There is no direct replacement
        method.
        """
        if 'evil' in debug.debug_flags:
            mutter_callsite(2, "all_revision_ids is linear with history.")
        return self._all_revision_ids()

    def _all_revision_ids(self):
        """Returns a list of all the revision ids in the repository.

        These are in as much topological order as the underlying store can
        present.
        """
        raise NotImplementedError(self._all_revision_ids)

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.
        """
        self.control_files.break_lock()

    @needs_read_lock
    def _eliminate_revisions_not_present(self, revision_ids):
        """Check every revision id in revision_ids to see if we have it.

        Returns a set of the present revisions.
        """
        result = []
        graph = self.get_graph()
        parent_map = graph.get_parent_map(revision_ids)
        # The old API returned a list, should this actually be a set?
        return parent_map.keys()

    @staticmethod
    def create(a_bzrdir):
        """Construct the current default format repository in a_bzrdir."""
        return RepositoryFormat.get_default_format().initialize(a_bzrdir)

    def __init__(self, _format, a_bzrdir, control_files):
        """instantiate a Repository.

        :param _format: The format of the repository on disk.
        :param a_bzrdir: The BzrDir of the repository.
        :param control_files: Control files to use for locking, etc.
        """
        # In the future we will have a single api for all stores for
        # getting file texts, inventories and revisions, then
        # this construct will accept instances of those things.
        super(Repository, self).__init__()
        self._format = _format
        # the following are part of the public API for Repository:
        self.bzrdir = a_bzrdir
        self.control_files = control_files
        self._transport = control_files._transport
        self.base = self._transport.base
        # for tests
        self._write_group = None
        # Additional places to query for data.
        self._fallback_repositories = []

    @property
    def user_transport(self):
        return self.bzrdir.user_transport

    @property
    def control_transport(self):
        return self._transport

    def __repr__(self):
        if self._fallback_repositories:
            return '%s(%r, fallback_repositories=%r)' % (
                self.__class__.__name__,
                self.base,
                self._fallback_repositories)
        else:
            return '%s(%r)' % (self.__class__.__name__,
                               self.base)

    def _has_same_fallbacks(self, other_repo):
        """Returns true if the repositories have the same fallbacks."""
        my_fb = self._fallback_repositories
        other_fb = other_repo._fallback_repositories
        if len(my_fb) != len(other_fb):
            return False
        for f, g in zip(my_fb, other_fb):
            if not f.has_same_location(g):
                return False
        return True

    def has_same_location(self, other):
        """Returns a boolean indicating if this repository is at the same
        location as another repository.

        This might return False even when two repository objects are accessing
        the same physical repository via different URLs.
        """
        if self.__class__ is not other.__class__:
            return False
        return (self._transport.base == other._transport.base)

    def is_in_write_group(self):
        """Return True if there is an open write group.

        :seealso: start_write_group.
        """
        return self._write_group is not None

    def is_locked(self):
        return self.control_files.is_locked()

    def is_write_locked(self):
        """Return True if this object is write locked."""
        return self.is_locked() and self.control_files._lock_mode == 'w'

    def lock_write(self, token=None):
        """Lock this repository for writing.

        This causes caching within the repository obejct to start accumlating
        data during reads, and allows a 'write_group' to be obtained. Write
        groups must be used for actual data insertion.

        A token should be passed in if you know that you have locked the object
        some other way, and need to synchronise this object's state with that
        fact.

        XXX: this docstring is duplicated in many places, e.g. lockable_files.py

        :param token: if this is already locked, then lock_write will fail
            unless the token matches the existing lock.
        :returns: a token if this instance supports tokens, otherwise None.
        :raises TokenLockingNotSupported: when a token is given but this
            instance doesn't support using token locks.
        :raises MismatchedToken: if the specified token doesn't match the token
            of the existing lock.
        :seealso: start_write_group.
        :return: A RepositoryWriteLockResult.
        """
        locked = self.is_locked()
        token = self.control_files.lock_write(token=token)
        if not locked:
            self._warn_if_deprecated()
            self._note_lock('w')
            for repo in self._fallback_repositories:
                # Writes don't affect fallback repos
                repo.lock_read()
            self._refresh_data()
        return RepositoryWriteLockResult(self.unlock, token)

    def lock_read(self):
        """Lock the repository for read operations.

        :return: An object with an unlock method which will release the lock
            obtained.
        """
        locked = self.is_locked()
        self.control_files.lock_read()
        if not locked:
            self._warn_if_deprecated()
            self._note_lock('r')
            for repo in self._fallback_repositories:
                repo.lock_read()
            self._refresh_data()
        return LogicalLockResult(self.unlock)

    def get_physical_lock_status(self):
        return self.control_files.get_physical_lock_status()

    def leave_lock_in_place(self):
        """Tell this repository not to release the physical lock when this
        object is unlocked.

        If lock_write doesn't return a token, then this method is not supported.
        """
        self.control_files.leave_in_place()

    def dont_leave_lock_in_place(self):
        """Tell this repository to release the physical lock when this
        object is unlocked, even if it didn't originally acquire it.

        If lock_write doesn't return a token, then this method is not supported.
        """
        self.control_files.dont_leave_in_place()

    @needs_read_lock
    def gather_stats(self, revid=None, committers=None):
        """Gather statistics from a revision id.

        :param revid: The revision id to gather statistics from, if None, then
            no revision specific statistics are gathered.
        :param committers: Optional parameter controlling whether to grab
            a count of committers from the revision specific statistics.
        :return: A dictionary of statistics. Currently this contains:
            committers: The number of committers if requested.
            firstrev: A tuple with timestamp, timezone for the penultimate left
                most ancestor of revid, if revid is not the NULL_REVISION.
            latestrev: A tuple with timestamp, timezone for revid, if revid is
                not the NULL_REVISION.
            revisions: The total revision count in the repository.
            size: An estimate disk size of the repository in bytes.
        """
        result = {}
        if revid and committers:
            result['committers'] = 0
        if revid and revid != _mod_revision.NULL_REVISION:
            if committers:
                all_committers = set()
            revisions = self.get_ancestry(revid)
            # pop the leading None
            revisions.pop(0)
            first_revision = None
            if not committers:
                # ignore the revisions in the middle - just grab first and last
                revisions = revisions[0], revisions[-1]
            for revision in self.get_revisions(revisions):
                if not first_revision:
                    first_revision = revision
                if committers:
                    all_committers.add(revision.committer)
            last_revision = revision
            if committers:
                result['committers'] = len(all_committers)
            result['firstrev'] = (first_revision.timestamp,
                first_revision.timezone)
            result['latestrev'] = (last_revision.timestamp,
                last_revision.timezone)

        # now gather global repository information
        # XXX: This is available for many repos regardless of listability.
        if self.user_transport.listable():
            # XXX: do we want to __define len__() ?
            # Maybe the versionedfiles object should provide a different
            # method to get the number of keys.
            result['revisions'] = len(self.revisions.keys())
            # result['size'] = t
        return result

    def find_branches(self, using=False):
        """Find branches underneath this repository.

        This will include branches inside other branches.

        :param using: If True, list only branches using this repository.
        """
        if using and not self.is_shared():
            return self.bzrdir.list_branches()
        class Evaluator(object):

            def __init__(self):
                self.first_call = True

            def __call__(self, bzrdir):
                # On the first call, the parameter is always the bzrdir
                # containing the current repo.
                if not self.first_call:
                    try:
                        repository = bzrdir.open_repository()
                    except errors.NoRepositoryPresent:
                        pass
                    else:
                        return False, ([], repository)
                self.first_call = False
                value = (bzrdir.list_branches(), None)
                return True, value

        ret = []
        for branches, repository in bzrdir.BzrDir.find_bzrdirs(
                self.user_transport, evaluate=Evaluator()):
            if branches is not None:
                ret.extend(branches)
            if not using and repository is not None:
                ret.extend(repository.find_branches())
        return ret

    @needs_read_lock
    def search_missing_revision_ids(self, other,
            revision_id=symbol_versioning.DEPRECATED_PARAMETER,
            find_ghosts=True, revision_ids=None, if_present_ids=None):
        """Return the revision ids that other has that this does not.

        These are returned in topological order.

        revision_id: only return revision ids included by revision_id.
        """
        if symbol_versioning.deprecated_passed(revision_id):
            symbol_versioning.warn(
                'search_missing_revision_ids(revision_id=...) was '
                'deprecated in 2.4.  Use revision_ids=[...] instead.',
                DeprecationWarning, stacklevel=3)
            if revision_ids is not None:
                raise AssertionError(
                    'revision_ids is mutually exclusive with revision_id')
            if revision_id is not None:
                revision_ids = [revision_id]
        return InterRepository.get(other, self).search_missing_revision_ids(
            find_ghosts=find_ghosts, revision_ids=revision_ids,
            if_present_ids=if_present_ids)

    @staticmethod
    def open(base):
        """Open the repository rooted at base.

        For instance, if the repository is at URL/.bzr/repository,
        Repository.open(URL) -> a Repository instance.
        """
        control = bzrdir.BzrDir.open(base)
        return control.open_repository()

    def copy_content_into(self, destination, revision_id=None):
        """Make a complete copy of the content in self into destination.

        This is a destructive operation! Do not use it on existing
        repositories.
        """
        return InterRepository.get(self, destination).copy_content(revision_id)

    def commit_write_group(self):
        """Commit the contents accrued within the current write group.

        :seealso: start_write_group.
        
        :return: it may return an opaque hint that can be passed to 'pack'.
        """
        if self._write_group is not self.get_transaction():
            # has an unlock or relock occured ?
            raise errors.BzrError('mismatched lock context %r and '
                'write group %r.' %
                (self.get_transaction(), self._write_group))
        result = self._commit_write_group()
        self._write_group = None
        return result

    def _commit_write_group(self):
        """Template method for per-repository write group cleanup.

        This is called before the write group is considered to be
        finished and should ensure that all data handed to the repository
        for writing during the write group is safely committed (to the
        extent possible considering file system caching etc).
        """

    def suspend_write_group(self):
        raise errors.UnsuspendableWriteGroup(self)

    def refresh_data(self):
        """Re-read any data needed to synchronise with disk.

        This method is intended to be called after another repository instance
        (such as one used by a smart server) has inserted data into the
        repository. On all repositories this will work outside of write groups.
        Some repository formats (pack and newer for bzrlib native formats)
        support refresh_data inside write groups. If called inside a write
        group on a repository that does not support refreshing in a write group
        IsInWriteGroupError will be raised.
        """
        self._refresh_data()

    def resume_write_group(self, tokens):
        if not self.is_write_locked():
            raise errors.NotWriteLocked(self)
        if self._write_group:
            raise errors.BzrError('already in a write group')
        self._resume_write_group(tokens)
        # so we can detect unlock/relock - the write group is now entered.
        self._write_group = self.get_transaction()

    def _resume_write_group(self, tokens):
        raise errors.UnsuspendableWriteGroup(self)

    def fetch(self, source, revision_id=None, find_ghosts=False,
            fetch_spec=None):
        """Fetch the content required to construct revision_id from source.

        If revision_id is None and fetch_spec is None, then all content is
        copied.

        fetch() may not be used when the repository is in a write group -
        either finish the current write group before using fetch, or use
        fetch before starting the write group.

        :param find_ghosts: Find and copy revisions in the source that are
            ghosts in the target (and not reachable directly by walking out to
            the first-present revision in target from revision_id).
        :param revision_id: If specified, all the content needed for this
            revision ID will be copied to the target.  Fetch will determine for
            itself which content needs to be copied.
        :param fetch_spec: If specified, a SearchResult or
            PendingAncestryResult that describes which revisions to copy.  This
            allows copying multiple heads at once.  Mutually exclusive with
            revision_id.
        """
        if fetch_spec is not None and revision_id is not None:
            raise AssertionError(
                "fetch_spec and revision_id are mutually exclusive.")
        if self.is_in_write_group():
            raise errors.InternalBzrError(
                "May not fetch while in a write group.")
        # fast path same-url fetch operations
        # TODO: lift out to somewhere common with RemoteRepository
        # <https://bugs.launchpad.net/bzr/+bug/401646>
        if (self.has_same_location(source)
            and fetch_spec is None
            and self._has_same_fallbacks(source)):
            # check that last_revision is in 'from' and then return a
            # no-operation.
            if (revision_id is not None and
                not _mod_revision.is_null(revision_id)):
                self.get_revision(revision_id)
            return 0, []
        inter = InterRepository.get(source, self)
        return inter.fetch(revision_id=revision_id,
            find_ghosts=find_ghosts, fetch_spec=fetch_spec)

    def create_bundle(self, target, base, fileobj, format=None):
        return serializer.write_bundle(self, target, base, fileobj, format)

    def get_commit_builder(self, branch, parents, config, timestamp=None,
                           timezone=None, committer=None, revprops=None,
                           revision_id=None, lossy=False):
        """Obtain a CommitBuilder for this repository.

        :param branch: Branch to commit to.
        :param parents: Revision ids of the parents of the new revision.
        :param config: Configuration to use.
        :param timestamp: Optional timestamp recorded for commit.
        :param timezone: Optional timezone for timestamp.
        :param committer: Optional committer to set for commit.
        :param revprops: Optional dictionary of revision properties.
        :param revision_id: Optional revision id.
        :param lossy: Whether to discard data that can not be natively
            represented, when pushing to a foreign VCS
        """
        if self._fallback_repositories and not self._format.supports_chks:
            raise errors.BzrError("Cannot commit directly to a stacked branch"
                " in pre-2a formats. See "
                "https://bugs.launchpad.net/bzr/+bug/375013 for details.")
        result = self._commit_builder_class(self, parents, config,
            timestamp, timezone, committer, revprops, revision_id,
            lossy)
        self.start_write_group()
        return result

    @only_raises(errors.LockNotHeld, errors.LockBroken)
    def unlock(self):
        if (self.control_files._lock_count == 1 and
            self.control_files._lock_mode == 'w'):
            if self._write_group is not None:
                self.abort_write_group()
                self.control_files.unlock()
                raise errors.BzrError(
                    'Must end write groups before releasing write locks.')
        self.control_files.unlock()
        if self.control_files._lock_count == 0:
            for repo in self._fallback_repositories:
                repo.unlock()

    @needs_read_lock
    def clone(self, a_bzrdir, revision_id=None):
        """Clone this repository into a_bzrdir using the current format.

        Currently no check is made that the format of this repository and
        the bzrdir format are compatible. FIXME RBC 20060201.

        :return: The newly created destination repository.
        """
        # TODO: deprecate after 0.16; cloning this with all its settings is
        # probably not very useful -- mbp 20070423
        dest_repo = self._create_sprouting_repo(a_bzrdir, shared=self.is_shared())
        self.copy_content_into(dest_repo, revision_id)
        return dest_repo

    def start_write_group(self):
        """Start a write group in the repository.

        Write groups are used by repositories which do not have a 1:1 mapping
        between file ids and backend store to manage the insertion of data from
        both fetch and commit operations.

        A write lock is required around the start_write_group/commit_write_group
        for the support of lock-requiring repository formats.

        One can only insert data into a repository inside a write group.

        :return: None.
        """
        if not self.is_write_locked():
            raise errors.NotWriteLocked(self)
        if self._write_group:
            raise errors.BzrError('already in a write group')
        self._start_write_group()
        # so we can detect unlock/relock - the write group is now entered.
        self._write_group = self.get_transaction()

    def _start_write_group(self):
        """Template method for per-repository write group startup.

        This is called before the write group is considered to be
        entered.
        """

    @needs_read_lock
    def sprout(self, to_bzrdir, revision_id=None):
        """Create a descendent repository for new development.

        Unlike clone, this does not copy the settings of the repository.
        """
        dest_repo = self._create_sprouting_repo(to_bzrdir, shared=False)
        dest_repo.fetch(self, revision_id=revision_id)
        return dest_repo

    def _create_sprouting_repo(self, a_bzrdir, shared):
        if not isinstance(a_bzrdir._format, self.bzrdir._format.__class__):
            # use target default format.
            dest_repo = a_bzrdir.create_repository()
        else:
            # Most control formats need the repository to be specifically
            # created, but on some old all-in-one formats it's not needed
            try:
                dest_repo = self._format.initialize(a_bzrdir, shared=shared)
            except errors.UninitializableFormat:
                dest_repo = a_bzrdir.open_repository()
        return dest_repo

    @needs_read_lock
    def has_revision(self, revision_id):
        """True if this repository has a copy of the revision."""
        return revision_id in self.has_revisions((revision_id,))

    @needs_read_lock
    def has_revisions(self, revision_ids):
        """Probe to find out the presence of multiple revisions.

        :param revision_ids: An iterable of revision_ids.
        :return: A set of the revision_ids that were present.
        """
        raise NotImplementedError(self.has_revisions)

    @needs_read_lock
    def get_revision(self, revision_id):
        """Return the Revision object for a named revision."""
        return self.get_revisions([revision_id])[0]

    def get_revision_reconcile(self, revision_id):
        """'reconcile' helper routine that allows access to a revision always.

        This variant of get_revision does not cross check the weave graph
        against the revision one as get_revision does: but it should only
        be used by reconcile, or reconcile-alike commands that are correcting
        or testing the revision graph.
        """
        raise NotImplementedError(self.get_revision_reconcile)

    def get_revisions(self, revision_ids):
        """Get many revisions at once.
        
        Repositories that need to check data on every revision read should 
        subclass this method.
        """
        raise NotImplementedError(self.get_revisions)

    def get_deltas_for_revisions(self, revisions, specific_fileids=None):
        """Produce a generator of revision deltas.

        Note that the input is a sequence of REVISIONS, not revision_ids.
        Trees will be held in memory until the generator exits.
        Each delta is relative to the revision's lefthand predecessor.

        :param specific_fileids: if not None, the result is filtered
          so that only those file-ids, their parents and their
          children are included.
        """
        # Get the revision-ids of interest
        required_trees = set()
        for revision in revisions:
            required_trees.add(revision.revision_id)
            required_trees.update(revision.parent_ids[:1])

        # Get the matching filtered trees. Note that it's more
        # efficient to pass filtered trees to changes_from() rather
        # than doing the filtering afterwards. changes_from() could
        # arguably do the filtering itself but it's path-based, not
        # file-id based, so filtering before or afterwards is
        # currently easier.
        if specific_fileids is None:
            trees = dict((t.get_revision_id(), t) for
                t in self.revision_trees(required_trees))
        else:
            trees = dict((t.get_revision_id(), t) for
                t in self._filtered_revision_trees(required_trees,
                specific_fileids))

        # Calculate the deltas
        for revision in revisions:
            if not revision.parent_ids:
                old_tree = self.revision_tree(_mod_revision.NULL_REVISION)
            else:
                old_tree = trees[revision.parent_ids[0]]
            yield trees[revision.revision_id].changes_from(old_tree)

    @needs_read_lock
    def get_revision_delta(self, revision_id, specific_fileids=None):
        """Return the delta for one revision.

        The delta is relative to the left-hand predecessor of the
        revision.

        :param specific_fileids: if not None, the result is filtered
          so that only those file-ids, their parents and their
          children are included.
        """
        r = self.get_revision(revision_id)
        return list(self.get_deltas_for_revisions([r],
            specific_fileids=specific_fileids))[0]

    @needs_write_lock
    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        signature = gpg_strategy.sign(plaintext)
        self.add_signature_text(revision_id, signature)

    def add_signature_text(self, revision_id, signature):
        """Store a signature text for a revision.

        :param revision_id: Revision id of the revision
        :param signature: Signature text.
        """
        raise NotImplementedError(self.add_signature_text)

    def find_text_key_references(self):
        """Find the text key references within the repository.

        :return: A dictionary mapping text keys ((fileid, revision_id) tuples)
            to whether they were referred to by the tree of the
            revision_id that they contain. 
        """
        raise NotImplementedError(self.find_text_key_references)

    def _find_parent_ids_of_revisions(self, revision_ids):
        """Find all parent ids that are mentioned in the revision graph.

        :return: set of revisions that are parents of revision_ids which are
            not part of revision_ids themselves
        """
        parent_map = self.get_parent_map(revision_ids)
        parent_ids = set()
        map(parent_ids.update, parent_map.itervalues())
        parent_ids.difference_update(revision_ids)
        parent_ids.discard(_mod_revision.NULL_REVISION)
        return parent_ids

    def fileids_altered_by_revision_ids(self, revision_ids):
        """Find the file ids and versions affected by revisions.

        :param revisions: an iterable containing revision ids.
        :return: a dictionary mapping altered file-ids to an iterable of
            revision_ids. Each altered file-ids has the exact revision_ids
            that altered it listed explicitly.
        """
        raise NotImplementedError(self.fileids_altered_by_revision_ids)

    def iter_files_bytes(self, desired_files):
        """Iterate through file versions.

        Files will not necessarily be returned in the order they occur in
        desired_files.  No specific order is guaranteed.

        Yields pairs of identifier, bytes_iterator.  identifier is an opaque
        value supplied by the caller as part of desired_files.  It should
        uniquely identify the file version in the caller's context.  (Examples:
        an index number or a TreeTransform trans_id.)

        :param desired_files: a list of (file_id, revision_id, identifier)
            triples
        """
        raise NotImplementedError(self.iter_files_bytes)

    def get_rev_id_for_revno(self, revno, known_pair):
        """Return the revision id of a revno, given a later (revno, revid)
        pair in the same history.

        :return: if found (True, revid).  If the available history ran out
            before reaching the revno, then this returns
            (False, (closest_revno, closest_revid)).
        """
        known_revno, known_revid = known_pair
        partial_history = [known_revid]
        distance_from_known = known_revno - revno
        if distance_from_known < 0:
            raise ValueError(
                'requested revno (%d) is later than given known revno (%d)'
                % (revno, known_revno))
        try:
            _iter_for_revno(
                self, partial_history, stop_index=distance_from_known)
        except errors.RevisionNotPresent, err:
            if err.revision_id == known_revid:
                # The start revision (known_revid) wasn't found.
                raise
            # This is a stacked repository with no fallbacks, or a there's a
            # left-hand ghost.  Either way, even though the revision named in
            # the error isn't in this repo, we know it's the next step in this
            # left-hand history.
            partial_history.append(err.revision_id)
        if len(partial_history) <= distance_from_known:
            # Didn't find enough history to get a revid for the revno.
            earliest_revno = known_revno - len(partial_history) + 1
            return (False, (earliest_revno, partial_history[-1]))
        if len(partial_history) - 1 > distance_from_known:
            raise AssertionError('_iter_for_revno returned too much history')
        return (True, partial_history[-1])

    def iter_reverse_revision_history(self, revision_id):
        """Iterate backwards through revision ids in the lefthand history

        :param revision_id: The revision id to start with.  All its lefthand
            ancestors will be traversed.
        """
        graph = self.get_graph()
        stop_revisions = (None, _mod_revision.NULL_REVISION)
        return graph.iter_lefthand_ancestry(revision_id, stop_revisions)

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        raise NotImplementedError(self.is_shared)

    @needs_write_lock
    def reconcile(self, other=None, thorough=False):
        """Reconcile this repository."""
        from bzrlib.reconcile import RepoReconciler
        reconciler = RepoReconciler(self, thorough=thorough)
        reconciler.reconcile()
        return reconciler

    def _refresh_data(self):
        """Helper called from lock_* to ensure coherency with disk.

        The default implementation does nothing; it is however possible
        for repositories to maintain loaded indices across multiple locks
        by checking inside their implementation of this method to see
        whether their indices are still valid. This depends of course on
        the disk format being validatable in this manner. This method is
        also called by the refresh_data() public interface to cause a refresh
        to occur while in a write lock so that data inserted by a smart server
        push operation is visible on the client's instance of the physical
        repository.
        """

    @needs_read_lock
    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be NULL_REVISION for the empty tree revision.
        """
        raise NotImplementedError(self.revision_tree)

    def revision_trees(self, revision_ids):
        """Return Trees for revisions in this repository.

        :param revision_ids: a sequence of revision-ids;
          a revision-id may not be None or 'null:'
        """
        raise NotImplementedError(self.revision_trees)

    @needs_read_lock
    def get_ancestry(self, revision_id, topo_sorted=True):
        """Return a list of revision-ids integrated by a revision.

        The first element of the list is always None, indicating the origin
        revision.  This might change when we have history horizons, or
        perhaps we should have a new API.

        This is topologically sorted.
        """
        if _mod_revision.is_null(revision_id):
            return [None]
        if not self.has_revision(revision_id):
            raise errors.NoSuchRevision(self, revision_id)
        graph = self.get_graph()
        keys = set()
        search = graph._make_breadth_first_searcher([revision_id])
        while True:
            try:
                found, ghosts = search.next_with_ghosts()
            except StopIteration:
                break
            keys.update(found)
        if _mod_revision.NULL_REVISION in keys:
            keys.remove(_mod_revision.NULL_REVISION)
        if topo_sorted:
            parent_map = graph.get_parent_map(keys)
            keys = tsort.topo_sort(parent_map)
        return [None] + list(keys)

    def pack(self, hint=None, clean_obsolete_packs=False):
        """Compress the data within the repository.

        This operation only makes sense for some repository types. For other
        types it should be a no-op that just returns.

        This stub method does not require a lock, but subclasses should use
        @needs_write_lock as this is a long running call it's reasonable to
        implicitly lock for the user.

        :param hint: If not supplied, the whole repository is packed.
            If supplied, the repository may use the hint parameter as a
            hint for the parts of the repository to pack. A hint can be
            obtained from the result of commit_write_group(). Out of
            date hints are simply ignored, because concurrent operations
            can obsolete them rapidly.

        :param clean_obsolete_packs: Clean obsolete packs immediately after
            the pack operation.
        """

    def get_transaction(self):
        return self.control_files.get_transaction()

    def get_parent_map(self, revision_ids):
        """See graph.StackedParentsProvider.get_parent_map"""
        raise NotImplementedError(self.get_parent_map)

    def _make_parents_provider(self):
        return self

    @needs_read_lock
    def get_known_graph_ancestry(self, revision_ids):
        """Return the known graph for a set of revision ids and their ancestors.
        """
        raise NotImplementedError(self.get_known_graph_ancestry)

    def get_graph(self, other_repository=None):
        """Return the graph walker for this repository format"""
        parents_provider = self._make_parents_provider()
        if (other_repository is not None and
            not self.has_same_location(other_repository)):
            parents_provider = graph.StackedParentsProvider(
                [parents_provider, other_repository._make_parents_provider()])
        return graph.Graph(parents_provider)

    def revision_ids_to_search_result(self, result_set):
        """Convert a set of revision ids to a graph SearchResult."""
        result_parents = set()
        for parents in self.get_graph().get_parent_map(
            result_set).itervalues():
            result_parents.update(parents)
        included_keys = result_set.intersection(result_parents)
        start_keys = result_set.difference(included_keys)
        exclude_keys = result_parents.difference(result_set)
        result = graph.SearchResult(start_keys, exclude_keys,
            len(result_set), result_set)
        return result

    @needs_write_lock
    def set_make_working_trees(self, new_value):
        """Set the policy flag for making working trees when creating branches.

        This only applies to branches that use this repository.

        The default is 'True'.
        :param new_value: True to restore the default, False to disable making
                          working trees.
        """
        raise NotImplementedError(self.set_make_working_trees)

    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        raise NotImplementedError(self.make_working_trees)

    @needs_write_lock
    def sign_revision(self, revision_id, gpg_strategy):
        plaintext = Testament.from_revision(self, revision_id).as_short_text()
        self.store_revision_signature(gpg_strategy, plaintext, revision_id)

    def has_signature_for_revision_id(self, revision_id):
        """Query for a revision signature for revision_id in the repository."""
        raise NotImplementedError(self.has_signature_for_revision_id)

    def get_signature_text(self, revision_id):
        """Return the text for a signature."""
        raise NotImplementedError(self.get_signature_text)

    @needs_read_lock
    def check(self, revision_ids=None, callback_refs=None, check_repo=True):
        """Check consistency of all history of given revision_ids.

        Different repository implementations should override _check().

        :param revision_ids: A non-empty list of revision_ids whose ancestry
             will be checked.  Typically the last revision_id of a branch.
        :param callback_refs: A dict of check-refs to resolve and callback
            the check/_check method on the items listed as wanting the ref.
            see bzrlib.check.
        :param check_repo: If False do not check the repository contents, just 
            calculate the data callback_refs requires and call them back.
        """
        return self._check(revision_ids, callback_refs=callback_refs,
            check_repo=check_repo)

    def _check(self, revision_ids, callback_refs, check_repo):
        result = check.Check(self, check_repo=check_repo)
        result.check(callback_refs)
        return result

    def _warn_if_deprecated(self, branch=None):
        if not self._format.is_deprecated():
            return
        global _deprecation_warning_done
        if _deprecation_warning_done:
            return
        try:
            if branch is None:
                conf = config.GlobalConfig()
            else:
                conf = branch.get_config()
            if conf.suppress_warning('format_deprecation'):
                return
            warning("Format %s for %s is deprecated -"
                    " please use 'bzr upgrade' to get better performance"
                    % (self._format, self.bzrdir.transport.base))
        finally:
            _deprecation_warning_done = True

    def supports_rich_root(self):
        return self._format.rich_root_data

    def _check_ascii_revisionid(self, revision_id, method):
        """Private helper for ascii-only repositories."""
        # weave repositories refuse to store revisionids that are non-ascii.
        if revision_id is not None:
            # weaves require ascii revision ids.
            if isinstance(revision_id, unicode):
                try:
                    revision_id.encode('ascii')
                except UnicodeEncodeError:
                    raise errors.NonAsciiRevisionId(method, self)
            else:
                try:
                    revision_id.decode('ascii')
                except UnicodeDecodeError:
                    raise errors.NonAsciiRevisionId(method, self)


class MetaDirRepository(Repository):
    """Repositories in the new meta-dir layout.

    :ivar _transport: Transport for access to repository control files,
        typically pointing to .bzr/repository.
    """

    def __init__(self, _format, a_bzrdir, control_files):
        super(MetaDirRepository, self).__init__(_format, a_bzrdir, control_files)
        self._transport = control_files._transport

    def is_shared(self):
        """Return True if this repository is flagged as a shared repository."""
        return self._transport.has('shared-storage')

    @needs_write_lock
    def set_make_working_trees(self, new_value):
        """Set the policy flag for making working trees when creating branches.

        This only applies to branches that use this repository.

        The default is 'True'.
        :param new_value: True to restore the default, False to disable making
                          working trees.
        """
        if new_value:
            try:
                self._transport.delete('no-working-trees')
            except errors.NoSuchFile:
                pass
        else:
            self._transport.put_bytes('no-working-trees', '',
                mode=self.bzrdir._get_file_mode())

    def make_working_trees(self):
        """Returns the policy for making working trees on new branches."""
        return not self._transport.has('no-working-trees')


class RepositoryFormatRegistry(controldir.ControlComponentFormatRegistry):
    """Repository format registry."""

    def get_default(self):
        """Return the current default format."""
        from bzrlib import bzrdir
        return bzrdir.format_registry.make_bzrdir('default').repository_format


network_format_registry = registry.FormatRegistry()
"""Registry of formats indexed by their network name.

The network name for a repository format is an identifier that can be used when
referring to formats with smart server operations. See
RepositoryFormat.network_name() for more detail.
"""


format_registry = RepositoryFormatRegistry(network_format_registry)
"""Registry of formats, indexed by their BzrDirMetaFormat format string.

This can contain either format instances themselves, or classes/factories that
can be called to obtain one.
"""


#####################################################################
# Repository Formats

class RepositoryFormat(controldir.ControlComponentFormat):
    """A repository format.

    Formats provide four things:
     * An initialization routine to construct repository data on disk.
     * a optional format string which is used when the BzrDir supports
       versioned children.
     * an open routine which returns a Repository instance.
     * A network name for referring to the format in smart server RPC
       methods.

    There is one and only one Format subclass for each on-disk format. But
    there can be one Repository subclass that is used for several different
    formats. The _format attribute on a Repository instance can be used to
    determine the disk format.

    Formats are placed in a registry by their format string for reference
    during opening. These should be subclasses of RepositoryFormat for
    consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the
    object may be created even when a repository instance hasn't been
    created.

    Common instance attributes:
    _matchingbzrdir - the bzrdir format that the repository format was
    originally written to work with. This can be used if manually
    constructing a bzrdir and repository, or more commonly for test suite
    parameterization.
    """

    # Set to True or False in derived classes. True indicates that the format
    # supports ghosts gracefully.
    supports_ghosts = None
    # Can this repository be given external locations to lookup additional
    # data. Set to True or False in derived classes.
    supports_external_lookups = None
    # Does this format support CHK bytestring lookups. Set to True or False in
    # derived classes.
    supports_chks = None
    # Should commit add an inventory, or an inventory delta to the repository.
    _commit_inv_deltas = True
    # What order should fetch operations request streams in?
    # The default is unordered as that is the cheapest for an origin to
    # provide.
    _fetch_order = 'unordered'
    # Does this repository format use deltas that can be fetched as-deltas ?
    # (E.g. knits, where the knit deltas can be transplanted intact.
    # We default to False, which will ensure that enough data to get
    # a full text out of any fetch stream will be grabbed.
    _fetch_uses_deltas = False
    # Should fetch trigger a reconcile after the fetch? Only needed for
    # some repository formats that can suffer internal inconsistencies.
    _fetch_reconcile = False
    # Does this format have < O(tree_size) delta generation. Used to hint what
    # code path for commit, amongst other things.
    fast_deltas = None
    # Does doing a pack operation compress data? Useful for the pack UI command
    # (so if there is one pack, the operation can still proceed because it may
    # help), and for fetching when data won't have come from the same
    # compressor.
    pack_compresses = False
    # Does the repository storage understand references to trees?
    supports_tree_reference = None
    # Is the format experimental ?
    experimental = False
    # Does this repository format escape funky characters, or does it create files with
    # similar names as the versioned files in its contents on disk ?
    supports_funky_characters = None
    # Does this repository format support leaving locks?
    supports_leaving_lock = None
    # Does this format support the full VersionedFiles interface?
    supports_full_versioned_files = None
    # Does this format support signing revision signatures?
    supports_revision_signatures = True
    # Can the revision graph have incorrect parents?
    revision_graph_can_have_wrong_parents = None

    def __repr__(self):
        return "%s()" % self.__class__.__name__

    def __eq__(self, other):
        # format objects are generally stateless
        return isinstance(other, self.__class__)

    def __ne__(self, other):
        return not self == other

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the repository object in a_bzrdir.

        This is used by bzr native formats that have a "format" file in
        the repository.  Other methods may be used by different types of
        control directory.
        """
        try:
            transport = a_bzrdir.get_repository_transport(None)
            format_string = transport.get_bytes("format")
            return format_registry.get(format_string)
        except errors.NoSuchFile:
            raise errors.NoRepositoryPresent(a_bzrdir)
        except KeyError:
            raise errors.UnknownFormatError(format=format_string,
                                            kind='repository')

    @classmethod
    @symbol_versioning.deprecated_method(symbol_versioning.deprecated_in((2, 4, 0)))
    def register_format(klass, format):
        format_registry.register(format)

    @classmethod
    @symbol_versioning.deprecated_method(symbol_versioning.deprecated_in((2, 4, 0)))
    def unregister_format(klass, format):
        format_registry.remove(format)

    @classmethod
    @symbol_versioning.deprecated_method(symbol_versioning.deprecated_in((2, 4, 0)))
    def get_default_format(klass):
        """Return the current default format."""
        return format_registry.get_default()

    def get_format_string(self):
        """Return the ASCII format string that identifies this format.

        Note that in pre format ?? repositories the format string is
        not permitted nor written to disk.
        """
        raise NotImplementedError(self.get_format_string)

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    # TODO: this shouldn't be in the base class, it's specific to things that
    # use weaves or knits -- mbp 20070207
    def _get_versioned_file_store(self,
                                  name,
                                  transport,
                                  control_files,
                                  prefixed=True,
                                  versionedfile_class=None,
                                  versionedfile_kwargs={},
                                  escaped=False):
        if versionedfile_class is None:
            versionedfile_class = self._versionedfile_class
        weave_transport = control_files._transport.clone(name)
        dir_mode = control_files._dir_mode
        file_mode = control_files._file_mode
        return VersionedFileStore(weave_transport, prefixed=prefixed,
                                  dir_mode=dir_mode,
                                  file_mode=file_mode,
                                  versionedfile_class=versionedfile_class,
                                  versionedfile_kwargs=versionedfile_kwargs,
                                  escaped=escaped)

    def initialize(self, a_bzrdir, shared=False):
        """Initialize a repository of this format in a_bzrdir.

        :param a_bzrdir: The bzrdir to put the new repository in it.
        :param shared: The repository should be initialized as a sharable one.
        :returns: The new repository object.

        This may raise UninitializableFormat if shared repository are not
        compatible the a_bzrdir.
        """
        raise NotImplementedError(self.initialize)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or
        some other features depending on the reason for not being supported.
        """
        return True

    def is_deprecated(self):
        """Is this format deprecated?

        Deprecated formats may trigger a user-visible warning recommending
        the user to upgrade. They are still fully supported.
        """
        return False

    def network_name(self):
        """A simple byte string uniquely identifying this format for RPC calls.

        MetaDir repository formats use their disk format string to identify the
        repository over the wire. All in one formats such as bzr < 0.8, and
        foreign formats like svn/git and hg should use some marker which is
        unique and immutable.
        """
        raise NotImplementedError(self.network_name)

    def check_conversion_target(self, target_format):
        if self.rich_root_data and not target_format.rich_root_data:
            raise errors.BadConversionTarget(
                'Does not support rich root data.', target_format,
                from_format=self)
        if (self.supports_tree_reference and 
            not getattr(target_format, 'supports_tree_reference', False)):
            raise errors.BadConversionTarget(
                'Does not support nested trees', target_format,
                from_format=self)

    def open(self, a_bzrdir, _found=False):
        """Return an instance of this format for the bzrdir a_bzrdir.

        _found is a private parameter, do not use it.
        """
        raise NotImplementedError(self.open)

    def _run_post_repo_init_hooks(self, repository, a_bzrdir, shared):
        from bzrlib.bzrdir import BzrDir, RepoInitHookParams
        hooks = BzrDir.hooks['post_repo_init']
        if not hooks:
            return
        params = RepoInitHookParams(repository, self, a_bzrdir, shared)
        for hook in hooks:
            hook(params)


class MetaDirRepositoryFormat(RepositoryFormat):
    """Common base class for the new repositories using the metadir layout."""

    rich_root_data = False
    supports_tree_reference = False
    supports_external_lookups = False
    supports_leaving_lock = True

    @property
    def _matchingbzrdir(self):
        matching = bzrdir.BzrDirMetaFormat1()
        matching.repository_format = self
        return matching

    def __init__(self):
        super(MetaDirRepositoryFormat, self).__init__()

    def _create_control_files(self, a_bzrdir):
        """Create the required files and the initial control_files object."""
        # FIXME: RBC 20060125 don't peek under the covers
        # NB: no need to escape relative paths that are url safe.
        repository_transport = a_bzrdir.get_repository_transport(self)
        control_files = lockable_files.LockableFiles(repository_transport,
                                'lock', lockdir.LockDir)
        control_files.create_lock()
        return control_files

    def _upload_blank_content(self, a_bzrdir, dirs, files, utf8_files, shared):
        """Upload the initial blank content."""
        control_files = self._create_control_files(a_bzrdir)
        control_files.lock_write()
        transport = control_files._transport
        if shared == True:
            utf8_files += [('shared-storage', '')]
        try:
            transport.mkdir_multi(dirs, mode=a_bzrdir._get_dir_mode())
            for (filename, content_stream) in files:
                transport.put_file(filename, content_stream,
                    mode=a_bzrdir._get_file_mode())
            for (filename, content_bytes) in utf8_files:
                transport.put_bytes_non_atomic(filename, content_bytes,
                    mode=a_bzrdir._get_file_mode())
        finally:
            control_files.unlock()

    def network_name(self):
        """Metadir formats have matching disk and network format strings."""
        return self.get_format_string()


# formats which have no format string are not discoverable or independently
# creatable on disk, so are not registered in format_registry.  They're
# all in bzrlib.repofmt.knitreponow.  When an instance of one of these is
# needed, it's constructed directly by the BzrDir.  Non-native formats where
# the repository is not separately opened are similar.

format_registry.register_lazy(
    'Bazaar-NG Knit Repository Format 1',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatKnit1',
    )

format_registry.register_lazy(
    'Bazaar Knit Repository Format 3 (bzr 0.15)\n',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatKnit3',
    )

format_registry.register_lazy(
    'Bazaar Knit Repository Format 4 (bzr 1.0)\n',
    'bzrlib.repofmt.knitrepo',
    'RepositoryFormatKnit4',
    )

# Pack-based formats. There is one format for pre-subtrees, and one for
# post-subtrees to allow ease of testing.
# NOTE: These are experimental in 0.92. Stable in 1.0 and above
format_registry.register_lazy(
    'Bazaar pack repository format 1 (needs bzr 0.92)\n',
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatKnitPack1',
    )
format_registry.register_lazy(
    'Bazaar pack repository format 1 with subtree support (needs bzr 0.92)\n',
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatKnitPack3',
    )
format_registry.register_lazy(
    'Bazaar pack repository format 1 with rich root (needs bzr 1.0)\n',
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatKnitPack4',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack5 (bzr 1.6)\n',
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatKnitPack5',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6.1)\n',
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatKnitPack5RichRoot',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack5RichRoot (bzr 1.6)\n',
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatKnitPack5RichRootBroken',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack6 (bzr 1.9)\n',
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatKnitPack6',
    )
format_registry.register_lazy(
    'Bazaar RepositoryFormatKnitPack6RichRoot (bzr 1.9)\n',
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatKnitPack6RichRoot',
    )
format_registry.register_lazy(
    'Bazaar repository format 2a (needs bzr 1.16 or later)\n',
    'bzrlib.repofmt.groupcompress_repo',
    'RepositoryFormat2a',
    )

# Development formats.
# Check their docstrings to see if/when they are obsolete.
format_registry.register_lazy(
    ("Bazaar development format 2 with subtree support "
        "(needs bzr.dev from before 1.8)\n"),
    'bzrlib.repofmt.knitpack_repo',
    'RepositoryFormatPackDevelopment2Subtree',
    )
format_registry.register_lazy(
    'Bazaar development format 8\n',
    'bzrlib.repofmt.groupcompress_repo',
    'RepositoryFormat2aSubtree',
    )


class InterRepository(InterObject):
    """This class represents operations taking place between two repositories.

    Its instances have methods like copy_content and fetch, and contain
    references to the source and target repositories these operations can be
    carried out on.

    Often we will provide convenience methods on 'repository' which carry out
    operations with another repository - they will always forward to
    InterRepository.get(other).method_name(parameters).
    """

    _walk_to_common_revisions_batch_size = 50
    _optimisers = []
    """The available optimised InterRepository types."""

    @needs_write_lock
    def copy_content(self, revision_id=None):
        """Make a complete copy of the content in self into destination.

        This is a destructive operation! Do not use it on existing
        repositories.

        :param revision_id: Only copy the content needed to construct
                            revision_id and its parents.
        """
        try:
            self.target.set_make_working_trees(self.source.make_working_trees())
        except NotImplementedError:
            pass
        self.target.fetch(self.source, revision_id=revision_id)

    @needs_write_lock
    def fetch(self, revision_id=None, find_ghosts=False,
            fetch_spec=None):
        """Fetch the content required to construct revision_id.

        The content is copied from self.source to self.target.

        :param revision_id: if None all content is copied, if NULL_REVISION no
                            content is copied.
        :return: None.
        """
        ui.ui_factory.warn_experimental_format_fetch(self)
        from bzrlib.fetch import RepoFetcher
        # See <https://launchpad.net/bugs/456077> asking for a warning here
        if self.source._format.network_name() != self.target._format.network_name():
            ui.ui_factory.show_user_warning('cross_format_fetch',
                from_format=self.source._format,
                to_format=self.target._format)
        f = RepoFetcher(to_repository=self.target,
                               from_repository=self.source,
                               last_revision=revision_id,
                               fetch_spec=fetch_spec,
                               find_ghosts=find_ghosts)

    def _walk_to_common_revisions(self, revision_ids, if_present_ids=None):
        """Walk out from revision_ids in source to revisions target has.

        :param revision_ids: The start point for the search.
        :return: A set of revision ids.
        """
        target_graph = self.target.get_graph()
        revision_ids = frozenset(revision_ids)
        if if_present_ids:
            all_wanted_revs = revision_ids.union(if_present_ids)
        else:
            all_wanted_revs = revision_ids
        missing_revs = set()
        source_graph = self.source.get_graph()
        # ensure we don't pay silly lookup costs.
        searcher = source_graph._make_breadth_first_searcher(all_wanted_revs)
        null_set = frozenset([_mod_revision.NULL_REVISION])
        searcher_exhausted = False
        while True:
            next_revs = set()
            ghosts = set()
            # Iterate the searcher until we have enough next_revs
            while len(next_revs) < self._walk_to_common_revisions_batch_size:
                try:
                    next_revs_part, ghosts_part = searcher.next_with_ghosts()
                    next_revs.update(next_revs_part)
                    ghosts.update(ghosts_part)
                except StopIteration:
                    searcher_exhausted = True
                    break
            # If there are ghosts in the source graph, and the caller asked for
            # them, make sure that they are present in the target.
            # We don't care about other ghosts as we can't fetch them and
            # haven't been asked to.
            ghosts_to_check = set(revision_ids.intersection(ghosts))
            revs_to_get = set(next_revs).union(ghosts_to_check)
            if revs_to_get:
                have_revs = set(target_graph.get_parent_map(revs_to_get))
                # we always have NULL_REVISION present.
                have_revs = have_revs.union(null_set)
                # Check if the target is missing any ghosts we need.
                ghosts_to_check.difference_update(have_revs)
                if ghosts_to_check:
                    # One of the caller's revision_ids is a ghost in both the
                    # source and the target.
                    raise errors.NoSuchRevision(
                        self.source, ghosts_to_check.pop())
                missing_revs.update(next_revs - have_revs)
                # Because we may have walked past the original stop point, make
                # sure everything is stopped
                stop_revs = searcher.find_seen_ancestors(have_revs)
                searcher.stop_searching_any(stop_revs)
            if searcher_exhausted:
                break
        return searcher.get_result()

    @needs_read_lock
    def search_missing_revision_ids(self,
            revision_id=symbol_versioning.DEPRECATED_PARAMETER,
            find_ghosts=True, revision_ids=None, if_present_ids=None):
        """Return the revision ids that source has that target does not.

        :param revision_id: only return revision ids included by this
            revision_id.
        :param revision_ids: return revision ids included by these
            revision_ids.  NoSuchRevision will be raised if any of these
            revisions are not present.
        :param if_present_ids: like revision_ids, but will not cause
            NoSuchRevision if any of these are absent, instead they will simply
            not be in the result.  This is useful for e.g. finding revisions
            to fetch for tags, which may reference absent revisions.
        :param find_ghosts: If True find missing revisions in deep history
            rather than just finding the surface difference.
        :return: A bzrlib.graph.SearchResult.
        """
        if symbol_versioning.deprecated_passed(revision_id):
            symbol_versioning.warn(
                'search_missing_revision_ids(revision_id=...) was '
                'deprecated in 2.4.  Use revision_ids=[...] instead.',
                DeprecationWarning, stacklevel=2)
            if revision_ids is not None:
                raise AssertionError(
                    'revision_ids is mutually exclusive with revision_id')
            if revision_id is not None:
                revision_ids = [revision_id]
        del revision_id
        # stop searching at found target revisions.
        if not find_ghosts and (revision_ids is not None or if_present_ids is
                not None):
            return self._walk_to_common_revisions(revision_ids,
                    if_present_ids=if_present_ids)
        # generic, possibly worst case, slow code path.
        target_ids = set(self.target.all_revision_ids())
        source_ids = self._present_source_revisions_for(
            revision_ids, if_present_ids)
        result_set = set(source_ids).difference(target_ids)
        return self.source.revision_ids_to_search_result(result_set)

    def _present_source_revisions_for(self, revision_ids, if_present_ids=None):
        """Returns set of all revisions in ancestry of revision_ids present in
        the source repo.

        :param revision_ids: if None, all revisions in source are returned.
        :param if_present_ids: like revision_ids, but if any/all of these are
            absent no error is raised.
        """
        if revision_ids is not None or if_present_ids is not None:
            # First, ensure all specified revisions exist.  Callers expect
            # NoSuchRevision when they pass absent revision_ids here.
            if revision_ids is None:
                revision_ids = set()
            if if_present_ids is None:
                if_present_ids = set()
            revision_ids = set(revision_ids)
            if_present_ids = set(if_present_ids)
            all_wanted_ids = revision_ids.union(if_present_ids)
            graph = self.source.get_graph()
            present_revs = set(graph.get_parent_map(all_wanted_ids))
            missing = revision_ids.difference(present_revs)
            if missing:
                raise errors.NoSuchRevision(self.source, missing.pop())
            found_ids = all_wanted_ids.intersection(present_revs)
            source_ids = [rev_id for (rev_id, parents) in
                          graph.iter_ancestry(found_ids)
                          if rev_id != _mod_revision.NULL_REVISION
                          and parents is not None]
        else:
            source_ids = self.source.all_revision_ids()
        return set(source_ids)

    @staticmethod
    def _same_model(source, target):
        """True if source and target have the same data representation.

        Note: this is always called on the base class; overriding it in a
        subclass will have no effect.
        """
        try:
            InterRepository._assert_same_model(source, target)
            return True
        except errors.IncompatibleRepositories, e:
            return False

    @staticmethod
    def _assert_same_model(source, target):
        """Raise an exception if two repositories do not use the same model.
        """
        if source.supports_rich_root() != target.supports_rich_root():
            raise errors.IncompatibleRepositories(source, target,
                "different rich-root support")
        if source._serializer != target._serializer:
            raise errors.IncompatibleRepositories(source, target,
                "different serializers")


class InterSameDataRepository(InterRepository):
    """Code for converting between repositories that represent the same data.

    Data format and model must match for this to work.
    """

    @classmethod
    def _get_repo_format_to_test(self):
        """Repository format for testing with.

        InterSameData can pull from subtree to subtree and from non-subtree to
        non-subtree, so we test this with the richest repository format.
        """
        from bzrlib.repofmt import knitrepo
        return knitrepo.RepositoryFormatKnit3()

    @staticmethod
    def is_compatible(source, target):
        return InterRepository._same_model(source, target)


InterRepository.register_optimiser(InterSameDataRepository)


class CopyConverter(object):
    """A repository conversion tool which just performs a copy of the content.

    This is slow but quite reliable.
    """

    def __init__(self, target_format):
        """Create a CopyConverter.

        :param target_format: The format the resulting repository should be.
        """
        self.target_format = target_format

    def convert(self, repo, pb):
        """Perform the conversion of to_convert, giving feedback via pb.

        :param to_convert: The disk object to convert.
        :param pb: a progress bar to use for progress information.
        """
        pb = ui.ui_factory.nested_progress_bar()
        self.count = 0
        self.total = 4
        # this is only useful with metadir layouts - separated repo content.
        # trigger an assertion if not such
        repo._format.get_format_string()
        self.repo_dir = repo.bzrdir
        pb.update('Moving repository to repository.backup')
        self.repo_dir.transport.move('repository', 'repository.backup')
        backup_transport =  self.repo_dir.transport.clone('repository.backup')
        repo._format.check_conversion_target(self.target_format)
        self.source_repo = repo._format.open(self.repo_dir,
            _found=True,
            _override_transport=backup_transport)
        pb.update('Creating new repository')
        converted = self.target_format.initialize(self.repo_dir,
                                                  self.source_repo.is_shared())
        converted.lock_write()
        try:
            pb.update('Copying content')
            self.source_repo.copy_content_into(converted)
        finally:
            converted.unlock()
        pb.update('Deleting old repository content')
        self.repo_dir.transport.delete_tree('repository.backup')
        ui.ui_factory.note('repository converted')
        pb.finished()


def _strip_NULL_ghosts(revision_graph):
    """Also don't use this. more compatibility code for unmigrated clients."""
    # Filter ghosts, and null:
    if _mod_revision.NULL_REVISION in revision_graph:
        del revision_graph[_mod_revision.NULL_REVISION]
    for key, parents in revision_graph.items():
        revision_graph[key] = tuple(parent for parent in parents if parent
            in revision_graph)
    return revision_graph


def _iter_for_revno(repo, partial_history_cache, stop_index=None,
                    stop_revision=None):
    """Extend the partial history to include a given index

    If a stop_index is supplied, stop when that index has been reached.
    If a stop_revision is supplied, stop when that revision is
    encountered.  Otherwise, stop when the beginning of history is
    reached.

    :param stop_index: The index which should be present.  When it is
        present, history extension will stop.
    :param stop_revision: The revision id which should be present.  When
        it is encountered, history extension will stop.
    """
    start_revision = partial_history_cache[-1]
    iterator = repo.iter_reverse_revision_history(start_revision)
    try:
        #skip the last revision in the list
        iterator.next()
        while True:
            if (stop_index is not None and
                len(partial_history_cache) > stop_index):
                break
            if partial_history_cache[-1] == stop_revision:
                break
            revision_id = iterator.next()
            partial_history_cache.append(revision_id)
    except StopIteration:
        # No more history
        return
