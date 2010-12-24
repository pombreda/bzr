# Copyright (C) 2007, 2009, 2010 Canonical Ltd
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

from email.Message import Message
import errno
import smtplib
import socket

from bzrlib import (
    config,
    email_message,
    errors,
    smtp_connection,
    tests,
    ui,
    )


def connection_refuser():
    def connect(server):
        raise socket.error(errno.ECONNREFUSED, 'Connection Refused')
    smtp = smtplib.SMTP()
    smtp.connect = connect
    return smtp


class StubSMTPFactory(object):
    """A fake SMTP connection to test the connection setup."""
    def __init__(self, fail_on=None, smtp_features=None):
        self._fail_on = fail_on or []
        self._calls = []
        self._smtp_features = smtp_features or []
        self._ehlo_called = False

    def __call__(self):
        # The factory pretends to be a connection
        return self

    def connect(self, server):
        self._calls.append(('connect', server))

    def helo(self):
        self._calls.append(('helo',))
        if 'helo' in self._fail_on:
            return 500, 'helo failure'
        else:
            return 200, 'helo success'

    def ehlo(self):
        self._calls.append(('ehlo',))
        if 'ehlo' in self._fail_on:
            return 500, 'ehlo failure'
        else:
            self._ehlo_called = True
            return 200, 'ehlo success'

    def has_extn(self, extension):
        self._calls.append(('has_extn', extension))
        return self._ehlo_called and extension in self._smtp_features

    def starttls(self):
        self._calls.append(('starttls',))
        if 'starttls' in self._fail_on:
            return 500, 'starttls failure'
        else:
            self._ehlo_called = True
            return 200, 'starttls success'


class WideOpenSMTPFactory(StubSMTPFactory):
    """A fake smtp server that implements login by accepting anybody."""

    def login(self, user, password):
        self._calls.append(('login', user, password))


