# (C) 2005 Canonical

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

"""Exceptions for bzr, and reporting of them.

Exceptions are caught at a high level to report errors to the user, and
might also be caught inside the program.  Therefore it needs to be
possible to convert them to a meaningful string, and also for them to be
interrogated by the program.

Exceptions are defined such that the arguments given to the constructor
are stored in the object as properties of the same name.  When the
object is printed as a string, the doc string of the class is used as
a format string with the property dictionary available to it.

This means that exceptions can used like this:

>>> import sys
>>> try:
...   raise NotBranchError(path='/foo/bar')
... except:
...   print sys.exc_type
...   print sys.exc_value
...   path = getattr(sys.exc_value, 'path')
...   if path is not None:
...     print path
bzrlib.errors.NotBranchError
Not a branch: /foo/bar
/foo/bar

Therefore:

 * create a new exception class for any class of error that can be
   usefully distinguished.

 * the printable form of an exception is generated by the base class
   __str__ method

Exception strings should start with a capital letter and not have a final
fullstop.
"""

# based on Scott James Remnant's hct error classes

# TODO: is there any value in providing the .args field used by standard
# python exceptions?   A list of values with no names seems less useful 
# to me.

# TODO: Perhaps convert the exception to a string at the moment it's 
# constructed to make sure it will succeed.  But that says nothing about
# exceptions that are never raised.

# TODO: Convert all the other error classes here to BzrNewError, and eliminate
# the old one.


class BzrError(StandardError):
    def __str__(self):
        # XXX: Should we show the exception class in 
        # exceptions that don't provide their own message?  
        # maybe it should be done at a higher level
        ## n = self.__class__.__name__ + ': '
        n = ''
        if len(self.args) == 1:
            return str(self.args[0])
        elif len(self.args) == 2:
            # further explanation or suggestions
            try:
                return n + '\n  '.join([self.args[0]] + self.args[1])
            except TypeError:
                return n + "%r" % self
        else:
            return n + `self.args`


class BzrNewError(BzrError):
    """bzr error"""
    # base classes should override the docstring with their human-
    # readable explanation

    def __init__(self, **kwds):
        for key, value in kwds.items():
            setattr(self, key, value)

    def __str__(self):
        try:
            return self.__doc__ % self.__dict__
        except (NameError, ValueError, KeyError), e:
            return 'Unprintable exception %s: %s' \
                % (self.__class__.__name__, str(e))


class BzrCheckError(BzrNewError):
    """Internal check failed: %(message)s"""
    def __init__(self, message):
        BzrNewError.__init__(self)
        self.message = message


class InvalidEntryName(BzrNewError):
    """Invalid entry name: %(name)s"""
    def __init__(self, name):
        BzrNewError.__init__(self)
        self.name = name


class InvalidRevisionNumber(BzrNewError):
    """Invalid revision number %(revno)d"""
    def __init__(self, revno):
        BzrNewError.__init__(self)
        self.revno = revno


class InvalidRevisionId(BzrNewError):
    """Invalid revision-id {%(revision_id)s} in %(branch)s"""
    def __init__(self, revision_id, branch):
        BzrNewError.__init__(self)
        self.revision_id = revision_id
        self.branch = branch


class NoWorkingTree(BzrNewError):
    """No WorkingTree exists for %s(base)."""
    
    def __init__(self, base):
        BzrNewError.__init__(self)
        self.base = base


class BzrCommandError(BzrError):
    # Error from malformed user command
    # This is being misused as a generic exception
    # pleae subclass. RBC 20051030
    #
    # I think it's a waste of effort to differentiate between errors that
    # are not intended to be caught anyway.  UI code need not subclass
    # BzrCommandError, and non-UI code should not throw a subclass of
    # BzrCommandError.  ADHB 20051211
    def __str__(self):
        return self.args[0]


class BzrOptionError(BzrCommandError):
    """Some missing or otherwise incorrect option was supplied."""

    
class StrictCommitFailed(Exception):
    """Commit refused because there are unknowns in the tree."""


class PathError(BzrNewError):
    """Generic path error: %(path)r%(extra)s)"""
    def __init__(self, path, extra=None):
        BzrNewError.__init__(self)
        self.path = path
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class NoSuchFile(PathError):
    """No such file: %(path)r%(extra)s"""


class FileExists(PathError):
    """File exists: %(path)r%(extra)s"""


class PermissionDenied(PathError):
    """Permission denied: %(path)r%(extra)s"""


class PathNotChild(BzrNewError):
    """Path %(path)r is not a child of path %(base)r%(extra)s"""
    def __init__(self, path, base, extra=None):
        BzrNewError.__init__(self)
        self.path = path
        self.base = base
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class NotBranchError(BzrNewError):
    """Not a branch: %(path)s"""
    def __init__(self, path):
        BzrNewError.__init__(self)
        self.path = path


