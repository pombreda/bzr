# Copyright (C) 2006 Canonical Ltd
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

"""Server-side bzrdir related request implmentations."""


from bzrlib import branch, errors, repository
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
    )


class SmartServerRequestOpenBzrDir(SmartServerRequest):

    def do(self, path):
        from bzrlib.bzrdir import BzrDirFormat
        try:
            t = self.transport_from_client_path(path)
        except errors.PathNotChild:
            # The client is trying to ask about a path that they have no access
            # to.
            # Ideally we'd return a FailedSmartServerResponse here rather than
            # a "successful" negative, but we want to be compatibile with
            # clients that don't anticipate errors from this method.
            answer = 'no'
        else:
            default_format = BzrDirFormat.get_default_format()
            real_bzrdir = default_format.open(t, _found=True)
            try:
                real_bzrdir._format.probe_transport(t)
            except (errors.NotBranchError, errors.UnknownFormatError):
                answer = 'no'
            else:
                answer = 'yes'
        return SuccessfulSmartServerResponse((answer,))


class SmartServerRequestBzrDir(SmartServerRequest):

    def _boolean_to_yes_no(self, a_boolean):
        if a_boolean:
            return 'yes'
        else:
            return 'no'

    def _format_to_capabilities(self, repo_format):
        rich_root = self._boolean_to_yes_no(repo_format.rich_root_data)
        tree_ref = self._boolean_to_yes_no(
            repo_format.supports_tree_reference)
        external_lookup = self._boolean_to_yes_no(
            repo_format.supports_external_lookups)
        return rich_root, tree_ref, external_lookup

    def _repo_relpath(self, current_transport, repository):
        """Get the relative path for repository from current_transport."""
        # the relpath of the bzrdir in the found repository gives us the
        # path segments to pop-out.
        relpath = repository.bzrdir.root_transport.relpath(
            current_transport.base)
        if len(relpath):
            segments = ['..'] * len(relpath.split('/'))
        else:
            segments = []
        return '/'.join(segments)


class SmartServerRequestCreateBranch(SmartServerRequestBzrDir):

    def do(self, path, network_name):
        """Create a branch in the bzr dir at path.

        This operates precisely like 'bzrdir.create_branch'.

        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions (and
        this method should only be called after establishing that a bzr dir
        exists anyway).

        This is the initial version of this method introduced to the smart
        server for 1.13.

        :param path: The path to the bzrdir.
        :param network_name: The network name of the branch type to create.
        :return: (ok, network_name)
        """
        bzrdir = BzrDir.open_from_transport(
            self.transport_from_client_path(path))
        format = branch.network_format_registry.get(network_name)
        bzrdir.branch_format = format
        result = format.initialize(bzrdir)
        rich_root, tree_ref, external_lookup = self._format_to_capabilities(
            result.repository._format)
        branch_format = result._format.network_name()
        repo_format = result.repository._format.network_name()
        repo_path = self._repo_relpath(bzrdir.root_transport,
            result.repository)
        # branch format, repo relpath, rich_root, tree_ref, external_lookup,
        # repo_network_name
        return SuccessfulSmartServerResponse(('ok', branch_format, repo_path,
            rich_root, tree_ref, external_lookup, repo_format))


class SmartServerRequestCreateRepository(SmartServerRequestBzrDir):

    def do(self, path, network_name, shared):
        """Create a repository in the bzr dir at path.
        
        This operates precisely like 'bzrdir.create_repository'.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions (and
        this method should only be called after establishing that a bzr dir
        exists anyway).

        This is the initial version of this method introduced to the smart
        server for 1.13.

        :param path: The path to the bzrdir.
        :param network_name: The network name of the repository type to create.
        :param shared: The value to pass create_repository for the shared
            parameter.
        :return: (ok, rich_root, tree_ref, external_lookup, network_name)
        """
        bzrdir = BzrDir.open_from_transport(
            self.transport_from_client_path(path))
        shared = shared == 'True'
        format = repository.network_format_registry.get(network_name)
        bzrdir.repository_format = format
        result = format.initialize(bzrdir, shared=shared)
        rich_root, tree_ref, external_lookup = self._format_to_capabilities(
            result._format)
        return SuccessfulSmartServerResponse(('ok', rich_root, tree_ref,
            external_lookup, result._format.network_name()))


class SmartServerRequestFindRepository(SmartServerRequestBzrDir):

    def _find(self, path):
        """try to find a repository from path upwards
        
        This operates precisely like 'bzrdir.find_repository'.
        
        :return: (relpath, rich_root, tree_ref, external_lookup) flags. All are
            strings, relpath is a / prefixed path, and the other three are
            either 'yes' or 'no'.
        :raises errors.NoRepositoryPresent: When there is no repository
            present.
        """
        bzrdir = BzrDir.open_from_transport(
            self.transport_from_client_path(path))
        repository = bzrdir.find_repository()
        path = self._repo_relpath(bzrdir.root_transport, repository)
        rich_root, tree_ref, external_lookup = self._format_to_capabilities(
            repository._format)
        return path, rich_root, tree_ref, external_lookup


class SmartServerRequestFindRepositoryV1(SmartServerRequestFindRepository):

    def do(self, path):
        """try to find a repository from path upwards
        
        This operates precisely like 'bzrdir.find_repository'.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.

        This is the initial version of this method introduced with the smart
        server. Modern clients will try the V2 method that adds support for the
        supports_external_lookups attribute.

        :return: norepository or ok, relpath.
        """
        try:
            path, rich_root, tree_ref, external_lookup = self._find(path)
            return SuccessfulSmartServerResponse(('ok', path, rich_root, tree_ref))
        except errors.NoRepositoryPresent:
            return FailedSmartServerResponse(('norepository', ))


class SmartServerRequestFindRepositoryV2(SmartServerRequestFindRepository):

    def do(self, path):
        """try to find a repository from path upwards
        
        This operates precisely like 'bzrdir.find_repository'.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.

        This is the second edition of this method introduced in bzr 1.3, which
        returns information about the supports_external_lookups format
        attribute too.

        :return: norepository or ok, relpath.
        """
        try:
            path, rich_root, tree_ref, external_lookup = self._find(path)
            return SuccessfulSmartServerResponse(
                ('ok', path, rich_root, tree_ref, external_lookup))
        except errors.NoRepositoryPresent:
            return FailedSmartServerResponse(('norepository', ))


class SmartServerRequestInitializeBzrDir(SmartServerRequest):

    def do(self, path):
        """Initialize a bzrdir at path.

        The default format of the server is used.
        :return: SmartServerResponse(('ok', ))
        """
        target_transport = self.transport_from_client_path(path)
        BzrDirFormat.get_default_format().initialize_on_transport(target_transport)
        return SuccessfulSmartServerResponse(('ok', ))


class SmartServerRequestOpenBranch(SmartServerRequest):

    def do(self, path):
        """try to open a branch at path and return ok/nobranch.
        
        If a bzrdir is not present, an exception is propogated
        rather than 'no branch' because these are different conditions.
        """
        bzrdir = BzrDir.open_from_transport(
            self.transport_from_client_path(path))
        try:
            reference_url = bzrdir.get_branch_reference()
            if reference_url is None:
                return SuccessfulSmartServerResponse(('ok', ''))
            else:
                return SuccessfulSmartServerResponse(('ok', reference_url))
        except errors.NotBranchError:
            return FailedSmartServerResponse(('nobranch', ))
