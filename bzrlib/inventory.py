#! /usr/bin/env python
# -*- coding: UTF-8 -*-

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

"""Inventories map files to their name in a revision."""


__copyright__ = "Copyright (C) 2005 Canonical Ltd."
__author__ = "Martin Pool <mbp@canonical.com>"

import sys, os.path, types
from sets import Set

try:
    from cElementTree import Element, ElementTree, SubElement
except ImportError:
    from elementtree import Element, ElementTree, SubElement

from xml import XMLMixin
from errors import bailout
from osutils import uuid, quotefn, splitpath, joinpath, appendpath
from trace import mutter

class InventoryEntry(XMLMixin):
    """Description of a versioned file.

    An InventoryEntry has the following fields, which are also
    present in the XML inventory-entry element:

    * *file_id*
    * *name*: (only the basename within the directory, must not
      contain slashes)
    * *kind*: "directory" or "file"
    * *directory_id*: (if absent/null means the branch root directory)
    * *text_sha1*: only for files
    * *text_size*: in bytes, only for files 
    * *text_id*: identifier for the text version, only for files

    InventoryEntries can also exist inside a WorkingTree
    inventory, in which case they are not yet bound to a
    particular revision of the file.  In that case the text_sha1,
    text_size and text_id are absent.


    >>> i = Inventory()
    >>> i.path2id('')
    >>> i.add(InventoryEntry('123', 'src', kind='directory'))
    >>> i.add(InventoryEntry('2323', 'hello.c', parent_id='123'))
    >>> for j in i.iter_entries():
    ...   print j
    ... 
    ('src', InventoryEntry('123', 'src', kind='directory', parent_id=None))
    ('src/hello.c', InventoryEntry('2323', 'hello.c', kind='file', parent_id='123'))
    >>> i.add(InventoryEntry('2323', 'bye.c', parent_id='123'))
    Traceback (most recent call last):
    ...
    BzrError: ('inventory already contains entry with id {2323}', [])
    >>> i.add(InventoryEntry('2324', 'bye.c', parent_id='123'))
    >>> i.add(InventoryEntry('2325', 'wibble', parent_id='123', kind='directory'))
    >>> i.path2id('src/wibble')
    '2325'
    >>> '2325' in i
    True
    >>> i.add(InventoryEntry('2326', 'wibble.c', parent_id='2325'))
    >>> i['2326']
    InventoryEntry('2326', 'wibble.c', kind='file', parent_id='2325')
    >>> for j in i.iter_entries():
    ...     print j[0]
    ...     assert i.path2id(j[0])
    ... 
    src
    src/bye.c
    src/hello.c
    src/wibble
    src/wibble/wibble.c
    >>> i.id2path('2326')
    'src/wibble/wibble.c'

    :todo: Maybe also keep the full path of the entry, and the children?
           But those depend on its position within a particular inventory, and
           it would be nice not to need to hold the backpointer here.
    """
    def __init__(self, file_id, name, kind='file', text_id=None,
                 parent_id=None):
        """Create an InventoryEntry
        
        The filename must be a single component, relative to the
        parent directory; it cannot be a whole path or relative name.

        >>> e = InventoryEntry('123', 'hello.c')
        >>> e.name
        'hello.c'
        >>> e.file_id
        '123'
        >>> e = InventoryEntry('123', 'src/hello.c')
        Traceback (most recent call last):
        BzrError: ("InventoryEntry name is not a simple filename: 'src/hello.c'", [])
        """
        
        if len(splitpath(name)) != 1:
            bailout('InventoryEntry name is not a simple filename: %r'
                    % name)
        
        self.file_id = file_id
        self.name = name
        assert kind in ['file', 'directory']
        self.kind = kind
        self.text_id = text_id
        self.parent_id = parent_id
        self.text_sha1 = None
        self.text_size = None


    def copy(self):
        other = InventoryEntry(self.file_id, self.name, self.kind,
                               self.text_id, self.parent_id)
        other.text_sha1 = self.text_sha1
        other.text_size = self.text_size
        return other


    def __repr__(self):
        return ("%s(%r, %r, kind=%r, parent_id=%r)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.kind,
                   self.parent_id))

    
    def to_element(self):
        """Convert to XML element"""
        e = Element('entry')

        e.set('name', self.name)
        e.set('file_id', self.file_id)
        e.set('kind', self.kind)

        if self.text_size is not None:
            e.set('text_size', '%d' % self.text_size)
            
        for f in ['text_id', 'text_sha1', 'parent_id']:
            v = getattr(self, f)
            if v is not None:
                e.set(f, v)

        e.tail = '\n'
            
        return e


    def from_element(cls, elt):
        assert elt.tag == 'entry'
        self = cls(elt.get('file_id'), elt.get('name'), elt.get('kind'))
        self.text_id = elt.get('text_id')
        self.text_sha1 = elt.get('text_sha1')
        self.parent_id = elt.get('parent_id')
        
        ## mutter("read inventoryentry: %r" % (elt.attrib))

        v = elt.get('text_size')
        self.text_size = v and int(v)

        return self
            

    from_element = classmethod(from_element)

    def __cmp__(self, other):
        if self is other:
            return 0
        if not isinstance(other, InventoryEntry):
            return NotImplemented

        return cmp(self.file_id, other.file_id) \
               or cmp(self.name, other.name) \
               or cmp(self.text_sha1, other.text_sha1) \
               or cmp(self.text_size, other.text_size) \
               or cmp(self.text_id, other.text_id) \
               or cmp(self.parent_id, other.parent_id) \
               or cmp(self.kind, other.kind)



