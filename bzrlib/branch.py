# Copyright (C) 2005 Canonical Ltd

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


import shutil
import sys
import os
import errno
from warnings import warn
from cStringIO import StringIO


import bzrlib
from bzrlib.inventory import InventoryEntry
import bzrlib.inventory as inventory
from bzrlib.trace import mutter, note
from bzrlib.osutils import (isdir, quotefn, compact_date, rand_bytes, 
                            rename, splitpath, sha_file, appendpath, 
                            file_kind, abspath)
import bzrlib.errors as errors
from bzrlib.errors import (BzrError, InvalidRevisionNumber, InvalidRevisionId,
                           NoSuchRevision, HistoryMissing, NotBranchError,
                           DivergedBranches, LockError, UnlistableStore,
                           UnlistableBranch, NoSuchFile, NotVersionedError,
                           NoWorkingTree)
from bzrlib.textui import show_status
from bzrlib.revision import (Revision, is_ancestor, get_intervening_revisions,
                             NULL_REVISION)

from bzrlib.delta import compare_trees
from bzrlib.tree import EmptyTree, RevisionTree
from bzrlib.inventory import Inventory
from bzrlib.store import copy_all
from bzrlib.store.text import TextStore
from bzrlib.store.weave import WeaveStore
from bzrlib.testament import Testament
import bzrlib.transactions as transactions
from bzrlib.transport import Transport, get_transport
import bzrlib.xml5
import bzrlib.ui
from config import TreeConfig


BZR_BRANCH_FORMAT_4 = "Bazaar-NG branch, format 0.0.4\n"
BZR_BRANCH_FORMAT_5 = "Bazaar-NG branch, format 5\n"
BZR_BRANCH_FORMAT_6 = "Bazaar-NG branch, format 6\n"
## TODO: Maybe include checks for common corruption of newlines, etc?


# TODO: Some operations like log might retrieve the same revisions
# repeatedly to calculate deltas.  We could perhaps have a weakref
# cache in memory to make this faster.  In general anything can be
# cached in memory between lock and unlock operations.

def find_branch(*ignored, **ignored_too):
    # XXX: leave this here for about one release, then remove it
    raise NotImplementedError('find_branch() is not supported anymore, '
                              'please use one of the new branch constructors')


def needs_read_lock(unbound):
    """Decorate unbound to take out and release a read lock."""
    def decorated(self, *args, **kwargs):
        self.lock_read()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self.unlock()
    return decorated


def needs_write_lock(unbound):
    """Decorate unbound to take out and release a write lock."""
    def decorated(self, *args, **kwargs):
        self.lock_write()
        try:
            return unbound(self, *args, **kwargs)
        finally:
            self.unlock()
    return decorated

######################################################################
# branch objects

