# Copyright (C) 2005, 2006 Canonical Ltd
#
# Authors:
#   Johan Rydberg <jrydberg@gnu.org>
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

"""Versioned text file storage api."""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from copy import deepcopy
import unittest

from bzrlib import (
    errors,
    osutils,
    multiparent,
    tsort,
    revision,
    ui,
    )
from bzrlib.transport.memory import MemoryTransport
""")

from bzrlib.inter import InterObject
from bzrlib.textmerge import TextMerge
from bzrlib.symbol_versioning import (deprecated_function,
        deprecated_method,
        zero_eight,
        )


class VersionedFile(object):
    """Versioned text file storage.
    
    A versioned file manages versions of line-based text files,
    keeping track of the originating version for each line.

    To clients the "lines" of the file are represented as a list of
    strings. These strings will typically have terminal newline
    characters, but this is not required.  In particular files commonly
    do not have a newline at the end of the file.

    Texts are identified by a version-id string.
    """

    def __init__(self, access_mode):
        self.finished = False
        self._access_mode = access_mode

    @staticmethod
    def check_not_reserved_id(version_id):
        revision.check_not_reserved_id(version_id)

    def copy_to(self, name, transport):
        """Copy this versioned file to name on transport."""
        raise NotImplementedError(self.copy_to)

    @deprecated_method(zero_eight)
    def names(self):
        """Return a list of all the versions in this versioned file.

        Please use versionedfile.versions() now.
        """
        return self.versions()

    def versions(self):
        """Return a unsorted list of versions."""
        raise NotImplementedError(self.versions)

    def has_ghost(self, version_id):
        """Returns whether version is present as a ghost."""
        raise NotImplementedError(self.has_ghost)

    def has_version(self, version_id):
        """Returns whether version is present."""
        raise NotImplementedError(self.has_version)

    def add_delta(self, version_id, parents, delta_parent, sha1, noeol, delta):
        """Add a text to the versioned file via a pregenerated delta.

        :param version_id: The version id being added.
        :param parents: The parents of the version_id.
        :param delta_parent: The parent this delta was created against.
        :param sha1: The sha1 of the full text.
        :param delta: The delta instructions. See get_delta for details.
        """
        version_id = osutils.safe_revision_id(version_id)
        parents = [osutils.safe_revision_id(v) for v in parents]
        self._check_write_ok()
        if self.has_version(version_id):
            raise errors.RevisionAlreadyPresent(version_id, self)
        return self._add_delta(version_id, parents, delta_parent, sha1, noeol, delta)

    def _add_delta(self, version_id, parents, delta_parent, sha1, noeol, delta):
        """Class specific routine to add a delta.

        This generic version simply applies the delta to the delta_parent and
        then inserts it.
        """
        # strip annotation from delta
        new_delta = []
        for start, stop, delta_len, delta_lines in delta:
            new_delta.append((start, stop, delta_len, [text for origin, text in delta_lines]))
        if delta_parent is not None:
            parent_full = self.get_lines(delta_parent)
        else:
            parent_full = []
        new_full = self._apply_delta(parent_full, new_delta)
        # its impossible to have noeol on an empty file
        if noeol and new_full[-1][-1] == '\n':
            new_full[-1] = new_full[-1][:-1]
        self.add_lines(version_id, parents, new_full)

    def add_lines(self, version_id, parents, lines, parent_texts=None):
        """Add a single text on top of the versioned file.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history.

        Must raise RevisionNotPresent if any of the given parents are
        not present in file history.
        :param parent_texts: An optional dictionary containing the opaque 
             representations of some or all of the parents of 
             version_id to allow delta optimisations. 
             VERY IMPORTANT: the texts must be those returned
             by add_lines or data corruption can be caused.
        :return: An opaque representation of the inserted version which can be
                 provided back to future add_lines calls in the parent_texts
                 dictionary.
        """
        version_id = osutils.safe_revision_id(version_id)
        parents = [osutils.safe_revision_id(v) for v in parents]
        self._check_write_ok()
        return self._add_lines(version_id, parents, lines, parent_texts)

    def _add_lines(self, version_id, parents, lines, parent_texts):
        """Helper to do the class specific add_lines."""
        raise NotImplementedError(self.add_lines)

    def add_lines_with_ghosts(self, version_id, parents, lines,
                              parent_texts=None):
        """Add lines to the versioned file, allowing ghosts to be present.
        
        This takes the same parameters as add_lines.
        """
        version_id = osutils.safe_revision_id(version_id)
        parents = [osutils.safe_revision_id(v) for v in parents]
        self._check_write_ok()
        return self._add_lines_with_ghosts(version_id, parents, lines,
                                           parent_texts)

    def _add_lines_with_ghosts(self, version_id, parents, lines, parent_texts):
        """Helper to do class specific add_lines_with_ghosts."""
        raise NotImplementedError(self.add_lines_with_ghosts)

    def check(self, progress_bar=None):
        """Check the versioned file for integrity."""
        raise NotImplementedError(self.check)

    def _check_lines_not_unicode(self, lines):
        """Check that lines being added to a versioned file are not unicode."""
        for line in lines:
            if line.__class__ is not str:
                raise errors.BzrBadParameterUnicode("lines")

    def _check_lines_are_lines(self, lines):
        """Check that the lines really are full lines without inline EOL."""
        for line in lines:
            if '\n' in line[:-1]:
                raise errors.BzrBadParameterContainsNewline("lines")

    def _check_write_ok(self):
        """Is the versioned file marked as 'finished' ? Raise if it is."""
        if self.finished:
            raise errors.OutSideTransaction()
        if self._access_mode != 'w':
            raise errors.ReadOnlyObjectDirtiedError(self)

    def enable_cache(self):
        """Tell this versioned file that it should cache any data it reads.
        
        This is advisory, implementations do not have to support caching.
        """
        pass
    
    def clear_cache(self):
        """Remove any data cached in the versioned file object.

        This only needs to be supported if caches are supported
        """
        pass

    def clone_text(self, new_version_id, old_version_id, parents):
        """Add an identical text to old_version_id as new_version_id.

        Must raise RevisionNotPresent if the old version or any of the
        parents are not present in file history.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history."""
        new_version_id = osutils.safe_revision_id(new_version_id)
        old_version_id = osutils.safe_revision_id(old_version_id)
        self._check_write_ok()
        return self._clone_text(new_version_id, old_version_id, parents)

    def _clone_text(self, new_version_id, old_version_id, parents):
        """Helper function to do the _clone_text work."""
        raise NotImplementedError(self.clone_text)

    def create_empty(self, name, transport, mode=None):
        """Create a new versioned file of this exact type.

        :param name: the file name
        :param transport: the transport
        :param mode: optional file mode.
        """
        raise NotImplementedError(self.create_empty)

    def fix_parents(self, version_id, new_parents):
        """Fix the parents list for version.
        
        This is done by appending a new version to the index
        with identical data except for the parents list.
        the parents list must be a superset of the current
        list.
        """
        version_id = osutils.safe_revision_id(version_id)
        new_parents = [osutils.safe_revision_id(p) for p in new_parents]
        self._check_write_ok()
        return self._fix_parents(version_id, new_parents)

    def _fix_parents(self, version_id, new_parents):
        """Helper for fix_parents."""
        raise NotImplementedError(self.fix_parents)

    def get_delta(self, version):
        """Get a delta for constructing version from some other version.
        
        :return: (delta_parent, sha1, noeol, delta)
        Where delta_parent is a version id or None to indicate no parent.
        """
        raise NotImplementedError(self.get_delta)

    def get_deltas(self, version_ids):
        """Get multiple deltas at once for constructing versions.
        
        :return: dict(version_id:(delta_parent, sha1, noeol, delta))
        Where delta_parent is a version id or None to indicate no parent, and
        version_id is the version_id created by that delta.
        """
        result = {}
        for version_id in version_ids:
            result[version_id] = self.get_delta(version_id)
        return result

    def make_mpdiffs(self, version_ids):
        knit_versions = set()
        for version_id in version_ids:
            knit_versions.add(version_id)
            knit_versions.update(self.get_parents(version_id))
        lines = dict(zip(knit_versions, self._get_line_list(knit_versions)))
        diffs = []
        for version_id in version_ids:
            target = lines[version_id]
            parents = [lines[p] for p in self.get_parents(version_id)]
            if len(parents) > 0:
                left_parent_blocks = self._extract_blocks(version_id,
                                                          parents[0], target)
            else:
                left_parent_blocks = None
            diffs.append(multiparent.MultiParent.from_lines(target, parents,
                         left_parent_blocks))
        return diffs

    def _extract_blocks(self, version_id, source, target):
        return None

    def add_mpdiffs(self, records):
        mpvf = multiparent.MultiMemoryVersionedFile()
        vf_parents = {}
        for version, parents, expected_sha1, mpdiff in records:
            needed_parents = [p for p in parents if not mpvf.has_version(p)]
            parent_lines = self._get_line_list(needed_parents)
            for parent_id, lines in zip(needed_parents, parent_lines):
                mpvf.add_version(lines, parent_id, [])
            mpvf.add_diff(mpdiff, version, parents)
            lines = mpvf.get_line_list([version])[0]
            version_text = self.add_lines(version, parents, lines, vf_parents)
            vf_parents[version] = version_text
            assert expected_sha1 == self.get_sha1(version)

    def get_sha1(self, version_id):
        """Get the stored sha1 sum for the given revision.
        
        :param name: The name of the version to lookup
        """
        raise NotImplementedError(self.get_sha1)

    def get_suffixes(self):
        """Return the file suffixes associated with this versioned file."""
        raise NotImplementedError(self.get_suffixes)
    
    def get_text(self, version_id):
        """Return version contents as a text string.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return ''.join(self.get_lines(version_id))
    get_string = get_text

    def get_texts(self, version_ids):
        """Return the texts of listed versions as a list of strings.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return [''.join(self.get_lines(v)) for v in version_ids]

    def get_lines(self, version_id):
        """Return version contents as a sequence of lines.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_lines)

    def _get_line_list(self, version_ids):
        return [t.splitlines(True) for t in self.get_texts(version_ids)]

    def get_ancestry(self, version_ids):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history."""
        if isinstance(version_ids, basestring):
            version_ids = [version_ids]
        raise NotImplementedError(self.get_ancestry)
        
    def get_ancestry_with_ghosts(self, version_ids):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history.
        
        Ghosts that are known about will be included in ancestry list,
        but are not explicitly marked.
        """
        raise NotImplementedError(self.get_ancestry_with_ghosts)
        
    def get_graph(self, version_ids=None):
        """Return a graph from the versioned file. 
        
        Ghosts are not listed or referenced in the graph.
        :param version_ids: Versions to select.
                            None means retrieve all versions.
        """
        result = {}
        if version_ids is None:
            for version in self.versions():
                result[version] = self.get_parents(version)
        else:
            pending = set(osutils.safe_revision_id(v) for v in version_ids)
            while pending:
                version = pending.pop()
                if version in result:
                    continue
                parents = self.get_parents(version)
                for parent in parents:
                    if parent in result:
                        continue
                    pending.add(parent)
                result[version] = parents
        return result

    def get_graph_with_ghosts(self):
        """Return a graph for the entire versioned file.
        
        Ghosts are referenced in parents list but are not
        explicitly listed.
        """
        raise NotImplementedError(self.get_graph_with_ghosts)

    @deprecated_method(zero_eight)
    def parent_names(self, version):
        """Return version names for parents of a version.
        
        See get_parents for the current api.
        """
        return self.get_parents(version)

    def get_parents(self, version_id):
        """Return version names for parents of a version.

        Must raise RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_parents)

    def get_parents_with_ghosts(self, version_id):
        """Return version names for parents of version_id.

        Will raise RevisionNotPresent if version_id is not present
        in the history.

        Ghosts that are known about will be included in the parent list,
        but are not explicitly marked.
        """
        raise NotImplementedError(self.get_parents_with_ghosts)

    def annotate_iter(self, version_id):
        """Yield list of (version-id, line) pairs for the specified
        version.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history.
        """
        raise NotImplementedError(self.annotate_iter)

    def annotate(self, version_id):
        return list(self.annotate_iter(version_id))

    def _apply_delta(self, lines, delta):
        """Apply delta to lines."""
        lines = list(lines)
        offset = 0
        for start, end, count, delta_lines in delta:
            lines[offset+start:offset+end] = delta_lines
            offset = offset + (start - end) + count
        return lines

    def join(self, other, pb=None, msg=None, version_ids=None,
             ignore_missing=False):
        """Integrate versions from other into this versioned file.

        If version_ids is None all versions from other should be
        incorporated into this versioned file.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the other files history unless ignore_missing
        is supplied when they are silently skipped.
        """
        self._check_write_ok()
        return InterVersionedFile.get(other, self).join(
            pb,
            msg,
            version_ids,
            ignore_missing)

    def iter_lines_added_or_present_in_versions(self, version_ids=None, 
                                                pb=None):
        """Iterate over the lines in the versioned file from version_ids.

        This may return lines from other versions, and does not return the
        specific version marker at this point. The api may be changed
        during development to include the version that the versioned file
        thinks is relevant, but given that such hints are just guesses,
        its better not to have it if we don't need it.

        If a progress bar is supplied, it may be used to indicate progress.
        The caller is responsible for cleaning up progress bars (because this
        is an iterator).

        NOTES: Lines are normalised: they will all have \n terminators.
               Lines are returned in arbitrary order.
        """
        raise NotImplementedError(self.iter_lines_added_or_present_in_versions)

    def transaction_finished(self):
        """The transaction that this file was opened in has finished.

        This records self.finished = True and should cause all mutating
        operations to error.
        """
        self.finished = True

    @deprecated_method(zero_eight)
    def walk(self, version_ids=None):
        """Walk the versioned file as a weave-like structure, for
        versions relative to version_ids.  Yields sequence of (lineno,
        insert, deletes, text) for each relevant line.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the file history.

        :param version_ids: the version_ids to walk with respect to. If not
                            supplied the entire weave-like structure is walked.

        walk is deprecated in favour of iter_lines_added_or_present_in_versions
        """
        raise NotImplementedError(self.walk)

    @deprecated_method(zero_eight)
    def iter_names(self):
        """Walk the names list."""
        return iter(self.versions())

    def plan_merge(self, ver_a, ver_b):
        """Return pseudo-annotation indicating how the two versions merge.

        This is computed between versions a and b and their common
        base.

        Weave lines present in none of them are skipped entirely.

        Legend:
        killed-base Dead in base revision
        killed-both Killed in each revision
        killed-a    Killed in a
        killed-b    Killed in b
        unchanged   Alive in both a and b (possibly created in both)
        new-a       Created in a
        new-b       Created in b
        ghost-a     Killed in a, unborn in b    
        ghost-b     Killed in b, unborn in a
        irrelevant  Not in either revision
        """
        raise NotImplementedError(VersionedFile.plan_merge)
        
    def weave_merge(self, plan, a_marker=TextMerge.A_MARKER,
                    b_marker=TextMerge.B_MARKER):
        return PlanWeaveMerge(plan, a_marker, b_marker).merge_lines()[0]


class PlanWeaveMerge(TextMerge):
    """Weave merge that takes a plan as its input.
    
    This exists so that VersionedFile.plan_merge is implementable.
    Most callers will want to use WeaveMerge instead.
    """

    def __init__(self, plan, a_marker=TextMerge.A_MARKER,
                 b_marker=TextMerge.B_MARKER):
        TextMerge.__init__(self, a_marker, b_marker)
        self.plan = plan

    def _merge_struct(self):
        lines_a = []
        lines_b = []
        ch_a = ch_b = False

        def outstanding_struct():
            if not lines_a and not lines_b:
                return
            elif ch_a and not ch_b:
                # one-sided change:
                yield(lines_a,)
            elif ch_b and not ch_a:
                yield (lines_b,)
            elif lines_a == lines_b:
                yield(lines_a,)
            else:
                yield (lines_a, lines_b)
       
        # We previously considered either 'unchanged' or 'killed-both' lines
        # to be possible places to resynchronize.  However, assuming agreement
        # on killed-both lines may be too aggressive. -- mbp 20060324
        for state, line in self.plan:
            if state == 'unchanged':
                # resync and flush queued conflicts changes if any
                for struct in outstanding_struct():
                    yield struct
                lines_a = []
                lines_b = []
                ch_a = ch_b = False
                
            if state == 'unchanged':
                if line:
                    yield ([line],)
            elif state == 'killed-a':
                ch_a = True
                lines_b.append(line)
            elif state == 'killed-b':
                ch_b = True
                lines_a.append(line)
            elif state == 'new-a':
                ch_a = True
                lines_a.append(line)
            elif state == 'new-b':
                ch_b = True
                lines_b.append(line)
            else:
                assert state in ('irrelevant', 'ghost-a', 'ghost-b', 
                                 'killed-base', 'killed-both'), state
        for struct in outstanding_struct():
            yield struct


class WeaveMerge(PlanWeaveMerge):
    """Weave merge that takes a VersionedFile and two versions as its input"""

    def __init__(self, versionedfile, ver_a, ver_b, 
        a_marker=PlanWeaveMerge.A_MARKER, b_marker=PlanWeaveMerge.B_MARKER):
        plan = versionedfile.plan_merge(ver_a, ver_b)
        PlanWeaveMerge.__init__(self, plan, a_marker, b_marker)


class InterVersionedFile(InterObject):
    """This class represents operations taking place between two versionedfiles..

    Its instances have methods like join, and contain
    references to the source and target versionedfiles these operations can be 
    carried out on.

    Often we will provide convenience methods on 'versionedfile' which carry out
    operations with another versionedfile - they will always forward to
    InterVersionedFile.get(other).method_name(parameters).
    """

    _optimisers = []
    """The available optimised InterVersionedFile types."""

    def join(self, pb=None, msg=None, version_ids=None, ignore_missing=False):
        """Integrate versions from self.source into self.target.

        If version_ids is None all versions from source should be
        incorporated into this versioned file.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the other files history unless ignore_missing is 
        supplied when they are silently skipped.
        """
        # the default join: 
        # - if the target is empty, just add all the versions from 
        #   source to target, otherwise:
        # - make a temporary versioned file of type target
        # - insert the source content into it one at a time
        # - join them
        if not self.target.versions():
            target = self.target
        else:
            # Make a new target-format versioned file. 
            temp_source = self.target.create_empty("temp", MemoryTransport())
            target = temp_source
        version_ids = self._get_source_version_ids(version_ids, ignore_missing)
        graph = self.source.get_graph(version_ids)
        order = tsort.topo_sort(graph.items())
        pb = ui.ui_factory.nested_progress_bar()
        parent_texts = {}
        try:
            # TODO for incremental cross-format work:
            # make a versioned file with the following content:
            # all revisions we have been asked to join
            # all their ancestors that are *not* in target already.
            # the immediate parents of the above two sets, with 
            # empty parent lists - these versions are in target already
            # and the incorrect version data will be ignored.
            # TODO: for all ancestors that are present in target already,
            # check them for consistent data, this requires moving sha1 from
            # 
            # TODO: remove parent texts when they are not relevant any more for 
            # memory pressure reduction. RBC 20060313
            # pb.update('Converting versioned data', 0, len(order))
            # deltas = self.source.get_deltas(order)
            for index, version in enumerate(order):
                pb.update('Converting versioned data', index, len(order))
                parent_text = target.add_lines(version,
                                               self.source.get_parents(version),
                                               self.source.get_lines(version),
                                               parent_texts=parent_texts)
                parent_texts[version] = parent_text
                #delta_parent, sha1, noeol, delta = deltas[version]
                #target.add_delta(version,
                #                 self.source.get_parents(version),
                #                 delta_parent,
                #                 sha1,
                #                 noeol,
                #                 delta)
                #target.get_lines(version)
            
            # this should hit the native code path for target
            if target is not self.target:
                return self.target.join(temp_source,
                                        pb,
                                        msg,
                                        version_ids,
                                        ignore_missing)
        finally:
            pb.finished()

    def _get_source_version_ids(self, version_ids, ignore_missing):
        """Determine the version ids to be used from self.source.

        :param version_ids: The caller-supplied version ids to check. (None 
                            for all). If None is in version_ids, it is stripped.
        :param ignore_missing: if True, remove missing ids from the version 
                               list. If False, raise RevisionNotPresent on
                               a missing version id.
        :return: A set of version ids.
        """
        if version_ids is None:
            # None cannot be in source.versions
            return set(self.source.versions())
        else:
            version_ids = [osutils.safe_revision_id(v) for v in version_ids]
            if ignore_missing:
                return set(self.source.versions()).intersection(set(version_ids))
            else:
                new_version_ids = set()
                for version in version_ids:
                    if version is None:
                        continue
                    if not self.source.has_version(version):
                        raise errors.RevisionNotPresent(version, str(self.source))
                    else:
                        new_version_ids.add(version)
                return new_version_ids


class InterVersionedFileTestProviderAdapter(object):
    """A tool to generate a suite testing multiple inter versioned-file classes.

    This is done by copying the test once for each InterVersionedFile provider
    and injecting the transport_server, transport_readonly_server,
    versionedfile_factory and versionedfile_factory_to classes into each copy.
    Each copy is also given a new id() to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        result = unittest.TestSuite()
        for (interversionedfile_class,
             versionedfile_factory,
             versionedfile_factory_to) in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.interversionedfile_class = interversionedfile_class
            new_test.versionedfile_factory = versionedfile_factory
            new_test.versionedfile_factory_to = versionedfile_factory_to
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), interversionedfile_class.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result

    @staticmethod
    def default_test_list():
        """Generate the default list of interversionedfile permutations to test."""
        from bzrlib.weave import WeaveFile
        from bzrlib.knit import KnitVersionedFile
        result = []
        # test the fallback InterVersionedFile from annotated knits to weave
        result.append((InterVersionedFile, 
                       KnitVersionedFile,
                       WeaveFile))
        for optimiser in InterVersionedFile._optimisers:
            result.append((optimiser,
                           optimiser._matching_file_from_factory,
                           optimiser._matching_file_to_factory
                           ))
        # if there are specific combinations we want to use, we can add them 
        # here.
        return result
