# Copyright (C) 2005 Canonical Ltd
# -*- coding: utf-8 -*-
# vim: encoding=utf-8
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

import os
from cStringIO import StringIO

from bzrlib.tests import BzrTestBase, TestCaseWithTransport
from bzrlib.log import (show_log, 
                        get_view_revisions, 
                        LogFormatter, 
                        LongLogFormatter, 
                        ShortLogFormatter, 
                        LineLogFormatter)
from bzrlib.branch import Branch
from bzrlib.errors import InvalidRevisionNumber


class _LogEntry(object):
    # should probably move into bzrlib.log?
    pass


class LogCatcher(LogFormatter):
    """Pull log messages into list rather than displaying them.

    For ease of testing we save log messages here rather than actually
    formatting them, so that we can precisely check the result without
    being too dependent on the exact formatting.

    We should also test the LogFormatter.
    """
    def __init__(self):
        super(LogCatcher, self).__init__(to_file=None)
        self.logs = []

    def show(self, revno, rev, delta):
        le = _LogEntry()
        le.revno = revno
        le.rev = rev
        le.delta = delta
        self.logs.append(le)


class SimpleLogTest(TestCaseWithTransport):

    def checkDelta(self, delta, **kw):
        """Check the filenames touched by a delta are as expected."""
        for n in 'added', 'removed', 'renamed', 'modified', 'unchanged':
            expected = kw.get(n, [])

            # tests are written with unix paths; fix them up for windows
            #if os.sep != '/':
            #    expected = [x.replace('/', os.sep) for x in expected]

            # strip out only the path components
            got = [x[0] for x in getattr(delta, n)]
            self.assertEquals(expected, got)

    def test_cur_revno(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        lf = LogCatcher()
        wt.commit('empty commit')
        show_log(b, lf, verbose=True, start_revision=1, end_revision=1)
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=2, end_revision=1) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=2) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=0, end_revision=2) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=0) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=-1, end_revision=1) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=-1) 

    def test_cur_revno(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        lf = LogCatcher()
        wt.commit('empty commit')
        show_log(b, lf, verbose=True, start_revision=1, end_revision=1)
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=2, end_revision=1) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=2) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=0, end_revision=2) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=0) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=-1, end_revision=1) 
        self.assertRaises(InvalidRevisionNumber, show_log, b, lf,
                          start_revision=1, end_revision=-1) 

    def test_simple_log(self):
        eq = self.assertEquals
        
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        lf = LogCatcher()
        show_log(b, lf)
        # no entries yet
        eq(lf.logs, [])

        wt.commit('empty commit')
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        eq(len(lf.logs), 1)
        eq(lf.logs[0].revno, '1')
        eq(lf.logs[0].rev.message, 'empty commit')
        d = lf.logs[0].delta
        self.log('log delta: %r' % d)
        self.checkDelta(d)

        self.build_tree(['hello'])
        wt.add('hello')
        wt.commit('add one file')

        lf = StringIO()
        # log using regular thing
        show_log(b, LongLogFormatter(lf))
        lf.seek(0)
        for l in lf.readlines():
            self.log(l)

        # get log as data structure
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        eq(len(lf.logs), 2)
        self.log('log entries:')
        for logentry in lf.logs:
            self.log('%4s %s' % (logentry.revno, logentry.rev.message))
        
        # first one is most recent
        logentry = lf.logs[0]
        eq(logentry.revno, '2')
        eq(logentry.rev.message, 'add one file')
        d = logentry.delta
        self.log('log 2 delta: %r' % d)
        # self.checkDelta(d, added=['hello'])
        
        # commit a log message with control characters
        msg = "All 8-bit chars: " +  ''.join([unichr(x) for x in range(256)])
        self.log("original commit message: %r", msg)
        wt.commit(msg)
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        committed_msg = lf.logs[0].rev.message
        self.log("escaped commit message: %r", committed_msg)
        self.assert_(msg != committed_msg)
        self.assert_(len(committed_msg) > len(msg))

        # Check that log message with only XML-valid characters isn't
        # escaped.  As ElementTree apparently does some kind of
        # newline conversion, neither LF (\x0A) nor CR (\x0D) are
        # included in the test commit message, even though they are
        # valid XML 1.0 characters.
        msg = "\x09" + ''.join([unichr(x) for x in range(0x20, 256)])
        self.log("original commit message: %r", msg)
        wt.commit(msg)
        lf = LogCatcher()
        show_log(b, lf, verbose=True)
        committed_msg = lf.logs[0].rev.message
        self.log("escaped commit message: %r", committed_msg)
        self.assert_(msg == committed_msg)

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        b.nick='test'
        open('a', 'wb').write('hello moto\n')
        wt.add('a')
        wt.commit('simple log message', rev_id='a1'
                , timestamp=1132586655.459960938, timezone=-6*3600
                , committer='Joe Foo <joe@foo.com>')
        open('b', 'wb').write('goodbye\n')
        wt.add('b')
        wt.commit('multiline\nlog\nmessage\n', rev_id='a2'
                , timestamp=1132586842.411175966, timezone=-6*3600
                , committer='Joe Foo <joe@foo.com>')

        open('c', 'wb').write('just another manic monday\n')
        wt.add('c')
        wt.commit('single line with trailing newline\n', rev_id='a3'
                , timestamp=1132587176.835228920, timezone=-6*3600
                , committer = 'Joe Foo <joe@foo.com>')

        sio = StringIO()
        lf = ShortLogFormatter(to_file=sio)
        show_log(b, lf)
        self.assertEquals(sio.getvalue(), """\
    3 Joe Foo\t2005-11-21
      single line with trailing newline

    2 Joe Foo\t2005-11-21
      multiline
      log
      message

    1 Joe Foo\t2005-11-21
      simple log message

""")

        sio = StringIO()
        lf = LongLogFormatter(to_file=sio)
        show_log(b, lf)
        self.assertEquals(sio.getvalue(), """\
------------------------------------------------------------
revno: 3
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Mon 2005-11-21 09:32:56 -0600
message:
  single line with trailing newline
------------------------------------------------------------
revno: 2
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Mon 2005-11-21 09:27:22 -0600
message:
  multiline
  log
  message
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Mon 2005-11-21 09:24:15 -0600
message:
  simple log message
""")
        
    def test_verbose_log(self):
        """Verbose log includes changed files
        
        bug #4676
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        # XXX: why does a longer nick show up?
        b.nick = 'test_verbose_log'
        wt.commit(message='add a', 
                  timestamp=1132711707, 
                  timezone=36000,
                  committer='Lorem Ipsum <test@example.com>')
        logfile = file('out.tmp', 'w+')
        formatter = LongLogFormatter(to_file=logfile)
        show_log(b, formatter, verbose=True)
        logfile.flush()
        logfile.seek(0)
        log_contents = logfile.read()
        self.assertEqualDiff(log_contents, '''\
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: test_verbose_log
timestamp: Wed 2005-11-23 12:08:27 +1000
message:
  add a
added:
  a
''')

    def test_line_log(self):
        """Line log should show revno
        
        bug #5162
        """
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['a'])
        wt.add('a')
        b.nick = 'test-line-log'
        wt.commit(message='add a', 
                  timestamp=1132711707, 
                  timezone=36000,
                  committer='Line-Log-Formatter Tester <test@line.log>')
        logfile = file('out.tmp', 'w+')
        formatter = LineLogFormatter(to_file=logfile)
        show_log(b, formatter)
        logfile.flush()
        logfile.seek(0)
        log_contents = logfile.read()
        self.assertEqualDiff(log_contents, '1: Line-Log-Formatte... 2005-11-23 add a\n')

    def make_tree_with_commits(self):
        """Create a tree with well-known revision ids"""
        wt = self.make_branch_and_tree('tree1')
        wt.commit('commit one', rev_id='1')
        wt.commit('commit two', rev_id='2')
        wt.commit('commit three', rev_id='3')
        mainline_revs = [None, '1', '2', '3']
        rev_nos = {'1': 1, '2': 2, '3': 3}
        return mainline_revs, rev_nos, wt

    def make_tree_with_merges(self):
        """Create a tree with well-known revision ids and a merge"""
        mainline_revs, rev_nos, wt = self.make_tree_with_commits()
        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()
        tree2.commit('four-a', rev_id='4a')
        wt.merge_from_branch(tree2.branch)
        wt.commit('four-b', rev_id='4b')
        mainline_revs.append('4b')
        rev_nos['4b'] = 4
        # 4a: 3.1.1
        return mainline_revs, rev_nos, wt

    def make_tree_with_many_merges(self):
        """Create a tree with well-known revision ids"""
        wt = self.make_branch_and_tree('tree1')
        wt.commit('commit one', rev_id='1')
        wt.commit('commit two', rev_id='2')
        tree3 = wt.bzrdir.sprout('tree3').open_workingtree()
        tree3.commit('commit three a', rev_id='3a')
        tree2 = wt.bzrdir.sprout('tree2').open_workingtree()
        tree2.merge_from_branch(tree3.branch)
        tree2.commit('commit three b', rev_id='3b')
        wt.merge_from_branch(tree2.branch)
        wt.commit('commit three c', rev_id='3c')
        tree2.commit('four-a', rev_id='4a')
        wt.merge_from_branch(tree2.branch)
        wt.commit('four-b', rev_id='4b')
        mainline_revs = [None, '1', '2', '3c', '4b']
        rev_nos = {'1':1, '2':2, '3c': 3, '4b':4}
        full_rev_nos_for_reference = {
            '1': '1',
            '2': '2',
            '3a': '2.2.1', #first commit tree 3
            '3b': '2.1.1', # first commit tree 2
            '3c': '3', #merges 3b to main
            '4a': '2.1.2', # second commit tree 2
            '4b': '4', # merges 4a to main
            }
        return mainline_revs, rev_nos, wt

    def test_get_view_revisions_forward(self):
        """Test the get_view_revisions method"""
        mainline_revs, rev_nos, wt = self.make_tree_with_commits()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'forward'))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0)],
            revisions)
        revisions2 = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'forward', include_merges=False))
        self.assertEqual(revisions, revisions2)

    def test_get_view_revisions_reverse(self):
        """Test the get_view_revisions with reverse"""
        mainline_revs, rev_nos, wt = self.make_tree_with_commits()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'reverse'))
        self.assertEqual([('3', '3', 0), ('2', '2', 0), ('1', '1', 0), ],
            revisions)
        revisions2 = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'reverse', include_merges=False))
        self.assertEqual(revisions, revisions2)

    def test_get_view_revisions_merge(self):
        """Test get_view_revisions when there are merges"""
        mainline_revs, rev_nos, wt = self.make_tree_with_merges()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'forward'))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0),
            ('4b', '4', 0), ('4a', '3.1.1', 1)],
            revisions)
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'forward', include_merges=False))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3', '3', 0),
            ('4b', '4', 0)],
            revisions)

    def test_get_view_revisions_merge_reverse(self):
        """Test get_view_revisions in reverse when there are merges"""
        mainline_revs, rev_nos, wt = self.make_tree_with_merges()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'reverse'))
        self.assertEqual([('4b', '4', 0), ('4a', '3.1.1', 1),
            ('3', '3', 0), ('2', '2', 0), ('1', '1', 0)],
            revisions)
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'reverse', include_merges=False))
        self.assertEqual([('4b', '4', 0), ('3', '3', 0), ('2', '2', 0),
            ('1', '1', 0)],
            revisions)

    def test_get_view_revisions_merge2(self):
        """Test get_view_revisions when there are merges"""
        mainline_revs, rev_nos, wt = self.make_tree_with_many_merges()
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                            'forward'))
        expected = [('1', '1', 0), ('2', '2', 0), ('3c', '3', 0),
            ('3a', '2.2.1', 1), ('3b', '2.1.1', 1), ('4b', '4', 0),
            ('4a', '2.1.2', 1)]
        self.assertEqual(expected, revisions)
        revisions = list(get_view_revisions(mainline_revs, rev_nos, wt.branch,
                                             'forward', include_merges=False))
        self.assertEqual([('1', '1', 0), ('2', '2', 0), ('3c', '3', 0),
            ('4b', '4', 0)],
            revisions)