class Branch(object):
    """Branch holding a history of revisions.

    base
        Base directory/url of the branch.
    """
    base = None

    def __init__(self, *ignored, **ignored_too):
        raise NotImplementedError('The Branch class is abstract')

    @staticmethod
    def open_downlevel(base):
        """Open a branch which may be of an old format.
        
        Only local branches are supported."""
        return BzrBranch(get_transport(base), relax_version_check=True)
        
    @staticmethod
    def open(base):
        """Open an existing branch, rooted at 'base' (url)"""
        t = get_transport(base)
        mutter("trying to open %r with transport %r", base, t)
        return BzrBranch(t)

    @staticmethod
    def open_containing(url):
        """Open an existing branch which contains url.
        
        This probes for a branch at url, and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into the root.  If there isn't one, raises NotBranchError.
        If there is one, it is returned, along with the unused portion of url.
        """
        t = get_transport(url)
        while True:
            try:
                return BzrBranch(t), t.relpath(url)
            except NotBranchError:
                pass
            new_t = t.clone('..')
            if new_t.base == t.base:
                # reached the root, whatever that may be
                raise NotBranchError(path=url)
            t = new_t

    @staticmethod
    def initialize(base):
        """Create a new branch, rooted at 'base' (url)"""
        t = get_transport(base)
        return BzrBranch(t, init=True)

    def setup_caching(self, cache_root):
        """Subclasses that care about caching should override this, and set
        up cached stores located under cache_root.
        """
        self.cache_root = cache_root

    def _get_nick(self):
        cfg = self.tree_config()
        return cfg.get_option(u"nickname", default=self.base.split('/')[-1])

    def _set_nick(self, nick):
        cfg = self.tree_config()
        cfg.set_option(nick, "nickname")
        assert cfg.get_option("nickname") == nick

    nick = property(_get_nick, _set_nick)
        
    def push_stores(self, branch_to):
        """Copy the content of this branches store to branch_to."""
        raise NotImplementedError('push_stores is abstract')

    def get_transaction(self):
        """Return the current active transaction.

        If no transaction is active, this returns a passthrough object
        for which all data is immediately flushed and no caching happens.
        """
        raise NotImplementedError('get_transaction is abstract')

    def lock_write(self):
        raise NotImplementedError('lock_write is abstract')
        
    def lock_read(self):
        raise NotImplementedError('lock_read is abstract')

    def unlock(self):
        raise NotImplementedError('unlock is abstract')

    def abspath(self, name):
        """Return absolute filename for something in the branch
        
        XXX: Robert Collins 20051017 what is this used for? why is it a branch
        method and not a tree method.
        """
        raise NotImplementedError('abspath is abstract')

    def controlfilename(self, file_or_path):
        """Return location relative to branch."""
        raise NotImplementedError('controlfilename is abstract')

    def controlfile(self, file_or_path, mode='r'):
        """Open a control file for this branch.

        There are two classes of file in the control directory: text
        and binary.  binary files are untranslated byte streams.  Text
        control files are stored with Unix newlines and in UTF-8, even
        if the platform or locale defaults are different.

        Controlfiles should almost never be opened in write mode but
        rather should be atomically copied and replaced using atomicfile.
        """
        raise NotImplementedError('controlfile is abstract')

    def put_controlfile(self, path, f, encode=True):
        """Write an entry as a controlfile.

        :param path: The path to put the file, relative to the .bzr control
                     directory
        :param f: A file-like or string object whose contents should be copied.
        :param encode:  If true, encode the contents as utf-8
        """
        raise NotImplementedError('put_controlfile is abstract')

    def put_controlfiles(self, files, encode=True):
        """Write several entries as controlfiles.

        :param files: A list of [(path, file)] pairs, where the path is the directory
                      underneath the bzr control directory
        :param encode:  If true, encode the contents as utf-8
        """
        raise NotImplementedError('put_controlfiles is abstract')

    def get_root_id(self):
        """Return the id of this branches root"""
        raise NotImplementedError('get_root_id is abstract')

    def set_root_id(self, file_id):
        raise NotImplementedError('set_root_id is abstract')

    def add(self, files, ids=None):
        """Make files versioned.

        Note that the command line normally calls smart_add instead,
        which can automatically recurse.

        This puts the files in the Added state, so that they will be
        recorded by the next commit.

        files
            List of paths to add, relative to the base of the tree.

        ids
            If set, use these instead of automatically generated ids.
            Must be the same length as the list of files, but may
            contain None for ids that are to be autogenerated.

        TODO: Perhaps have an option to add the ids even if the files do
              not (yet) exist.

        TODO: Perhaps yield the ids and paths as they're added.
        """
        # XXX This should be a WorkingTree method, not a Branch method.
        raise NotImplementedError('add is abstract')

    def print_file(self, file, revno):
        """Print `file` to stdout."""
        raise NotImplementedError('print_file is abstract')

    def unknowns(self):
        """Return all unknown files.

        These are files in the working directory that are not versioned or
        control files or ignored.
        
        >>> from bzrlib.workingtree import WorkingTree
        >>> b = ScratchBranch(files=['foo', 'foo~'])
        >>> map(str, b.unknowns())
        ['foo']
        >>> b.add('foo')
        >>> list(b.unknowns())
        []
        >>> WorkingTree(b.base, b).remove('foo')
        >>> list(b.unknowns())
        [u'foo']
        """
        raise NotImplementedError('unknowns is abstract')

    def append_revision(self, *revision_ids):
        raise NotImplementedError('append_revision is abstract')

    def set_revision_history(self, rev_history):
        raise NotImplementedError('set_revision_history is abstract')

    def has_revision(self, revision_id):
        """True if this branch has a copy of the revision.

        This does not necessarily imply the revision is merge
        or on the mainline."""
        raise NotImplementedError('has_revision is abstract')

    def get_revision_xml(self, revision_id):
        raise NotImplementedError('get_revision_xml is abstract')

    def get_revision(self, revision_id):
        """Return the Revision object for a named revision"""
        raise NotImplementedError('get_revision is abstract')

    def get_revision_delta(self, revno):
        """Return the delta for one revision.

        The delta is relative to its mainline predecessor, or the
        empty tree for revision 1.
        """
        assert isinstance(revno, int)
        rh = self.revision_history()
        if not (1 <= revno <= len(rh)):
            raise InvalidRevisionNumber(revno)

        # revno is 1-based; list is 0-based

        new_tree = self.revision_tree(rh[revno-1])
        if revno == 1:
            old_tree = EmptyTree()
        else:
            old_tree = self.revision_tree(rh[revno-2])

        return compare_trees(old_tree, new_tree)

    def get_revision_sha1(self, revision_id):
        """Hash the stored value of a revision, and return it."""
        raise NotImplementedError('get_revision_sha1 is abstract')

    def get_ancestry(self, revision_id):
        """Return a list of revision-ids integrated by a revision.
        
        This currently returns a list, but the ordering is not guaranteed:
        treat it as a set.
        """
        raise NotImplementedError('get_ancestry is abstract')

    def get_inventory(self, revision_id):
        """Get Inventory object by hash."""
        raise NotImplementedError('get_inventory is abstract')

    def get_inventory_xml(self, revision_id):
        """Get inventory XML as a file object."""
        raise NotImplementedError('get_inventory_xml is abstract')

    def get_inventory_sha1(self, revision_id):
        """Return the sha1 hash of the inventory entry."""
        raise NotImplementedError('get_inventory_sha1 is abstract')

    def get_revision_inventory(self, revision_id):
        """Return inventory of a past revision."""
        raise NotImplementedError('get_revision_inventory is abstract')

    def revision_history(self):
        """Return sequence of revision hashes on to this branch."""
        raise NotImplementedError('revision_history is abstract')

    def revno(self):
        """Return current revision number for this branch.

        That is equivalent to the number of revisions committed to
        this branch.
        """
        return len(self.revision_history())

    def last_revision(self):
        """Return last patch hash, or None if no history."""
        ph = self.revision_history()
        if ph:
            return ph[-1]
        else:
            return None

    def missing_revisions(self, other, stop_revision=None, diverged_ok=False):
        """Return a list of new revisions that would perfectly fit.
        
        If self and other have not diverged, return a list of the revisions
        present in other, but missing from self.

        >>> from bzrlib.commit import commit
        >>> bzrlib.trace.silent = True
        >>> br1 = ScratchBranch()
        >>> br2 = ScratchBranch()
        >>> br1.missing_revisions(br2)
        []
        >>> commit(br2, "lala!", rev_id="REVISION-ID-1")
        >>> br1.missing_revisions(br2)
        [u'REVISION-ID-1']
        >>> br2.missing_revisions(br1)
        []
        >>> commit(br1, "lala!", rev_id="REVISION-ID-1")
        >>> br1.missing_revisions(br2)
        []
        >>> commit(br2, "lala!", rev_id="REVISION-ID-2A")
        >>> br1.missing_revisions(br2)
        [u'REVISION-ID-2A']
        >>> commit(br1, "lala!", rev_id="REVISION-ID-2B")
        >>> br1.missing_revisions(br2)
        Traceback (most recent call last):
        DivergedBranches: These branches have diverged.
        """
        self_history = self.revision_history()
        self_len = len(self_history)
        other_history = other.revision_history()
        other_len = len(other_history)
        common_index = min(self_len, other_len) -1
        if common_index >= 0 and \
            self_history[common_index] != other_history[common_index]:
            raise DivergedBranches(self, other)

        if stop_revision is None:
            stop_revision = other_len
        else:
            assert isinstance(stop_revision, int)
            if stop_revision > other_len:
                raise bzrlib.errors.NoSuchRevision(self, stop_revision)
        return other_history[self_len:stop_revision]
    
    def update_revisions(self, other, stop_revision=None):
        """Pull in new perfect-fit revisions."""
        raise NotImplementedError('update_revisions is abstract')

    def pullable_revisions(self, other, stop_revision):
        raise NotImplementedError('pullable_revisions is abstract')
        
    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        if revision_id is None:
            return 0
        history = self.revision_history()
        try:
            return history.index(revision_id) + 1
        except ValueError:
            raise bzrlib.errors.NoSuchRevision(self, revision_id)

    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
        if revno == 0:
            return None
        if history is None:
            history = self.revision_history()
        elif revno <= 0 or revno > len(history):
            raise bzrlib.errors.NoSuchRevision(self, revno)
        return history[revno - 1]

    def revision_tree(self, revision_id):
        """Return Tree for a revision on this branch.

        `revision_id` may be None for the null revision, in which case
        an `EmptyTree` is returned."""
        raise NotImplementedError('revision_tree is abstract')

    def working_tree(self):
        """Return a `Tree` for the working copy."""
        raise NotImplementedError('working_tree is abstract')

    def pull(self, source, overwrite=False):
        raise NotImplementedError('pull is abstract')

    def basis_tree(self):
        """Return `Tree` object for last revision.

        If there are no revisions yet, return an `EmptyTree`.
        """
        return self.revision_tree(self.last_revision())

    def rename_one(self, from_rel, to_rel):
        """Rename one file.

        This can change the directory or the filename or both.
        """
        raise NotImplementedError('rename_one is abstract')

    def move(self, from_paths, to_name):
        """Rename files.

        to_name must exist as a versioned directory.

        If to_name exists and is a directory, the files are moved into
        it, keeping their old names.  If it is a directory, 

        Note that to_name is only the last component of the new name;
        this doesn't change the directory.

        This returns a list of (from_path, to_path) pairs for each
        entry that is moved.
        """
        raise NotImplementedError('move is abstract')

    def get_parent(self):
        """Return the parent location of the branch.

        This is the default location for push/pull/missing.  The usual
        pattern is that the user can override it by specifying a
        location.
        """
        raise NotImplementedError('get_parent is abstract')

    def get_push_location(self):
        """Return the None or the location to push this branch to."""
        raise NotImplementedError('get_push_location is abstract')

    def set_push_location(self, location):
        """Set a new push location for this branch."""
        raise NotImplementedError('set_push_location is abstract')

    def set_parent(self, url):
        raise NotImplementedError('set_parent is abstract')

    def check_revno(self, revno):
        """\
        Check whether a revno corresponds to any revision.
        Zero (the NULL revision) is considered valid.
        """
        if revno != 0:
            self.check_real_revno(revno)
            
    def check_real_revno(self, revno):
        """\
        Check whether a revno corresponds to a real revision.
        Zero (the NULL revision) is considered invalid
        """
        if revno < 1 or revno > self.revno():
            raise InvalidRevisionNumber(revno)
        
    def sign_revision(self, revision_id, gpg_strategy):
        raise NotImplementedError('sign_revision is abstract')

    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        raise NotImplementedError('store_revision_signature is abstract')

