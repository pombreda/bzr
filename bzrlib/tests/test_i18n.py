# Copyright (C) 2011 Canonical Ltd
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

"""Tests for bzrlib.i18n"""

from bzrlib import (i18n, 
                    tests, 
                    errors, 
                    workingtree,
                    )


class ZzzTranslations(object):
    """Special Zzz translation for debugging i18n stuff.

    This class can be used to confirm that the message is properly translated
    during black box tests.
    """
    _null_translation = i18n._gettext.NullTranslations()

    def zzz(self, s):
        return u'zz\xe5{{%s}}' % s

    def ugettext(self, s):
        return self.zzz(self._null_translation.ugettext(s))

    def ungettext(self, s, p, n):
        return self.zzz(self._null_translation.ungettext(s, p, n))


class TestZzzTranslation(tests.TestCase):

    def _check_exact(self, expected, source):
        self.assertEqual(expected, source)
        self.assertEqual(type(expected), type(source))

    def test_translation(self):
        trans = ZzzTranslations()

        t = trans.zzz('msg')
        self._check_exact(u'zz\xe5{{msg}}', t)

        t = trans.ugettext('msg')
        self._check_exact(u'zz\xe5{{msg}}', t)

        t = trans.ungettext('msg1', 'msg2', 0)
        self._check_exact(u'zz\xe5{{msg2}}', t)
        t = trans.ungettext('msg1', 'msg2', 2)
        self._check_exact(u'zz\xe5{{msg2}}', t)

        t = trans.ungettext('msg1', 'msg2', 1)
        self._check_exact(u'zz\xe5{{msg1}}', t)


class TestGetText(tests.TestCase):

    def setUp(self):
        super(TestGetText, self).setUp()
        self.overrideAttr(i18n, '_translations', ZzzTranslations())

    def test_oneline(self):
        self.assertEqual(u"zz\xe5{{spam ham eggs}}",
                         i18n.gettext("spam ham eggs"))

    def test_multiline(self):
        self.assertEqual(u"zz\xe5{{spam\nham\n\neggs\n}}",
                         i18n.gettext("spam\nham\n\neggs\n"))


class TestGetTextPerParagraph(tests.TestCase):

    def setUp(self):
        super(TestGetTextPerParagraph, self).setUp()
        self.overrideAttr(i18n, '_translations', ZzzTranslations())

    def test_oneline(self):
        self.assertEqual(u"zz\xe5{{spam ham eggs}}",
                         i18n.gettext_per_paragraph("spam ham eggs"))

    def test_multiline(self):
        self.assertEqual(u"zz\xe5{{spam\nham}}\n\nzz\xe5{{eggs\n}}",
                         i18n.gettext_per_paragraph("spam\nham\n\neggs\n"))


class TestInstall(tests.TestCase):

    def setUp(self):
        super(TestInstall, self).setUp()
        # Restore a proper env to test translation installation
        self.overrideAttr(i18n, 'installed', self.i18nInstalled)
        self.overrideAttr(i18n, '_translations', None)

    def test_custom_languages(self):
        self.enableI18n()
        i18n.install('nl:fy')
        self.assertIsInstance(i18n._translations, i18n._gettext.NullTranslations)

    def test_no_env_variables(self):
        self.overrideEnv('LANGUAGE', None)
        self.overrideEnv('LC_ALL', None)
        self.overrideEnv('LC_MESSAGES', None)
        self.overrideEnv('LANG', None)
        i18n.install()
        self.assertIsInstance(i18n._translations, i18n._gettext.NullTranslations)

    def test_disable_i18n(self):
        i18n.disable_i18n()
        i18n.install()
        self.assertTrue(i18n._translations is None)


class TestTranslate(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestTranslate, self).setUp()
        self.overrideAttr(i18n, '_translations', ZzzTranslations())

    def test_error_message_translation(self):
        """do errors get translated?"""
        err = None
        tree = self.make_branch_and_tree('.')
        try:
            workingtree.WorkingTree.open('./foo')
        except errors.NotBranchError,e:
            err = str(e)
        self.assertContainsRe(err, 
                              u"zz\xe5{{Not a branch: .*}}".encode("utf-8"))

    def test_topic_help_translation(self):
        """does topic help get translated?"""
        from bzrlib import help
        from StringIO import StringIO
        out = StringIO()
        help.help("authentication", out)
        self.assertContainsRe(out.getvalue(), "zz\xe5{{Authentication Settings")