class Inventory(XMLMixin):
    """Inventory of versioned files in a tree.

    An Inventory acts like a set of InventoryEntry items.  You can
    also look files up by their file_id or name.
    
    May be read from and written to a metadata file in a tree.  To
    manipulate the inventory (for example to add a file), it is read
    in, modified, and then written back out.

    The inventory represents a typical unix file tree, with
    directories containing files and subdirectories.  We never store
    the full path to a file, because renaming a directory implicitly
    moves all of its contents.  This class internally maintains a
    lookup tree that allows the children under a directory to be
    returned quickly.

    InventoryEntry objects must not be modified after they are
    inserted.

    >>> inv = Inventory()
    >>> inv.write_xml(sys.stdout)
    <inventory>
    </inventory>
    >>> inv.add(InventoryEntry('123-123', 'hello.c'))
    >>> inv['123-123'].name
    'hello.c'
    >>> for file_id in inv: print file_id
    ...
    123-123

    May be treated as an iterator or set to look up file ids:
    
    >>> bool(inv.path2id('hello.c'))
    True
    >>> '123-123' in inv
    True

    May also look up by name:

    >>> [x[0] for x in inv.iter_entries()]
    ['hello.c']
    
    >>> inv.write_xml(sys.stdout)
    <inventory>
    <entry file_id="123-123" kind="file" name="hello.c" />
    </inventory>

    """

    ## TODO: Clear up handling of files in subdirectories; we probably
    ## do want to be able to just look them up by name but this
    ## probably means gradually walking down the path, looking up as we go.

    ## TODO: Make sure only canonical filenames are stored.

    ## TODO: Do something sensible about the possible collisions on
    ## case-losing filesystems.  Perhaps we should just always forbid
    ## such collisions.

    ## _tree should probably just be stored as
    ## InventoryEntry._children on each directory.

    def __init__(self):
        """Create or read an inventory.

        If a working directory is specified, the inventory is read
        from there.  If the file is specified, read from that. If not,
        the inventory is created empty.
        """
        self._byid = dict()

        # _tree is indexed by parent_id; at each level a map from name
        # to ie.  The None entry is the root.
        self._tree = {None: {}}


    def __iter__(self):
        return iter(self._byid)


    def __len__(self):
        """Returns number of entries."""
        return len(self._byid)


    def iter_entries(self, parent_id=None):
        """Return (path, entry) pairs, in order by name."""
        kids = self._tree[parent_id].items()
        kids.sort()
        for name, ie in kids:
            yield name, ie
            if ie.kind == 'directory':
                for cn, cie in self.iter_entries(parent_id=ie.file_id):
                    yield joinpath([name, cn]), cie


    def directories(self, include_root=True):
        """Return (path, entry) pairs for all directories.
        """
        if include_root:
            yield '', None
        for path, entry in self.iter_entries():
            if entry.kind == 'directory':
                yield path, entry
        


    def children(self, parent_id):
        """Return entries that are direct children of parent_id."""
        return self._tree[parent_id]
                    


    # TODO: return all paths and entries


    def __contains__(self, file_id):
        """True if this entry contains a file with given id.

        >>> inv = Inventory()
        >>> inv.add(InventoryEntry('123', 'foo.c'))
        >>> '123' in inv
        True
        >>> '456' in inv
        False
        """
        return file_id in self._byid


    def __getitem__(self, file_id):
        """Return the entry for given file_id.

        >>> inv = Inventory()
        >>> inv.add(InventoryEntry('123123', 'hello.c'))
        >>> inv['123123'].name
        'hello.c'
        """
        return self._byid[file_id]


    def add(self, entry):
        """Add entry to inventory.

        To add  a file to a branch ready to be committed, use Branch.add,
        which calls this."""
        if entry.file_id in self:
            bailout("inventory already contains entry with id {%s}" % entry.file_id)

        if entry.parent_id != None:
            if entry.parent_id not in self:
                bailout("parent_id %s of new entry not found in inventory"
                        % entry.parent_id)
            
        if self._tree[entry.parent_id].has_key(entry.name):
            bailout("%s is already versioned"
                    % appendpath(self.id2path(entry.parent_id), entry.name))

        self._byid[entry.file_id] = entry
        self._tree[entry.parent_id][entry.name] = entry

        if entry.kind == 'directory':
            self._tree[entry.file_id] = {}


    def __delitem__(self, file_id):
        """Remove entry by id.

        >>> inv = Inventory()
        >>> inv.add(InventoryEntry('123', 'foo.c'))
        >>> '123' in inv
        True
        >>> del inv['123']
        >>> '123' in inv
        False
        """
        ie = self[file_id]

        assert self._tree[ie.parent_id][ie.name] == ie
        
        # TODO: Test deleting all children; maybe hoist to a separate
        # deltree method?
        if ie.kind == 'directory':
            for cie in self._tree[file_id].values():
                del self[cie.file_id]
            del self._tree[file_id]

        del self._byid[file_id]
        del self._tree[ie.parent_id][ie.name]


    def id_set(self):
        return Set(self._byid)


    def to_element(self):
        """Convert to XML Element"""
        e = Element('inventory')
        e.text = '\n'
        for path, ie in self.iter_entries():
            e.append(ie.to_element())
        return e
    

    def from_element(cls, elt):
        """Construct from XML Element

        >>> inv = Inventory()
        >>> inv.add(InventoryEntry('foo.c-123981239', 'foo.c'))
        >>> elt = inv.to_element()
        >>> inv2 = Inventory.from_element(elt)
        >>> inv2 == inv
        True
        """
        assert elt.tag == 'inventory'
        o = cls()
        for e in elt:
            o.add(InventoryEntry.from_element(e))
        return o
        
    from_element = classmethod(from_element)


    def __cmp__(self, other):
        """Compare two sets by comparing their contents.

        >>> i1 = Inventory()
        >>> i2 = Inventory()
        >>> i1 == i2
        True
        >>> i1.add(InventoryEntry('123', 'foo'))
        >>> i1 == i2
        False
        >>> i2.add(InventoryEntry('123', 'foo'))
        >>> i1 == i2
        True
        """
        if self is other:
            return 0
        
        if not isinstance(other, Inventory):
            return NotImplemented

        if self.id_set() ^ other.id_set():
            return 1

        for file_id in self._byid:
            c = cmp(self[file_id], other[file_id])
            if c: return c

        return 0


    def id2path(self, file_id):
        """Return as a list the path to file_id."""
        p = []
        while file_id != None:
            ie = self[file_id]
            p = [ie.name] + p
            file_id = ie.parent_id
        return joinpath(p)
            


    def path2id(self, name):
        """Walk down through directories to return entry of last component.

        names may be either a list of path components, or a single
        string, in which case it is automatically split.

        This returns the entry of the last component in the path,
        which may be either a file or a directory.
        """
        assert isinstance(name, types.StringTypes)

        parent_id = None
        for f in splitpath(name):
            try:
                cie = self._tree[parent_id][f]
                assert cie.name == f
                parent_id = cie.file_id
            except KeyError:
                # or raise an error?
                return None

        return parent_id


    def get_child(self, parent_id, child_name):
        return self._tree[parent_id].get(child_name)


    def has_filename(self, names):
        return bool(self.path2id(names))


    def has_id(self, file_id):
        assert isinstance(file_id, str)
        return self._byid.has_key(file_id)



if __name__ == '__main__':
    import doctest, inventory
    doctest.testmod(inventory)