class BzrBranch(Branch):
    """A branch stored in the actual filesystem.

    Note that it's "local" in the context of the filesystem; it doesn't
    really matter if it's on an nfs/smb/afs/coda/... share, as long as
    it's writable, and can be accessed via the normal filesystem API.

    _lock_mode
        None, or 'r' or 'w'

    _lock_count
        If _lock_mode is true, a positive count of the number of times the
        lock has been taken.

    _lock
        Lock object from bzrlib.lock.
    """
    # We actually expect this class to be somewhat short-lived; part of its
    # purpose is to try to isolate what bits of the branch logic are tied to
    # filesystem access, so that in a later step, we can extricate them to
    # a separarte ("storage") class.
    _lock_mode = None
    _lock_count = None
    _lock = None
    _inventory_weave = None
    
    # Map some sort of prefix into a namespace
    # stuff like "revno:10", "revid:", etc.
    # This should match a prefix with a function which accepts
    REVISION_NAMESPACES = {}

    def push_stores(self, branch_to):
        """See Branch.push_stores."""
        if (self._branch_format != branch_to._branch_format
            or self._branch_format != 4):
            from bzrlib.fetch import greedy_fetch
            mutter("falling back to fetch logic to push between %s(%s) and %s(%s)",
                   self, self._branch_format, branch_to, branch_to._branch_format)
            greedy_fetch(to_branch=branch_to, from_branch=self,
                         revision=self.last_revision())
            return

        store_pairs = ((self.text_store,      branch_to.text_store),
                       (self.inventory_store, branch_to.inventory_store),
                       (self.revision_store,  branch_to.revision_store))
        try:
            for from_store, to_store in store_pairs: 
                copy_all(from_store, to_store)
        except UnlistableStore:
            raise UnlistableBranch(from_store)

    def __init__(self, transport, init=False,
                 relax_version_check=False):
        """Create new branch object at a particular location.

        transport -- A Transport object, defining how to access files.
        
        init -- If True, create new control files in a previously
             unversioned directory.  If False, the branch must already
             be versioned.

        relax_version_check -- If true, the usual check for the branch
            version is not applied.  This is intended only for
            upgrade/recovery type use; it's not guaranteed that
            all operations will work on old format branches.

        In the test suite, creation of new trees is tested using the
        `ScratchBranch` class.
        """
        assert isinstance(transport, Transport), \
            "%r is not a Transport" % transport
        self._transport = transport
        if init:
            self._make_control()
        self._check_format(relax_version_check)

        def get_store(name, compressed=True, prefixed=False):
            # FIXME: This approach of assuming stores are all entirely compressed
            # or entirely uncompressed is tidy, but breaks upgrade from 
            # some existing branches where there's a mixture; we probably 
            # still want the option to look for both.
            relpath = self._rel_controlfilename(name)
            store = TextStore(self._transport.clone(relpath),
                              prefixed=prefixed,
                              compressed=compressed)
            #if self._transport.should_cache():
            #    cache_path = os.path.join(self.cache_root, name)
            #    os.mkdir(cache_path)
            #    store = bzrlib.store.CachedStore(store, cache_path)
            return store
        def get_weave(name, prefixed=False):
            relpath = self._rel_controlfilename(name)
            ws = WeaveStore(self._transport.clone(relpath), prefixed=prefixed)
            if self._transport.should_cache():
                ws.enable_cache = True
            return ws

        if self._branch_format == 4:
            self.inventory_store = get_store('inventory-store')
            self.text_store = get_store('text-store')
            self.revision_store = get_store('revision-store')
        elif self._branch_format == 5:
            self.control_weaves = get_weave('')
            self.weave_store = get_weave('weaves')
            self.revision_store = get_store('revision-store', compressed=False)
        elif self._branch_format == 6:
            self.control_weaves = get_weave('')
            self.weave_store = get_weave('weaves', prefixed=True)
            self.revision_store = get_store('revision-store', compressed=False,
                                            prefixed=True)
        self.revision_store.register_suffix('sig')
        self._transaction = None

    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self._transport.base)

    __repr__ = __str__

    def __del__(self):
        if self._lock_mode or self._lock:
            # XXX: This should show something every time, and be suitable for
            # headless operation and embedding
            warn("branch %r was not explicitly unlocked" % self)
            self._lock.unlock()

        # TODO: It might be best to do this somewhere else,
        # but it is nice for a Branch object to automatically
        # cache it's information.
        # Alternatively, we could have the Transport objects cache requests
        # See the earlier discussion about how major objects (like Branch)
        # should never expect their __del__ function to run.
        if hasattr(self, 'cache_root') and self.cache_root is not None:
            try:
                shutil.rmtree(self.cache_root)
            except:
                pass
            self.cache_root = None

    def _get_base(self):
        if self._transport:
            return self._transport.base
        return None

    base = property(_get_base, doc="The URL for the root of this branch.")

    def _finish_transaction(self):
        """Exit the current transaction."""
        if self._transaction is None:
            raise errors.LockError('Branch %s is not in a transaction' %
                                   self)
        transaction = self._transaction
        self._transaction = None
        transaction.finish()

    def get_transaction(self):
        """See Branch.get_transaction."""
        if self._transaction is None:
            return transactions.PassThroughTransaction()
        else:
            return self._transaction

    def _set_transaction(self, new_transaction):
        """Set a new active transaction."""
        if self._transaction is not None:
            raise errors.LockError('Branch %s is in a transaction already.' %
                                   self)
        self._transaction = new_transaction

    def lock_write(self):
        mutter("lock write: %s (%s)", self, self._lock_count)
        # TODO: Upgrade locking to support using a Transport,
        # and potentially a remote locking protocol
        if self._lock_mode:
            if self._lock_mode != 'w':
                raise LockError("can't upgrade to a write lock from %r" %
                                self._lock_mode)
            self._lock_count += 1
        else:
            self._lock = self._transport.lock_write(
                    self._rel_controlfilename('branch-lock'))
            self._lock_mode = 'w'
            self._lock_count = 1
            self._set_transaction(transactions.PassThroughTransaction())

    def lock_read(self):
        mutter("lock read: %s (%s)", self, self._lock_count)
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w'), \
                   "invalid lock mode %r" % self._lock_mode
            self._lock_count += 1
        else:
            self._lock = self._transport.lock_read(
                    self._rel_controlfilename('branch-lock'))
            self._lock_mode = 'r'
            self._lock_count = 1
            self._set_transaction(transactions.ReadOnlyTransaction())
            # 5K may be excessive, but hey, its a knob.
            self.get_transaction().set_cache_size(5000)
                        
    def unlock(self):
        mutter("unlock: %s (%s)", self, self._lock_count)
        if not self._lock_mode:
            raise LockError('branch %r is not locked' % (self))

        if self._lock_count > 1:
            self._lock_count -= 1
        else:
            self._finish_transaction()
            self._lock.unlock()
            self._lock = None
            self._lock_mode = self._lock_count = None

    def abspath(self, name):
        """See Branch.abspath."""
        return self._transport.abspath(name)

    def _rel_controlfilename(self, file_or_path):
        if not isinstance(file_or_path, basestring):
            file_or_path = '/'.join(file_or_path)
        if file_or_path == '':
            return bzrlib.BZRDIR
        return bzrlib.transport.urlescape(bzrlib.BZRDIR + '/' + file_or_path)

    def controlfilename(self, file_or_path):
        """See Branch.controlfilename."""
        return self._transport.abspath(self._rel_controlfilename(file_or_path))

    def controlfile(self, file_or_path, mode='r'):
        """See Branch.controlfile."""
        import codecs

        relpath = self._rel_controlfilename(file_or_path)
        #TODO: codecs.open() buffers linewise, so it was overloaded with
        # a much larger buffer, do we need to do the same for getreader/getwriter?
        if mode == 'rb': 
            return self._transport.get(relpath)
        elif mode == 'wb':
            raise BzrError("Branch.controlfile(mode='wb') is not supported, use put_controlfiles")
        elif mode == 'r':
            # XXX: Do we really want errors='replace'?   Perhaps it should be
            # an error, or at least reported, if there's incorrectly-encoded
            # data inside a file.
            # <https://launchpad.net/products/bzr/+bug/3823>
            return codecs.getreader('utf-8')(self._transport.get(relpath), errors='replace')
        elif mode == 'w':
            raise BzrError("Branch.controlfile(mode='w') is not supported, use put_controlfiles")
        else:
            raise BzrError("invalid controlfile mode %r" % mode)

    def put_controlfile(self, path, f, encode=True):
        """See Branch.put_controlfile."""
        self.put_controlfiles([(path, f)], encode=encode)

    def put_controlfiles(self, files, encode=True):
        """See Branch.put_controlfiles."""
        import codecs
        ctrl_files = []
        for path, f in files:
            if encode:
                if isinstance(f, basestring):
                    f = f.encode('utf-8', 'replace')
                else:
                    f = codecs.getwriter('utf-8')(f, errors='replace')
            path = self._rel_controlfilename(path)
            ctrl_files.append((path, f))
        self._transport.put_multi(ctrl_files)

    def _make_control(self):
        from bzrlib.inventory import Inventory
        from bzrlib.weavefile import write_weave_v5
        from bzrlib.weave import Weave
        
        # Create an empty inventory
        sio = StringIO()
        # if we want per-tree root ids then this is the place to set
        # them; they're not needed for now and so ommitted for
        # simplicity.
        bzrlib.xml5.serializer_v5.write_inventory(Inventory(), sio)
        empty_inv = sio.getvalue()
        sio = StringIO()
        bzrlib.weavefile.write_weave_v5(Weave(), sio)
        empty_weave = sio.getvalue()

        dirs = [[], 'revision-store', 'weaves']
        files = [('README', 
            "This is a Bazaar-NG control directory.\n"
            "Do not change any files in this directory.\n"),
            ('branch-format', BZR_BRANCH_FORMAT_6),
            ('revision-history', ''),
            ('branch-name', ''),
            ('branch-lock', ''),
            ('pending-merges', ''),
            ('inventory', empty_inv),
            ('inventory.weave', empty_weave),
            ('ancestry.weave', empty_weave)
        ]
        cfn = self._rel_controlfilename
        self._transport.mkdir_multi([cfn(d) for d in dirs])
        self.put_controlfiles(files)
        mutter('created control directory in ' + self._transport.base)

    def _check_format(self, relax_version_check):
        """Check this branch format is supported.

        The format level is stored, as an integer, in
        self._branch_format for code that needs to check it later.

        In the future, we might need different in-memory Branch
        classes to support downlevel branches.  But not yet.
        """
        try:
            fmt = self.controlfile('branch-format', 'r').read()
        except NoSuchFile:
            raise NotBranchError(path=self.base)
        mutter("got branch format %r", fmt)
        if fmt == BZR_BRANCH_FORMAT_6:
            self._branch_format = 6
        elif fmt == BZR_BRANCH_FORMAT_5:
            self._branch_format = 5
        elif fmt == BZR_BRANCH_FORMAT_4:
            self._branch_format = 4

        if (not relax_version_check
            and self._branch_format not in (5, 6)):
            raise errors.UnsupportedFormatError(
                           'sorry, branch format %r not supported' % fmt,
                           ['use a different bzr version',
                            'or remove the .bzr directory'
                            ' and "bzr init" again'])

    def get_root_id(self):
        """See Branch.get_root_id."""
        inv = self.get_inventory(self.last_revision())
        return inv.root.file_id

    @needs_write_lock
    def set_root_id(self, file_id):
        """See Branch.set_root_id."""
        inv = self.working_tree().read_working_inventory()
        orig_root_id = inv.root.file_id
        del inv._byid[inv.root.file_id]
        inv.root.file_id = file_id
        inv._byid[inv.root.file_id] = inv.root
        for fid in inv:
            entry = inv[fid]
            if entry.parent_id in (None, orig_root_id):
                entry.parent_id = inv.root.file_id
        self._write_inventory(inv)

    @needs_write_lock
    def add(self, files, ids=None):
        """See Branch.add."""
        # TODO: Re-adding a file that is removed in the working copy
        # should probably put it back with the previous ID.
        if isinstance(files, basestring):
            assert(ids is None or isinstance(ids, basestring))
            files = [files]
            if ids is not None:
                ids = [ids]

        if ids is None:
            ids = [None] * len(files)
        else:
            assert(len(ids) == len(files))

        inv = self.working_tree().read_working_inventory()
        for f,file_id in zip(files, ids):
            if is_control_file(f):
                raise BzrError("cannot add control file %s" % quotefn(f))

            fp = splitpath(f)

            if len(fp) == 0:
                raise BzrError("cannot add top-level %r" % f)

            fullpath = os.path.normpath(self.abspath(f))

            try:
                kind = file_kind(fullpath)
            except OSError:
                # maybe something better?
                raise BzrError('cannot add: not a regular file, symlink or directory: %s' % quotefn(f))

            if not InventoryEntry.versionable_kind(kind):
                raise BzrError('cannot add: not a versionable file ('
                               'i.e. regular file, symlink or directory): %s' % quotefn(f))

            if file_id is None:
                file_id = gen_file_id(f)
            inv.add_path(f, kind=kind, file_id=file_id)

            mutter("add file %s file_id:{%s} kind=%r" % (f, file_id, kind))

        self.working_tree()._write_inventory(inv)

    @needs_read_lock
    def print_file(self, file, revno):
        """See Branch.print_file."""
        tree = self.revision_tree(self.get_rev_id(revno))
        # use inventory as it was in that revision
        file_id = tree.inventory.path2id(file)
        if not file_id:
            raise BzrError("%r is not present in revision %s" % (file, revno))
        tree.print_file(file_id)

    def unknowns(self):
        """See Branch.unknowns."""
        return self.working_tree().unknowns()

    @needs_write_lock
    def append_revision(self, *revision_ids):
        """See Branch.append_revision."""
        for revision_id in revision_ids:
            mutter("add {%s} to revision-history" % revision_id)
        rev_history = self.revision_history()
        rev_history.extend(revision_ids)
        self.set_revision_history(rev_history)

    @needs_write_lock
    def set_revision_history(self, rev_history):
        """See Branch.set_revision_history."""
        self.put_controlfile('revision-history', '\n'.join(rev_history))

    def has_revision(self, revision_id):
        """See Branch.has_revision."""
        return (revision_id is None
                or self.revision_store.has_id(revision_id))

    @needs_read_lock
    def _get_revision_xml_file(self, revision_id):
        if not revision_id or not isinstance(revision_id, basestring):
            raise InvalidRevisionId(revision_id=revision_id, branch=self)
        try:
            return self.revision_store.get(revision_id)
        except (IndexError, KeyError):
            raise bzrlib.errors.NoSuchRevision(self, revision_id)

    def get_revision_xml(self, revision_id):
        """See Branch.get_revision_xml."""
        return self._get_revision_xml_file(revision_id).read()

    def get_revision(self, revision_id):
        """See Branch.get_revision."""
        xml_file = self._get_revision_xml_file(revision_id)

        try:
            r = bzrlib.xml5.serializer_v5.read_revision(xml_file)
        except SyntaxError, e:
            raise bzrlib.errors.BzrError('failed to unpack revision_xml',
                                         [revision_id,
                                          str(e)])
            
        assert r.revision_id == revision_id
        return r

    def get_revision_sha1(self, revision_id):
        """See Branch.get_revision_sha1."""
        # In the future, revision entries will be signed. At that
        # point, it is probably best *not* to include the signature
        # in the revision hash. Because that lets you re-sign
        # the revision, (add signatures/remove signatures) and still
        # have all hash pointers stay consistent.
        # But for now, just hash the contents.
        return bzrlib.osutils.sha_file(self.get_revision_xml_file(revision_id))

    def get_ancestry(self, revision_id):
        """See Branch.get_ancestry."""
        if revision_id is None:
            return [None]
        w = self._get_inventory_weave()
        return [None] + map(w.idx_to_name,
                            w.inclusions([w.lookup(revision_id)]))

    def _get_inventory_weave(self):
        return self.control_weaves.get_weave('inventory',
                                             self.get_transaction())

    def get_inventory(self, revision_id):
        """See Branch.get_inventory."""
        xml = self.get_inventory_xml(revision_id)
        return bzrlib.xml5.serializer_v5.read_inventory_from_string(xml)

    def get_inventory_xml(self, revision_id):
        """See Branch.get_inventory_xml."""
        try:
            assert isinstance(revision_id, basestring), type(revision_id)
            iw = self._get_inventory_weave()
            return iw.get_text(iw.lookup(revision_id))
        except IndexError:
            raise bzrlib.errors.HistoryMissing(self, 'inventory', revision_id)

    def get_inventory_sha1(self, revision_id):
        """See Branch.get_inventory_sha1."""
        return self.get_revision(revision_id).inventory_sha1

    def get_revision_inventory(self, revision_id):
        """See Branch.get_revision_inventory."""
        # TODO: Unify this with get_inventory()
        # bzr 0.0.6 and later imposes the constraint that the inventory_id
        # must be the same as its revision, so this is trivial.
        if revision_id == None:
            # This does not make sense: if there is no revision,
            # then it is the current tree inventory surely ?!
            # and thus get_root_id() is something that looks at the last
            # commit on the branch, and the get_root_id is an inventory check.
            raise NotImplementedError
            # return Inventory(self.get_root_id())
        else:
            return self.get_inventory(revision_id)

    @needs_read_lock
    def revision_history(self):
        """See Branch.revision_history."""
        transaction = self.get_transaction()
        history = transaction.map.find_revision_history()
        if history is not None:
            mutter("cache hit for revision-history in %s", self)
            return list(history)
        history = [l.rstrip('\r\n') for l in
                self.controlfile('revision-history', 'r').readlines()]
        transaction.map.add_revision_history(history)
        # this call is disabled because revision_history is 
        # not really an object yet, and the transaction is for objects.
        # transaction.register_clean(history, precious=True)
        return list(history)

    def update_revisions(self, other, stop_revision=None):
        """See Branch.update_revisions."""
        from bzrlib.fetch import greedy_fetch
        if stop_revision is None:
            stop_revision = other.last_revision()
        ### Should this be checking is_ancestor instead of revision_history?
        if (stop_revision is not None and 
            stop_revision in self.revision_history()):
            return
        greedy_fetch(to_branch=self, from_branch=other,
                     revision=stop_revision)
        pullable_revs = self.pullable_revisions(other, stop_revision)
        if len(pullable_revs) > 0:
            self.append_revision(*pullable_revs)

    def pullable_revisions(self, other, stop_revision):
        """See Branch.pullable_revisions."""
        other_revno = other.revision_id_to_revno(stop_revision)
        try:
            return self.missing_revisions(other, other_revno)
        except DivergedBranches, e:
            try:
                pullable_revs = get_intervening_revisions(self.last_revision(),
                                                          stop_revision, self)
                assert self.last_revision() not in pullable_revs
                return pullable_revs
            except bzrlib.errors.NotAncestor:
                if is_ancestor(self.last_revision(), stop_revision, self):
                    return []
                else:
                    raise e
        
    def revision_tree(self, revision_id):
        """See Branch.revision_tree."""
        # TODO: refactor this to use an existing revision object
        # so we don't need to read it in twice.
        if revision_id == None or revision_id == NULL_REVISION:
            return EmptyTree()
        else:
            inv = self.get_revision_inventory(revision_id)
            return RevisionTree(self.weave_store, inv, revision_id)

    def working_tree(self):
        """See Branch.working_tree."""
        from bzrlib.workingtree import WorkingTree
        # TODO: In the future, perhaps WorkingTree should utilize Transport
        # RobertCollins 20051003 - I don't think it should - working trees are
        # much more complex to keep consistent than our careful .bzr subset.
        # instead, we should say that working trees are local only, and optimise
        # for that.
        if self._transport.base.find('://') != -1:
            raise NoWorkingTree(self.base)
        return WorkingTree(self.base, branch=self)

    @needs_write_lock
    def pull(self, source, overwrite=False):
        """See Branch.pull."""
        source.lock_read()
        try:
            try:
                self.update_revisions(source)
            except DivergedBranches:
                if not overwrite:
                    raise
                self.set_revision_history(source.revision_history())
        finally:
            source.unlock()

    @needs_write_lock
    def rename_one(self, from_rel, to_rel):
        """See Branch.rename_one."""
        tree = self.working_tree()
        inv = tree.inventory
        if not tree.has_filename(from_rel):
            raise BzrError("can't rename: old working file %r does not exist" % from_rel)
        if tree.has_filename(to_rel):
            raise BzrError("can't rename: new working file %r already exists" % to_rel)

        file_id = inv.path2id(from_rel)
        if file_id == None:
            raise BzrError("can't rename: old name %r is not versioned" % from_rel)

        if inv.path2id(to_rel):
            raise BzrError("can't rename: new name %r is already versioned" % to_rel)

        to_dir, to_tail = os.path.split(to_rel)
        to_dir_id = inv.path2id(to_dir)
        if to_dir_id == None and to_dir != '':
            raise BzrError("can't determine destination directory id for %r" % to_dir)

        mutter("rename_one:")
        mutter("  file_id    {%s}" % file_id)
        mutter("  from_rel   %r" % from_rel)
        mutter("  to_rel     %r" % to_rel)
        mutter("  to_dir     %r" % to_dir)
        mutter("  to_dir_id  {%s}" % to_dir_id)

        inv.rename(file_id, to_dir_id, to_tail)

        from_abs = self.abspath(from_rel)
        to_abs = self.abspath(to_rel)
        try:
            rename(from_abs, to_abs)
        except OSError, e:
            raise BzrError("failed to rename %r to %r: %s"
                    % (from_abs, to_abs, e[1]),
                    ["rename rolled back"])

        self.working_tree()._write_inventory(inv)

    @needs_write_lock
    def move(self, from_paths, to_name):
        """See Branch.move."""
        result = []
        ## TODO: Option to move IDs only
        assert not isinstance(from_paths, basestring)
        tree = self.working_tree()
        inv = tree.inventory
        to_abs = self.abspath(to_name)
        if not isdir(to_abs):
            raise BzrError("destination %r is not a directory" % to_abs)
        if not tree.has_filename(to_name):
            raise BzrError("destination %r not in working directory" % to_abs)
        to_dir_id = inv.path2id(to_name)
        if to_dir_id == None and to_name != '':
            raise BzrError("destination %r is not a versioned directory" % to_name)
        to_dir_ie = inv[to_dir_id]
        if to_dir_ie.kind not in ('directory', 'root_directory'):
            raise BzrError("destination %r is not a directory" % to_abs)

        to_idpath = inv.get_idpath(to_dir_id)

        for f in from_paths:
            if not tree.has_filename(f):
                raise BzrError("%r does not exist in working tree" % f)
            f_id = inv.path2id(f)
            if f_id == None:
                raise BzrError("%r is not versioned" % f)
            name_tail = splitpath(f)[-1]
            dest_path = appendpath(to_name, name_tail)
            if tree.has_filename(dest_path):
                raise BzrError("destination %r already exists" % dest_path)
            if f_id in to_idpath:
                raise BzrError("can't move %r to a subdirectory of itself" % f)

        # OK, so there's a race here, it's possible that someone will
        # create a file in this interval and then the rename might be
        # left half-done.  But we should have caught most problems.

        for f in from_paths:
            name_tail = splitpath(f)[-1]
            dest_path = appendpath(to_name, name_tail)
            result.append((f, dest_path))
            inv.rename(inv.path2id(f), to_dir_id, name_tail)
            try:
                rename(self.abspath(f), self.abspath(dest_path))
            except OSError, e:
                raise BzrError("failed to rename %r to %r: %s" % (f, dest_path, e[1]),
                        ["rename rolled back"])

        self.working_tree()._write_inventory(inv)
        return result

    def get_parent(self):
        """See Branch.get_parent."""
        import errno
        _locs = ['parent', 'pull', 'x-pull']
        for l in _locs:
            try:
                return self.controlfile(l, 'r').read().strip('\n')
            except IOError, e:
                if e.errno != errno.ENOENT:
                    raise
        return None

    def get_push_location(self):
        """See Branch.get_push_location."""
        config = bzrlib.config.BranchConfig(self)
        push_loc = config.get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        config = bzrlib.config.LocationConfig(self.base)
        config.set_user_option('push_location', location)

    @needs_write_lock
    def set_parent(self, url):
        """See Branch.set_parent."""
        # TODO: Maybe delete old location files?
        from bzrlib.atomicfile import AtomicFile
        f = AtomicFile(self.controlfilename('parent'))
        try:
            f.write(url + '\n')
            f.commit()
        finally:
            f.close()

    def tree_config(self):
        return TreeConfig(self)

    def sign_revision(self, revision_id, gpg_strategy):
        """See Branch.sign_revision."""
        plaintext = Testament.from_revision(self, revision_id).as_short_text()
        self.store_revision_signature(gpg_strategy, plaintext, revision_id)

    @needs_write_lock
    def store_revision_signature(self, gpg_strategy, plaintext, revision_id):
        """See Branch.store_revision_signature."""
        self.revision_store.add(StringIO(gpg_strategy.sign(plaintext)), 
                                revision_id, "sig")