class FileInWrongBranch(BzrNewError):
    """File %(path)s in not in branch %(branch_base)s."""
    def __init__(self, branch, path):
        BzrNewError.__init__(self)
        self.branch = branch
        self.branch_base = branch.base
        self.path = path


class UnsupportedFormatError(BzrError):
    """Specified path is a bzr branch that we recognize but cannot read."""
    def __str__(self):
        return 'unsupported branch format: %s' % self.args[0]


class UnknownFormatError(BzrError):
    """Specified path is a bzr branch whose format we do not recognize."""
    def __str__(self):
        return 'unknown branch format: %s' % self.args[0]


class NotVersionedError(BzrNewError):
    """%(path)s is not versioned"""
    def __init__(self, path):
        BzrNewError.__init__(self)
        self.path = path


class BadFileKindError(BzrError):
    """Specified file is of a kind that cannot be added.

    (For example a symlink or device file.)"""


class ForbiddenFileError(BzrError):
    """Cannot operate on a file because it is a control file."""


class LockError(Exception):
    """Lock error"""
    # All exceptions from the lock/unlock functions should be from
    # this exception class.  They will be translated as necessary. The
    # original exception is available as e.original_error


class CommitNotPossible(LockError):
    """A commit was attempted but we do not have a write lock open."""


class AlreadyCommitted(LockError):
    """A rollback was requested, but is not able to be accomplished."""


class ReadOnlyError(LockError):
    """A write attempt was made in a read only transaction."""


class PointlessCommit(BzrNewError):
    """No changes to commit"""


class UpgradeReadonly(BzrNewError):
    """Upgrade URL cannot work with readonly URL's."""


class StrictCommitFailed(Exception):
    """Commit refused because there are unknowns in the tree."""


class NoSuchRevision(BzrError):
    def __init__(self, branch, revision):
        self.branch = branch
        self.revision = revision
        msg = "Branch %s has no revision %s" % (branch, revision)
        BzrError.__init__(self, msg)


class HistoryMissing(BzrError):
    def __init__(self, branch, object_type, object_id):
        self.branch = branch
        BzrError.__init__(self,
                          '%s is missing %s {%s}'
                          % (branch, object_type, object_id))


class DivergedBranches(BzrError):
    def __init__(self, branch1, branch2):
        BzrError.__init__(self, "These branches have diverged.  Try merge.")
        self.branch1 = branch1
        self.branch2 = branch2


class UnrelatedBranches(BzrCommandError):
    def __init__(self):
        msg = "Branches have no common ancestor, and no base revision"\
            " specified."
        BzrCommandError.__init__(self, msg)

class NoCommonAncestor(BzrError):
    def __init__(self, revision_a, revision_b):
        msg = "Revisions have no common ancestor: %s %s." \
            % (revision_a, revision_b) 
        BzrError.__init__(self, msg)

class NoCommonRoot(BzrError):
    def __init__(self, revision_a, revision_b):
        msg = "Revisions are not derived from the same root: %s %s." \
            % (revision_a, revision_b) 
        BzrError.__init__(self, msg)

class NotAncestor(BzrError):
    def __init__(self, rev_id, not_ancestor_id):
        msg = "Revision %s is not an ancestor of %s" % (not_ancestor_id, 
                                                        rev_id)
        BzrError.__init__(self, msg)
        self.rev_id = rev_id
        self.not_ancestor_id = not_ancestor_id


class InstallFailed(BzrError):
    def __init__(self, revisions):
        msg = "Could not install revisions:\n%s" % " ,".join(revisions)
        BzrError.__init__(self, msg)
        self.revisions = revisions


class AmbiguousBase(BzrError):
    def __init__(self, bases):
        msg = "The correct base is unclear, becase %s are all equally close" %\
            ", ".join(bases)
        BzrError.__init__(self, msg)
        self.bases = bases

class NoCommits(BzrError):
    def __init__(self, branch):
        msg = "Branch %s has no commits." % branch
        BzrError.__init__(self, msg)

class UnlistableStore(BzrError):
    def __init__(self, store):
        BzrError.__init__(self, "Store %s is not listable" % store)

class UnlistableBranch(BzrError):
    def __init__(self, br):
        BzrError.__init__(self, "Stores for branch %s are not listable" % br)


class WeaveError(BzrNewError):
    """Error in processing weave: %(message)s"""
    def __init__(self, message=None):
        BzrNewError.__init__(self)
        self.message = message


class WeaveRevisionAlreadyPresent(WeaveError):
    """Revision {%(revision_id)s} already present in %(weave)s"""
    def __init__(self, revision_id, weave):
        WeaveError.__init__(self)
        self.revision_id = revision_id
        self.weave = weave


class WeaveRevisionNotPresent(WeaveError):
    """Revision {%(revision_id)s} not present in %(weave)s"""
    def __init__(self, revision_id, weave):
        WeaveError.__init__(self)
        self.revision_id = revision_id
        self.weave = weave


