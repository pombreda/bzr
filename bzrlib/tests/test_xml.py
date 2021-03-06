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

from cStringIO import StringIO

from bzrlib import (
    errors,
    fifo_cache,
    inventory,
    xml6,
    xml7,
    xml8,
    )
from bzrlib.tests import TestCase
from bzrlib.inventory import Inventory
import bzrlib.xml5

_revision_v5 = """<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.212"
    timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92"/>
</parents>
</revision>
"""

_revision_v5_utc = """\
<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9"
    timestamp="1125907235.212"
    timezone="0">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92"/>
</parents>
</revision>
"""

_committed_inv_v5 = """<inventory>
<file file_id="bar-20050901064931-73b4b1138abc9cd2"
      name="bar" parent_id="TREE_ROOT"
      revision="mbp@foo-123123"
      text_sha1="A" text_size="1"/>
<directory name="subdir"
           file_id="foo-20050801201819-4139aa4a272f4250"
           parent_id="TREE_ROOT"
           revision="mbp@foo-00"/>
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134"
      name="bar" parent_id="foo-20050801201819-4139aa4a272f4250"
      revision="mbp@foo-00"
      text_sha1="B" text_size="0"/>
</inventory>
"""

_basis_inv_v5 = """<inventory revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92">
<file file_id="bar-20050901064931-73b4b1138abc9cd2"
      name="bar" parent_id="TREE_ROOT"
      revision="mbp@foo-123123"/>
<directory name="subdir"
           file_id="foo-20050801201819-4139aa4a272f4250"
           parent_id="TREE_ROOT"
           revision="mbp@foo-00"/>
<file file_id="bar-20050824000535-6bc48cfad47ed134"
      name="bar" parent_id="foo-20050801201819-4139aa4a272f4250"
      revision="mbp@foo-00"/>
</inventory>
"""


# DO NOT REFLOW THIS. Its the exact revision we want.
_expected_rev_v5 = """<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;" format="5" inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41" revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9" timestamp="1125907235.212" timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92" />
</parents>
</revision>
"""


# DO NOT REFLOW THIS. Its the exact inventory we want.
_expected_inv_v5 = """<inventory format="5">
<file file_id="bar-20050901064931-73b4b1138abc9cd2" name="bar" revision="mbp@foo-123123" text_sha1="A" text_size="1" />
<directory file_id="foo-20050801201819-4139aa4a272f4250" name="subdir" revision="mbp@foo-00" />
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" revision="mbp@foo-00" text_sha1="B" text_size="0" />
</inventory>
"""


_expected_inv_v5_root = """<inventory file_id="f&lt;" format="5" revision_id="mother!">
<file file_id="bar-20050901064931-73b4b1138abc9cd2" name="bar" parent_id="f&lt;" revision="mbp@foo-123123" text_sha1="A" text_size="1" />
<directory file_id="foo-20050801201819-4139aa4a272f4250" name="subdir" parent_id="f&lt;" revision="mbp@foo-00" />
<file executable="yes" file_id="bar-20050824000535-6bc48cfad47ed134" name="bar" parent_id="foo-20050801201819-4139aa4a272f4250" revision="mbp@foo-00" text_sha1="B" text_size="0" />
<symlink file_id="link-1" name="link" parent_id="foo-20050801201819-4139aa4a272f4250" revision="mbp@foo-00" symlink_target="a" />
</inventory>
"""

_expected_inv_v6 = """<inventory format="6" revision_id="rev_outer">
<directory file_id="tree-root-321" name="" revision="rev_outer" />
<directory file_id="dir-id" name="dir" parent_id="tree-root-321" revision="rev_outer" />
<file file_id="file-id" name="file" parent_id="tree-root-321" revision="rev_outer" text_sha1="A" text_size="1" />
<symlink file_id="link-id" name="link" parent_id="tree-root-321" revision="rev_outer" symlink_target="a" />
</inventory>
"""

