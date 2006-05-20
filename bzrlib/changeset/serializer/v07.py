# (C) 2005 Canonical Development Ltd

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

"""Serializer factory for reading and writing changesets.
"""

import os
from sha import sha

from bzrlib.changeset.serializer import (ChangesetSerializer, 
        CHANGESET_HEADER,
        format_highres_date, unpack_highres_date)
from bzrlib.changeset.common import testament_sha1
from bzrlib.changeset.serializer import binary_diff
from bzrlib.delta import compare_trees
from bzrlib.diff import internal_diff
import bzrlib.errors as errors
from bzrlib.osutils import pathjoin
from bzrlib.revision import NULL_REVISION
from bzrlib.rio import RioWriter, read_stanzas
import bzrlib.ui
from bzrlib.textfile import text_file

bool_text = {True: 'yes', False: 'no'}

class ChangesetSerializerV07(ChangesetSerializer):
    def read(self, f):
        """Read the rest of the changesets from the supplied file.

        :param f: The file to read from
        :return: A list of changesets
        """
        assert self.version == '0.7'
        # The first line of the header should have been read
        raise NotImplementedError

    def write(self, source, revision_ids, forced_bases, f):
        """Write the changesets to the supplied files.

        :param source: A source for revision information
        :param revision_ids: The list of revision ids to serialize
        :param forced_bases: A dict of revision -> base that overrides default
        :param f: The file to output to
        """
        self.source = source
        self.revision_ids = revision_ids
        self.forced_bases = forced_bases
        self.to_file = f
        source.lock_read()
        try:
            self._write_main_header()
            pb = bzrlib.ui.ui_factory.nested_progress_bar()
            try:
                self._write_revisions(pb)
            finally:
                pb.finished()
        finally:
            source.unlock()

    def _write_main_header(self):
        """Write the header for the changes"""
        f = self.to_file
        f.write(CHANGESET_HEADER)
        f.write('0.7\n')
        f.write('#\n')

    def _write(self, key, value, indent=1):
        """Write out meta information, with proper indenting, etc"""
        assert indent > 0, 'indentation must be greater than 0'
        f = self.to_file
        f.write('#' + (' ' * indent))
        f.write(key.encode('utf-8'))
        if not value:
            f.write(':\n')
        elif isinstance(value, basestring):
            f.write(': ')
            f.write(value.encode('utf-8'))
            f.write('\n')
        else:
            f.write(':\n')
            for entry in value:
                f.write('#' + (' ' * (indent+2)))
                f.write(entry.encode('utf-8'))
                f.write('\n')

    def _write_revisions(self, pb):
        """Write the information for all of the revisions."""

        # Optimize for the case of revisions in order
        last_rev_id = None
        last_rev_tree = None

        i_max = len(self.revision_ids) 
        for i, rev_id in enumerate(self.revision_ids):
            pb.update("Generating revsion data", i, i_max)
            rev = self.source.get_revision(rev_id)
            if rev_id == last_rev_id:
                rev_tree = last_rev_tree
            else:
                base_tree = self.source.revision_tree(rev_id)
            rev_tree = self.source.revision_tree(rev_id)
            if rev_id in self.forced_bases:
                explicit_base = True
                base_id = self.forced_bases[rev_id]
                if base_id is None:
                    base_id = NULL_REVISION
            else:
                explicit_base = False
                if rev.parent_ids:
                    base_id = rev.parent_ids[-1]
                else:
                    base_id = NULL_REVISION

            if base_id == last_rev_id:
                base_tree = last_rev_tree
            else:
                base_tree = self.source.revision_tree(base_id)

            self._write_revision(rev, rev_tree, base_id, base_tree, 
                                 explicit_base)

            last_rev_id = base_id
            last_rev_tree = base_tree

    def _write_revision(self, rev, rev_tree, base_rev, base_tree, 
                        explicit_base):
        """Write out the information for a revision."""
        def w(key, value):
            self._write(key, value, indent=1)

        w('message', rev.message.split('\n'))
        w('committer', rev.committer)
        w('date', format_highres_date(rev.timestamp, rev.timezone))
        self.to_file.write('\n')

        self._write_delta(rev_tree, base_tree, rev.revision_id)

        w('revision id', rev.revision_id)
        w('sha1', testament_sha1(self.source, rev.revision_id))
        w('inventory sha1', rev.inventory_sha1)
        if rev.parent_ids:
            w('parent ids', rev.parent_ids)
        if explicit_base:
            w('base id', base_rev)
        if rev.properties:
            self._write('properties', None, indent=1)
            for name, value in rev.properties.items():
                self._write(name, value, indent=3)
        
        # Add an extra blank space at the end
        self.to_file.write('\n')

    def _write_action(self, name, parameters, properties=None):
        if properties is None:
            properties = []
        p_texts = ['%s:%s' % v for v in properties]
        self.to_file.write('=== ')
        self.to_file.write(' '.join([name]+parameters).encode('utf-8'))
        self.to_file.write(' // '.join(p_texts).encode('utf-8'))
        self.to_file.write('\n')

    def _write_delta(self, new_tree, old_tree, default_revision_id):
        """Write out the changes between the trees."""
        DEVNULL = '/dev/null'
        old_label = ''
        new_label = ''

        def do_diff(old_path, file_id, new_path, kind):
            def tree_lines(tree, require_text=False):
                if file_id in tree:
                    tree_file = tree.get_file(file_id)
                    if require_text is True:
                        tree_file = text_file(tree_file)
                    return tree_file.readlines()
                else:
                    return []

            try:
                old_lines = tree_lines(old_tree, require_text=True)
                new_lines = tree_lines(new_tree, require_text=True)
                self.to_file.write('\n')
                internal_diff(old_path, old_lines, new_path, new_lines, 
                              self.to_file)
            except errors.BinaryFile:
                old_lines = tree_lines(old_tree, require_text=False)
                new_lines = tree_lines(new_tree, require_text=False)
                self.to_file.write(' // encoding:base64\n')
                binary_diff(old_path, old_lines, new_path, new_lines, 
                            self.to_file)

        def do_meta(file_id):
            ie = new_tree.inventory[file_id]
            w(' // executable:%s' % bool_text[ie.executable])

        def do_target(target):
            w(' // target:%s' % target)

        def do_revision(file_id):
            ie = new_tree.inventory[file_id]
            if ie.revision != default_revision_id:
                w(' // last-changed:%s' % ie.revision)

        delta = compare_trees(old_tree, new_tree, want_unchanged=False)

        def w(text):
            self.to_file.write(text.encode('utf-8'))

        for path, file_id, kind in delta.removed:
            self._write_action('removed', [kind, path])

        for path, file_id, kind in delta.added:
            w('=== added %s %s // file-id:%s' % (kind, path, file_id))
            do_revision(file_id)
            if kind == 'file':
                do_meta(file_id)
            if kind == 'symlink':
                do_target(new_tree.inventory[file_id].symlink_target)
            if kind == 'file':
                do_diff(DEVNULL, file_id, path, kind)
            else:
                w('\n')


        for (old_path, new_path, file_id, kind,
             text_modified, meta_modified) in delta.renamed:
            w('=== renamed %s %s // %s' % (kind, old_path, new_path))
            do_revision(file_id)
            if meta_modified:
                do_meta(file_id)
            if text_modified and kind == "symlink":
                do_target(new_tree.inventory[file_id].symlink_target)
            if text_modified and kind == "file":
                do_diff(old_path, file_id, new_path, text_modified)
            else:
                w('\n')

        for (path, file_id, kind,
             text_modified, meta_modified) in delta.modified:
            # TODO: Handle meta_modified
            #prop_str = get_prop_change(meta_modified)
            w('=== modified %s %s' % (kind, path))
            do_revision(file_id)
            if meta_modified:
                do_meta(file_id)
            if text_modified and kind == "symlink":
                do_target(new_tree.inventory[file_id].symlink_target)
            if text_modified and kind == "file":
                do_diff(path, file_id, path, kind)
            else:
                w('\n')