class ScratchBranch(BzrBranch):
    """Special test class: a branch that cleans up after itself.

    >>> b = ScratchBranch()
    >>> isdir(b.base)
    True
    >>> bd = b.base
    >>> b._transport.__del__()
    >>> isdir(bd)
    False
    """

    def __init__(self, files=[], dirs=[], transport=None):
        """Make a test branch.

        This creates a temporary directory and runs init-tree in it.

        If any files are listed, they are created in the working copy.
        """
        if transport is None:
            transport = bzrlib.transport.local.ScratchTransport()
            super(ScratchBranch, self).__init__(transport, init=True)
        else:
            super(ScratchBranch, self).__init__(transport)

        for d in dirs:
            self._transport.mkdir(d)
            
        for f in files:
            self._transport.put(f, 'content of %s' % f)


    def clone(self):
        """
        >>> orig = ScratchBranch(files=["file1", "file2"])
        >>> clone = orig.clone()
        >>> if os.name != 'nt':
        ...   os.path.samefile(orig.base, clone.base)
        ... else:
        ...   orig.base == clone.base
        ...
        False
        >>> os.path.isfile(os.path.join(clone.base, "file1"))
        True
        """
        from shutil import copytree
        from tempfile import mkdtemp
        base = mkdtemp()
        os.rmdir(base)
        copytree(self.base, base, symlinks=True)
        return ScratchBranch(
            transport=bzrlib.transport.local.ScratchTransport(base))
    

######################################################################
# predicates


def is_control_file(filename):
    ## FIXME: better check
    filename = os.path.normpath(filename)
    while filename != '':
        head, tail = os.path.split(filename)
        ## mutter('check %r for control file' % ((head, tail), ))
        if tail == bzrlib.BZRDIR:
            return True
        if filename == head:
            break
        filename = head
    return False



def gen_file_id(name):
    """Return new file id.

    This should probably generate proper UUIDs, but for the moment we
    cope with just randomness because running uuidgen every time is
    slow."""
    import re
    from binascii import hexlify
    from time import time

    # get last component
    idx = name.rfind('/')
    if idx != -1:
        name = name[idx+1 : ]
    idx = name.rfind('\\')
    if idx != -1:
        name = name[idx+1 : ]

    # make it not a hidden file
    name = name.lstrip('.')

    # remove any wierd characters; we don't escape them but rather
    # just pull them out
    name = re.sub(r'[^\w.]', '', name)

    s = hexlify(rand_bytes(8))
    return '-'.join((name, compact_date(time()), s))


def gen_root_id():
    """Return a new tree-root file id."""
    return gen_file_id('TREE_ROOT')