_expected_inv_v7 = """<inventory format="7" revision_id="rev_outer">
<directory file_id="tree-root-321" name="" revision="rev_outer" />
<directory file_id="dir-id" name="dir" parent_id="tree-root-321" revision="rev_outer" />
<file file_id="file-id" name="file" parent_id="tree-root-321" revision="rev_outer" text_sha1="A" text_size="1" />
<symlink file_id="link-id" name="link" parent_id="tree-root-321" revision="rev_outer" symlink_target="a" />
<tree-reference file_id="nested-id" name="nested" parent_id="tree-root-321" revision="rev_outer" reference_revision="rev_inner" />
</inventory>
"""

_expected_rev_v8 = """<revision committer="Martin Pool &lt;mbp@sourcefrog.net&gt;" format="8" inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41" revision_id="mbp@sourcefrog.net-20050905080035-e0439293f8b6b9f9" timestamp="1125907235.212" timezone="36000">
<message>- start splitting code for xml (de)serialization away from objects
  preparatory to supporting multiple formats by a single library
</message>
<parents>
<revision_ref revision_id="mbp@sourcefrog.net-20050905063503-43948f59fa127d92" />
</parents>
</revision>
"""

_expected_inv_v8 = """<inventory format="8" revision_id="rev_outer">
<directory file_id="tree-root-321" name="" revision="rev_outer" />
<directory file_id="dir-id" name="dir" parent_id="tree-root-321" revision="rev_outer" />
<file file_id="file-id" name="file" parent_id="tree-root-321" revision="rev_outer" text_sha1="A" text_size="1" />
<symlink file_id="link-id" name="link" parent_id="tree-root-321" revision="rev_outer" symlink_target="a" />
</inventory>
"""

_revision_utf8_v5 = """<revision committer="Erik B&#229;gfors &lt;erik@foo.net&gt;"
    inventory_sha1="e79c31c1deb64c163cf660fdedd476dd579ffd41"
    revision_id="erik@b&#229;gfors-02"
    timestamp="1125907235.212"
    timezone="36000">
<message>Include &#181;nicode characters
</message>
<parents>
<revision_ref revision_id="erik@b&#229;gfors-01"/>
</parents>
</revision>
"""

_inventory_utf8_v5 = """<inventory file_id="TRE&#233;_ROOT" format="5"
                                   revision_id="erik@b&#229;gfors-02">
<file file_id="b&#229;r-01"
      name="b&#229;r" parent_id="TRE&#233;_ROOT"
      revision="erik@b&#229;gfors-01"/>
<directory name="s&#181;bdir"
           file_id="s&#181;bdir-01"
           parent_id="TRE&#233;_ROOT"
           revision="erik@b&#229;gfors-01"/>
<file executable="yes" file_id="b&#229;r-02"
      name="b&#229;r" parent_id="s&#181;bdir-01"
      revision="erik@b&#229;gfors-02"/>
</inventory>
"""

# Before revision_id was always stored as an attribute
_inventory_v5a = """<inventory format="5">
</inventory>
"""

# Before revision_id was always stored as an attribute
_inventory_v5b = """<inventory format="5" revision_id="a-rev-id">
</inventory>
"""