class WeaveFormatError(WeaveError):
    """Weave invariant violated: %(what)s"""
    def __init__(self, what):
        WeaveError.__init__(self)
        self.what = what


class WeaveParentMismatch(WeaveError):
    """Parents are mismatched between two revisions."""
    

class WeaveInvalidChecksum(WeaveError):
    """Text did not match it's checksum: %(message)s"""


class WeaveTextDiffers(WeaveError):
    """Weaves differ on text content. Revision: {%(revision_id)s}, %(weave_a)s, %(weave_b)s"""

    def __init__(self, revision_id, weave_a, weave_b):
        WeaveError.__init__(self)
        self.revision_id = revision_id
        self.weave_a = weave_a
        self.weave_b = weave_b


class NoSuchExportFormat(BzrNewError):
    """Export format %(format)r not supported"""
    def __init__(self, format):
        BzrNewError.__init__(self)
        self.format = format


class TransportError(BzrError):
    """All errors thrown by Transport implementations should derive
    from this class.
    """
    def __init__(self, msg=None, orig_error=None):
        if msg is None and orig_error is not None:
            msg = str(orig_error)
        BzrError.__init__(self, msg)
        self.msg = msg
        self.orig_error = orig_error

# A set of semi-meaningful errors which can be thrown
class TransportNotPossible(TransportError):
    """This is for transports where a specific function is explicitly not
    possible. Such as pushing files to an HTTP server.
    """
    pass


class ConnectionError(TransportError):
    """A connection problem prevents file retrieval.
    This does not indicate whether the file exists or not; it indicates that a
    precondition for requesting the file was not met.
    """
    def __init__(self, msg=None, orig_error=None):
        TransportError.__init__(self, msg=msg, orig_error=orig_error)


class ConnectionReset(TransportError):
    """The connection has been closed."""
    pass

class ConflictsInTree(BzrError):
    def __init__(self):
        BzrError.__init__(self, "Working tree has conflicts.")

class ParseConfigError(BzrError):
    def __init__(self, errors, filename):
        if filename is None:
            filename = ""
        message = "Error(s) parsing config file %s:\n%s" % \
            (filename, ('\n'.join(e.message for e in errors)))
        BzrError.__init__(self, message)

class SigningFailed(BzrError):
    def __init__(self, command_line):
        BzrError.__init__(self, "Failed to gpg sign data with command '%s'"
                               % command_line)

class WorkingTreeNotRevision(BzrError):
    def __init__(self, tree):
        BzrError.__init__(self, "The working tree for %s has changed since"
                          " last commit, but weave merge requires that it be"
                          " unchanged." % tree.basedir)

class CantReprocessAndShowBase(BzrNewError):
    """Can't reprocess and show base.
Reprocessing obscures relationship of conflicting lines to base."""

class GraphCycleError(BzrNewError):
    """Cycle in graph %(graph)r"""
    def __init__(self, graph):
        BzrNewError.__init__(self)
        self.graph = graph


class NotConflicted(BzrNewError):
    """File %(filename)s is not conflicted."""

    def __init__(self, filename):
        BzrNewError.__init__(self)
        self.filename = filename


class MustUseDecorated(Exception):
    """A decorating function has requested its original command be used.
    
    This should never escape bzr, so does not need to be printable.
    """


class MissingText(BzrNewError):
    """Branch %(base)s is missing revision %(text_revision)s of %(file_id)s"""

    def __init__(self, branch, text_revision, file_id):
        BzrNewError.__init__(self)
        self.branch = branch
        self.base = branch.base
        self.text_revision = text_revision
        self.file_id = file_id


class BzrBadParameter(BzrNewError):
    """A bad parameter : %(param)s is not usable.
    
    This exception should never be thrown, but it is a base class for all
    parameter-to-function errors.
    """
    def __init__(self, param):
        BzrNewError.__init__(self)
        self.param = param


class BzrBadParameterNotUnicode(BzrBadParameter):
    """Parameter %(param)s is neither unicode nor utf8."""


class BzrBadParameterNotString(BzrBadParameter):
    """Parameter %(param)s is not a string or unicode string."""


class DependencyNotPresent(BzrNewError):
    """Unable to import library: %(library)s, %(error)s"""

    def __init__(self, library, error):
        BzrNewError.__init__(self, library=library, error=error)


class ParamikoNotPresent(DependencyNotPresent):
    """Unable to import paramiko (required for sftp support): %(error)s"""

    def __init__(self, error):
        DependencyNotPresent.__init__(self, 'paramiko', error)


class UninitializableFormat(BzrNewError):
    """Format %(format)s cannot be initialised by this version of bzr."""

    def __init__(self, format):
        BzrNewError.__init__(self)
        self.format = format