class TestSMTPConnection(tests.TestCaseInTempDir):

    def get_connection(self, text, smtp_factory=None):
        my_config = config.GlobalConfig.from_string(text)
        return smtp_connection.SMTPConnection(my_config,
                                              _smtp_factory=smtp_factory)

    def test_defaults(self):
        conn = self.get_connection('')
        self.assertEqual('localhost', conn._smtp_server)
        self.assertEqual(None, conn._smtp_username)
        self.assertEqual(None, conn._smtp_password)

    def test_smtp_server(self):
        conn = self.get_connection('[DEFAULT]\nsmtp_server=host:10\n')
        self.assertEqual('host:10', conn._smtp_server)

    def test_missing_server(self):
        conn = self.get_connection('', smtp_factory=connection_refuser)
        self.assertRaises(errors.DefaultSMTPConnectionRefused, conn._connect)
        conn = self.get_connection('[DEFAULT]\nsmtp_server=smtp.example.com\n',
                                   smtp_factory=connection_refuser)
        self.assertRaises(errors.SMTPConnectionRefused, conn._connect)

    def test_smtp_username(self):
        conn = self.get_connection('')
        self.assertIs(None, conn._smtp_username)

        conn = self.get_connection('[DEFAULT]\nsmtp_username=joebody\n')
        self.assertEqual(u'joebody', conn._smtp_username)

    def test_smtp_password_from_config(self):
        conn = self.get_connection('')
        self.assertIs(None, conn._smtp_password)

        conn = self.get_connection('[DEFAULT]\nsmtp_password=mypass\n')
        self.assertEqual(u'mypass', conn._smtp_password)

    def test_smtp_password_from_user(self):
        user = 'joe'
        password = 'hispass'
        factory = WideOpenSMTPFactory()
        conn = self.get_connection('[DEFAULT]\nsmtp_username=%s\n' % user,
                                   smtp_factory=factory)
        self.assertIs(None, conn._smtp_password)

        ui.ui_factory = ui.CannedInputUIFactory([password])
        conn._connect()
        self.assertEqual(password, conn._smtp_password)

    def test_smtp_password_from_auth_config(self):
        user = 'joe'
        password = 'hispass'
        factory = WideOpenSMTPFactory()
        conn = self.get_connection('[DEFAULT]\nsmtp_username=%s\n' % user,
                                   smtp_factory=factory)
        self.assertEqual(user, conn._smtp_username)
        self.assertIs(None, conn._smtp_password)
        # Create a config file with the right password
        conf = config.AuthenticationConfig()
        conf._get_config().update({'smtptest':
                                       {'scheme': 'smtp', 'user':user,
                                        'password': password}})
        conf._save()

        conn._connect()
        self.assertEqual(password, conn._smtp_password)

    def test_authenticate_with_byte_strings(self):
        user = 'joe'
        unicode_pass = u'h\xECspass'
        utf8_pass = unicode_pass.encode('utf-8')
        factory = WideOpenSMTPFactory()
        conn = self.get_connection(
            u'[DEFAULT]\nsmtp_username=%s\nsmtp_password=%s\n'
            % (user, unicode_pass), smtp_factory=factory)
        self.assertEqual(unicode_pass, conn._smtp_password)
        conn._connect()
        self.assertEqual([('connect', 'localhost'),
                          ('ehlo',),
                          ('has_extn', 'starttls'),
                          ('login', user, utf8_pass)], factory._calls)
        smtp_username, smtp_password = factory._calls[-1][1:]
        self.assertIsInstance(smtp_username, str)
        self.assertIsInstance(smtp_password, str)

    def test_create_connection(self):
        factory = StubSMTPFactory()
        conn = self.get_connection('', smtp_factory=factory)
        conn._create_connection()
        self.assertEqual([('connect', 'localhost'),
                          ('ehlo',),
                          ('has_extn', 'starttls')], factory._calls)

    def test_create_connection_ehlo_fails(self):
        # Check that we call HELO if EHLO failed.
        factory = StubSMTPFactory(fail_on=['ehlo'])
        conn = self.get_connection('', smtp_factory=factory)
        conn._create_connection()
        self.assertEqual([('connect', 'localhost'),
                          ('ehlo',),
                          ('helo',),
                          ('has_extn', 'starttls')], factory._calls)

    def test_create_connection_ehlo_helo_fails(self):
        # Check that we raise an exception if both EHLO and HELO fail.
        factory = StubSMTPFactory(fail_on=['ehlo', 'helo'])
        conn = self.get_connection('', smtp_factory=factory)
        self.assertRaises(errors.SMTPError, conn._create_connection)
        self.assertEqual([('connect', 'localhost'),
                          ('ehlo',),
                          ('helo',)], factory._calls)

    def test_create_connection_starttls(self):
        # Check that STARTTLS plus a second EHLO are called if the
        # server says it supports the feature.
        factory = StubSMTPFactory(smtp_features=['starttls'])
        conn = self.get_connection('', smtp_factory=factory)
        conn._create_connection()
        self.assertEqual([('connect', 'localhost'),
                          ('ehlo',),
                          ('has_extn', 'starttls'),
                          ('starttls',),
                          ('ehlo',)], factory._calls)

    def test_create_connection_starttls_fails(self):
        # Check that we raise an exception if the server claims to
        # support STARTTLS, but then fails when we try to activate it.
        factory = StubSMTPFactory(fail_on=['starttls'],
                                  smtp_features=['starttls'])
        conn = self.get_connection('', smtp_factory=factory)
        self.assertRaises(errors.SMTPError, conn._create_connection)
        self.assertEqual([('connect', 'localhost'),
                          ('ehlo',),
                          ('has_extn', 'starttls'),
                          ('starttls',)], factory._calls)

    def test_get_message_addresses(self):
        msg = Message()

        from_, to = smtp_connection.SMTPConnection.get_message_addresses(msg)
        self.assertEqual('', from_)
        self.assertEqual([], to)

        msg['From'] = '"J. Random Developer" <jrandom@example.com>'
        msg['To'] = 'John Doe <john@doe.com>, Jane Doe <jane@doe.com>'
        msg['CC'] = u'Pepe P\xe9rez <pperez@ejemplo.com>'
        msg['Bcc'] = 'user@localhost'

        from_, to = smtp_connection.SMTPConnection.get_message_addresses(msg)
        self.assertEqual('jrandom@example.com', from_)
        self.assertEqual(sorted(['john@doe.com', 'jane@doe.com',
            'pperez@ejemplo.com', 'user@localhost']), sorted(to))

        # now with bzrlib's EmailMessage
        msg = email_message.EmailMessage(
            '"J. Random Developer" <jrandom@example.com>',
            ['John Doe <john@doe.com>', 'Jane Doe <jane@doe.com>',
             u'Pepe P\xe9rez <pperez@ejemplo.com>', 'user@localhost' ],
            'subject')

        from_, to = smtp_connection.SMTPConnection.get_message_addresses(msg)
        self.assertEqual('jrandom@example.com', from_)
        self.assertEqual(sorted(['john@doe.com', 'jane@doe.com',
            'pperez@ejemplo.com', 'user@localhost']), sorted(to))

    def test_destination_address_required(self):
        class FakeConfig:
            def get_user_option(self, option):
                return None

        msg = Message()
        msg['From'] = '"J. Random Developer" <jrandom@example.com>'
        self.assertRaises(
            errors.NoDestinationAddress,
            smtp_connection.SMTPConnection(FakeConfig()).send_email, msg)

        msg = email_message.EmailMessage('from@from.com', '', 'subject')
        self.assertRaises(
            errors.NoDestinationAddress,
            smtp_connection.SMTPConnection(FakeConfig()).send_email, msg)

        msg = email_message.EmailMessage('from@from.com', [], 'subject')
        self.assertRaises(
            errors.NoDestinationAddress,
            smtp_connection.SMTPConnection(FakeConfig()).send_email, msg)