class TestSerializer(TestCase):
    """Test XML serialization"""

    def test_unpack_revision_5(self):
        """Test unpacking a canned revision v5"""
        inp = StringIO(_revision_v5)
        rev = bzrlib.xml5.serializer_v5.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer,
           "Martin Pool <mbp@sourcefrog.net>")
        eq(len(rev.parent_ids), 1)
        eq(rev.timezone, 36000)
        eq(rev.parent_ids[0],
           "mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_revision_5_utc(self):
        inp = StringIO(_revision_v5_utc)
        rev = bzrlib.xml5.serializer_v5.read_revision(inp)
        eq = self.assertEqual
        eq(rev.committer,
           "Martin Pool <mbp@sourcefrog.net>")
        eq(len(rev.parent_ids), 1)
        eq(rev.timezone, 0)
        eq(rev.parent_ids[0],
           "mbp@sourcefrog.net-20050905063503-43948f59fa127d92")

    def test_unpack_inventory_5(self):
        """Unpack canned new-style inventory"""
        inp = StringIO(_committed_inv_v5)
        inv = bzrlib.xml5.serializer_v5.read_inventory(inp)
        eq = self.assertEqual
        eq(len(inv), 4)
        ie = inv['bar-20050824000535-6bc48cfad47ed134']
        eq(ie.kind, 'file')
        eq(ie.revision, 'mbp@foo-00')
        eq(ie.name, 'bar')
        eq(inv[ie.parent_id].kind, 'directory')

    def test_unpack_basis_inventory_5(self):
        """Unpack canned new-style inventory"""
        inp = StringIO(_basis_inv_v5)
        inv = bzrlib.xml5.serializer_v5.read_inventory(inp)
        eq = self.assertEqual
        eq(len(inv), 4)
        eq(inv.revision_id, 'mbp@sourcefrog.net-20050905063503-43948f59fa127d92')
        ie = inv['bar-20050824000535-6bc48cfad47ed134']
        eq(ie.kind, 'file')
        eq(ie.revision, 'mbp@foo-00')
        eq(ie.name, 'bar')
        eq(inv[ie.parent_id].kind, 'directory')

    def test_unpack_inventory_5a(self):
        inv = bzrlib.xml5.serializer_v5.read_inventory_from_string(
                _inventory_v5a, revision_id='test-rev-id')
        self.assertEqual('test-rev-id', inv.root.revision)

    def test_unpack_inventory_5a_cache_and_copy(self):
        # Passing an entry_cache should get populated with the objects
        # But the returned objects should be copies if return_from_cache is
        # False
        entry_cache = fifo_cache.FIFOCache()
        inv = bzrlib.xml5.serializer_v5.read_inventory_from_string(
            _inventory_v5a, revision_id='test-rev-id',
            entry_cache=entry_cache, return_from_cache=False)
        for entry in inv.iter_just_entries():
            key = (entry.file_id, entry.revision)
            if entry.file_id is inv.root.file_id:
                # The root id is inferred for xml v5
                self.assertFalse(key in entry_cache)
            else:
                self.assertIsNot(entry, entry_cache[key])

    def test_unpack_inventory_5a_cache_no_copy(self):
        # Passing an entry_cache should get populated with the objects
        # The returned objects should be exact if return_from_cache is
        # True
        entry_cache = fifo_cache.FIFOCache()
        inv = bzrlib.xml5.serializer_v5.read_inventory_from_string(
            _inventory_v5a, revision_id='test-rev-id',
            entry_cache=entry_cache, return_from_cache=True)
        for entry in inv.iter_just_entries():
            key = (entry.file_id, entry.revision)
            if entry.file_id is inv.root.file_id:
                # The root id is inferred for xml v5
                self.assertFalse(key in entry_cache)
            else:
                self.assertIs(entry, entry_cache[key])

    def test_unpack_inventory_5b(self):
        inv = bzrlib.xml5.serializer_v5.read_inventory_from_string(
                _inventory_v5b, revision_id='test-rev-id')
        self.assertEqual('a-rev-id', inv.root.revision)

    def test_repack_inventory_5(self):
        inp = StringIO(_committed_inv_v5)
        inv = bzrlib.xml5.serializer_v5.read_inventory(inp)
        outp = StringIO()
        bzrlib.xml5.serializer_v5.write_inventory(inv, outp)
        self.assertEqualDiff(_expected_inv_v5, outp.getvalue())
        inv2 = bzrlib.xml5.serializer_v5.read_inventory(StringIO(outp.getvalue()))
        self.assertEqual(inv, inv2)

    def assertRoundTrips(self, xml_string):
        inp = StringIO(xml_string)
        inv = bzrlib.xml5.serializer_v5.read_inventory(inp)
        outp = StringIO()
        bzrlib.xml5.serializer_v5.write_inventory(inv, outp)
        self.assertEqualDiff(xml_string, outp.getvalue())
        lines = bzrlib.xml5.serializer_v5.write_inventory_to_lines(inv)
        outp.seek(0)
        self.assertEqual(outp.readlines(), lines)
        inv2 = bzrlib.xml5.serializer_v5.read_inventory(StringIO(outp.getvalue()))
        self.assertEqual(inv, inv2)

    def tests_serialize_inventory_v5_with_root(self):
        self.assertRoundTrips(_expected_inv_v5_root)

    def check_repack_revision(self, txt):
        """Check that repacking a revision yields the same information"""
        inp = StringIO(txt)
        rev = bzrlib.xml5.serializer_v5.read_revision(inp)
        outp = StringIO()
        bzrlib.xml5.serializer_v5.write_revision(rev, outp)
        outfile_contents = outp.getvalue()
        rev2 = bzrlib.xml5.serializer_v5.read_revision(StringIO(outfile_contents))
        self.assertEqual(rev, rev2)

    def test_repack_revision_5(self):
        """Round-trip revision to XML v5"""
        self.check_repack_revision(_revision_v5)

    def test_repack_revision_5_utc(self):
        self.check_repack_revision(_revision_v5_utc)

    def test_pack_revision_5(self):
        """Pack revision to XML v5"""
        # fixed 20051025, revisions should have final newline
        rev = bzrlib.xml5.serializer_v5.read_revision_from_string(_revision_v5)
        outp = StringIO()
        bzrlib.xml5.serializer_v5.write_revision(rev, outp)
        outfile_contents = outp.getvalue()
        self.assertEqual(outfile_contents[-1], '\n')
        self.assertEqualDiff(outfile_contents, bzrlib.xml5.serializer_v5.write_revision_to_string(rev))
        self.assertEqualDiff(outfile_contents, _expected_rev_v5)

    def test_empty_property_value(self):
        """Create an empty property value check that it serializes correctly"""
        s_v5 = bzrlib.xml5.serializer_v5
        rev = s_v5.read_revision_from_string(_revision_v5)
        outp = StringIO()
        props = {'empty':'', 'one':'one'}
        rev.properties = props
        txt = s_v5.write_revision_to_string(rev)
        new_rev = s_v5.read_revision_from_string(txt)
        self.assertEqual(props, new_rev.properties)

    def get_sample_inventory(self):
        inv = Inventory('tree-root-321', revision_id='rev_outer')
        inv.add(inventory.InventoryFile('file-id', 'file', 'tree-root-321'))
        inv.add(inventory.InventoryDirectory('dir-id', 'dir',
                                             'tree-root-321'))
        inv.add(inventory.InventoryLink('link-id', 'link', 'tree-root-321'))
        inv['tree-root-321'].revision = 'rev_outer'
        inv['dir-id'].revision = 'rev_outer'
        inv['file-id'].revision = 'rev_outer'
        inv['file-id'].text_sha1 = 'A'
        inv['file-id'].text_size = 1
        inv['link-id'].revision = 'rev_outer'
        inv['link-id'].symlink_target = 'a'
        return inv

    def test_roundtrip_inventory_v7(self):
        inv = self.get_sample_inventory()
        inv.add(inventory.TreeReference('nested-id', 'nested', 'tree-root-321',
                                        'rev_outer', 'rev_inner'))
        txt = xml7.serializer_v7.write_inventory_to_string(inv)
        lines = xml7.serializer_v7.write_inventory_to_lines(inv)
        self.assertEqual(bzrlib.osutils.split_lines(txt), lines)
        self.assertEqualDiff(_expected_inv_v7, txt)
        inv2 = xml7.serializer_v7.read_inventory_from_string(txt)
        self.assertEqual(5, len(inv2))
        for path, ie in inv.iter_entries():
            self.assertEqual(ie, inv2[ie.file_id])

    def test_roundtrip_inventory_v6(self):
        inv = self.get_sample_inventory()
        txt = xml6.serializer_v6.write_inventory_to_string(inv)
        lines = xml6.serializer_v6.write_inventory_to_lines(inv)
        self.assertEqual(bzrlib.osutils.split_lines(txt), lines)
        self.assertEqualDiff(_expected_inv_v6, txt)
        inv2 = xml6.serializer_v6.read_inventory_from_string(txt)
        self.assertEqual(4, len(inv2))
        for path, ie in inv.iter_entries():
            self.assertEqual(ie, inv2[ie.file_id])

    def test_wrong_format_v7(self):
        """Can't accidentally open a file with wrong serializer"""
        s_v6 = bzrlib.xml6.serializer_v6
        s_v7 = xml7.serializer_v7
        self.assertRaises(errors.UnexpectedInventoryFormat,
                          s_v7.read_inventory_from_string, _expected_inv_v5)
        self.assertRaises(errors.UnexpectedInventoryFormat,
                          s_v6.read_inventory_from_string, _expected_inv_v7)

    def test_tree_reference(self):
        s_v5 = bzrlib.xml5.serializer_v5
        s_v6 = bzrlib.xml6.serializer_v6
        s_v7 = xml7.serializer_v7
        inv = Inventory('tree-root-321', revision_id='rev-outer')
        inv.root.revision = 'root-rev'
        inv.add(inventory.TreeReference('nested-id', 'nested', 'tree-root-321',
                                        'rev-outer', 'rev-inner'))
        self.assertRaises(errors.UnsupportedInventoryKind,
                          s_v5.write_inventory_to_string, inv)
        self.assertRaises(errors.UnsupportedInventoryKind,
                          s_v6.write_inventory_to_string, inv)
        txt = s_v7.write_inventory_to_string(inv)
        lines = s_v7.write_inventory_to_lines(inv)
        self.assertEqual(bzrlib.osutils.split_lines(txt), lines)
        inv2 = s_v7.read_inventory_from_string(txt)
        self.assertEqual('tree-root-321', inv2['nested-id'].parent_id)
        self.assertEqual('rev-outer', inv2['nested-id'].revision)
        self.assertEqual('rev-inner', inv2['nested-id'].reference_revision)

    def test_roundtrip_inventory_v8(self):
        inv = self.get_sample_inventory()
        txt = xml8.serializer_v8.write_inventory_to_string(inv)
        inv2 = xml8.serializer_v8.read_inventory_from_string(txt)
        self.assertEqual(4, len(inv2))
        for path, ie in inv.iter_entries():
            self.assertEqual(ie, inv2[ie.file_id])

    def test_inventory_text_v8(self):
        inv = self.get_sample_inventory()
        txt = xml8.serializer_v8.write_inventory_to_string(inv)
        lines = xml8.serializer_v8.write_inventory_to_lines(inv)
        self.assertEqual(bzrlib.osutils.split_lines(txt), lines)
        self.assertEqualDiff(_expected_inv_v8, txt)

    def test_revision_text_v6(self):
        """Pack revision to XML v6"""
        rev = bzrlib.xml6.serializer_v6.read_revision_from_string(
            _expected_rev_v5)
        serialized = bzrlib.xml6.serializer_v6.write_revision_to_string(rev)
        self.assertEqualDiff(serialized, _expected_rev_v5)

    def test_revision_text_v7(self):
        """Pack revision to XML v7"""
        rev = bzrlib.xml7.serializer_v7.read_revision_from_string(
            _expected_rev_v5)
        serialized = bzrlib.xml7.serializer_v7.write_revision_to_string(rev)
        self.assertEqualDiff(serialized, _expected_rev_v5)

    def test_revision_text_v8(self):
        """Pack revision to XML v8"""
        rev = bzrlib.xml8.serializer_v8.read_revision_from_string(
            _expected_rev_v8)
        serialized = bzrlib.xml8.serializer_v8.write_revision_to_string(rev)
        self.assertEqualDiff(serialized, _expected_rev_v8)

    def test_revision_ids_are_utf8(self):
        """Parsed revision_ids should all be utf-8 strings, not unicode."""
        s_v5 = bzrlib.xml5.serializer_v5
        rev = s_v5.read_revision_from_string(_revision_utf8_v5)
        self.assertEqual('erik@b\xc3\xa5gfors-02', rev.revision_id)
        self.assertIsInstance(rev.revision_id, str)
        self.assertEqual(['erik@b\xc3\xa5gfors-01'], rev.parent_ids)
        for parent_id in rev.parent_ids:
            self.assertIsInstance(parent_id, str)
        self.assertEqual(u'Include \xb5nicode characters\n', rev.message)
        self.assertIsInstance(rev.message, unicode)

        # ie.revision should either be None or a utf-8 revision id
        inv = s_v5.read_inventory_from_string(_inventory_utf8_v5)
        rev_id_1 = u'erik@b\xe5gfors-01'.encode('utf8')
        rev_id_2 = u'erik@b\xe5gfors-02'.encode('utf8')
        fid_root = u'TRE\xe9_ROOT'.encode('utf8')
        fid_bar1 = u'b\xe5r-01'.encode('utf8')
        fid_sub = u's\xb5bdir-01'.encode('utf8')
        fid_bar2 = u'b\xe5r-02'.encode('utf8')
        expected = [(u'', fid_root, None, rev_id_2),
                    (u'b\xe5r', fid_bar1, fid_root, rev_id_1),
                    (u's\xb5bdir', fid_sub, fid_root, rev_id_1),
                    (u's\xb5bdir/b\xe5r', fid_bar2, fid_sub, rev_id_2),
                   ]
        self.assertEqual(rev_id_2, inv.revision_id)
        self.assertIsInstance(inv.revision_id, str)

        actual = list(inv.iter_entries_by_dir())
        for ((exp_path, exp_file_id, exp_parent_id, exp_rev_id),
             (act_path, act_ie)) in zip(expected, actual):
            self.assertEqual(exp_path, act_path)
            self.assertIsInstance(act_path, unicode)
            self.assertEqual(exp_file_id, act_ie.file_id)
            self.assertIsInstance(act_ie.file_id, str)
            self.assertEqual(exp_parent_id, act_ie.parent_id)
            if exp_parent_id is not None:
                self.assertIsInstance(act_ie.parent_id, str)
            self.assertEqual(exp_rev_id, act_ie.revision)
            if exp_rev_id is not None:
                self.assertIsInstance(act_ie.revision, str)

        self.assertEqual(len(expected), len(actual))


class TestEncodeAndEscape(TestCase):
    """Whitebox testing of the _encode_and_escape function."""

    def setUp(self):
        super(TestEncodeAndEscape, self).setUp()
        # Keep the cache clear before and after the test
        bzrlib.xml_serializer._clear_cache()
        self.addCleanup(bzrlib.xml_serializer._clear_cache)

    def test_simple_ascii(self):
        # _encode_and_escape always appends a final ", because these parameters
        # are being used in xml attributes, and by returning it now, we have to
        # do fewer string operations later.
        val = bzrlib.xml_serializer.encode_and_escape('foo bar')
        self.assertEqual('foo bar"', val)
        # The second time should be cached
        val2 = bzrlib.xml_serializer.encode_and_escape('foo bar')
        self.assertIs(val2, val)

    def test_ascii_with_xml(self):
        self.assertEqual('&amp;&apos;&quot;&lt;&gt;"',
                         bzrlib.xml_serializer.encode_and_escape('&\'"<>'))

    def test_utf8_with_xml(self):
        # u'\xb5\xe5&\u062c'
        utf8_str = '\xc2\xb5\xc3\xa5&\xd8\xac'
        self.assertEqual('&#181;&#229;&amp;&#1580;"',
                         bzrlib.xml_serializer.encode_and_escape(utf8_str))

    def test_unicode(self):
        uni_str = u'\xb5\xe5&\u062c'
        self.assertEqual('&#181;&#229;&amp;&#1580;"',
                         bzrlib.xml_serializer.encode_and_escape(uni_str))


class TestMisc(TestCase):

    def test_unescape_xml(self):
        """We get some kind of error when malformed entities are passed"""
        self.assertRaises(KeyError, bzrlib.xml8._unescape_xml, 'foo&bar;')
