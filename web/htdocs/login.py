#!/usr/bin/python
# -*- encoding: utf-8; py-indent-offset: 4 -*-
# +------------------------------------------------------------------+
# |             ____ _               _        __  __ _  __           |
# |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
# |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
# |           | |___| | | |  __/ (__|   <    | |  | | . \            |
# |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
# |                                                                  |
# | Copyright Mathias Kettner 2011             mk@mathias-kettner.de |
# +------------------------------------------------------------------+
#
# This file is part of Check_MK.
# The official homepage is at http://mathias-kettner.de/check_mk.
#
# check_mk is free software;  you can redistribute it and/or modify it
# under the  terms of the  GNU General Public License  as published by
# the Free Software Foundation in version 2.  check_mk is  distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
# out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
# PARTICULAR PURPOSE. See the  GNU General Public License for more de-
# ails.  You should have  received  a copy of the  GNU  General Public
# License along with GNU Make; see the file  COPYING.  If  not,  write
# to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
# Boston, MA 02110-1301 USA.

import defaults, htmllib, config
from lib import *
from mod_python import apache
import md5, md5crypt, crypt, time

class MKAuthException(MKGeneralException):
    pass

def site_cookie_name():
    name = os.path.dirname(defaults.url_prefix).replace('/', '_')
    return 'auth%s' % name

# Validate hashes taken from the htpasswd file. This method handles
# crypt() and md5 hashes. This should be the common cases in the
# used htpasswd files.
def password_valid(pwhash, password):
    if pwhash[:3] == '$1$':
        salt = pwhash.split('$', 3)[2]
        return pwhash == md5crypt.md5crypt(password, salt, '$1$')
    else:
        #html.write(repr(pwhash + ' ' + crypt.crypt(password, pwhash)))
        return pwhash == crypt.crypt(password, pwhash[:2])

# Loads the contents of a valid htpasswd file into a dictionary
# and returns the dictionary
def load_htpasswd():
    creds = {}

    for line in open(defaults.htpasswd_file, 'r'):
        username, pwhash = line.split(':', 1)
        creds[username] = pwhash.rstrip('\n')

    return creds

# Reads the auth secret from a file. Creates the files if it does
# not exist. Having access to the secret means that one can issue valid
# cookies for the cookie auth.
# FIXME: Secret auch replizieren
def load_secret():
    secret_path = '%s/auth.secret' % os.path.dirname(defaults.htpasswd_file)
    if not os.path.exists(secret_path):
        secret = md5.md5(str(time.time())).hexdigest()
        file(secret_path, 'w').write(secret)
    else:
        secret = file(secret_path).read().strip()
    return secret

# Generates the hash to be added into the cookie value
def generate_hash(username, now, pwhash):
    secret = load_secret()
    return md5.md5(username + now + pwhash + secret).hexdigest()

def del_auth_cookie():
    name = site_cookie_name()
    if html.has_cookie(name):
        html.del_cookie(name)

def set_auth_cookie(username, pwhash):
    now = str(time.time())
    html.set_cookie(site_cookie_name(), username
                                        + ':' + now
                                        + ':' + generate_hash(username, now, pwhash))

def check_auth_cookie(cookie_name):
    username, issue_time, cookie_hash = html.cookie(cookie_name, '::').split(':', 2)

    # FIXME: Ablauf-Zeit des Cookies testen
    #max_cookie_age = 10
    #if float(issue_time) < time.time() - max_cookie_age:
    #    del_auth_cookie()
    #    return ''

    users = load_htpasswd()
    if not username in users:
        raise MKAuthException(_('Username is unknown'))
    pwhash = users[username]

    # Validate the hash
    if cookie_hash != generate_hash(username, issue_time, pwhash):
        raise MKAuthException(_('Invalid credentials'))

    # Once reached this the cookie is a good one. Renew it!
    # Do not renew if:
    # a) The _ajaxid var is set
    # b) A logout is requested
    if (html.req.myfile != 'logout' or html.has_var('_ajaxid')) \
       and cookie_name == site_cookie_name():
        set_auth_cookie(username, pwhash)

    # Return the authenticated username
    return username

def check_auth():
    for cookie_name in html.get_cookie_names():
        if cookie_name.startswith('auth_'):
            try:
                return check_auth_cookie(cookie_name)
            except Exception, e:
                #html.write('Exception occured while checking cookie %s' % cookie_name)
                #raise
                pass

    return ''


def login_page():
    # handle the sent login form
    err = None
    if html.var('_login'):
        try:
            username = html.var('_username', '')
            if username == '':
                raise MKUserError('_username', _('No username given.'))

            password = html.var('_password', '')
            if password == '':
                raise MKUserError('_password', _('No password given.'))

            origin = html.var('_origin')
            if not origin:
                origin = defaults.url_prefix + 'check_mk/'

            users = load_htpasswd()
            if username in users and password_valid(users[username], password):
                # The login succeeded! Now:
                # a) Set the auth cookie
                # b) Unset the login vars in further processing
                # c) Show the real requested page (No redirect needed)
                set_auth_cookie(username, users[username])

                # Use redirects for URLs or simply execute other handlers for
                # mulitsite modules
                if '/' in origin:
                    html.set_http_header('Location', origin)
                    raise apache.SERVER_RETURN, apache.HTTP_MOVED_TEMPORARILY
                else:
                    # Remove login vars to hide them from the next page handler
                    try:
                        del html.req.vars['_username']
                        del html.req.vars['_password']
                        del html.req.vars['_login']
                        del html.req.vars['_origin']
                    except:
                        pass

                    return (username, origin)
            else:
                raise MKUserError(None, _('Invalid credentials.'))
        except MKUserError, e:
            err = e
            html.add_user_error(e.varname, e.message)

    html.set_render_headfoot(False)

    html.header(_("Check_MK Multisite Login"), javascripts=[], stylesheets=["pages","login"])

    if err:
        html.write('<div class=error>%s</div>\n' % e.message)

    origin = html.var('_origin', '')
    if not origin and not html.req.myfile == 'login':
        origin = html.req.uri

    html.write("<div id=login>")
    html.write("<div id=logo></div>")
    html.write("<h1>Check_MK Multisite</h2>")
    html.write("<table id=table>")
    html.write("<tr class=form>\n")
    html.write("<td>")
    html.begin_form("login", method = 'POST', add_transid = False)
    html.hidden_field('_origin', htmllib.attrencode(origin))
    html.write("<div class=whiteborder>\n")
    html.write("<table class=\"form\">\n")

    html.write("<tr>")
    html.write("<td class=legend>%s</td>" % _('Username'))
    html.write("<td class=content>")
    html.text_input("_username", size = 50)
    html.write("</td>")
    html.write("</tr>")

    html.write("<tr>")
    html.write("<td class=legend>%s</td>" % _('Password'))
    html.write("<td class=content>")
    html.password_input("_password", size = 50)
    html.write("</td>")
    html.write("</tr>")

    html.write("<tr>")
    html.write("<td colspan=2 class=legend>")
    html.button("_login", _('Login'))
    html.write("</td>")
    html.write("</tr>")

    html.write("</table>")
    html.write("<div id=foot>Version: %s - &copy; "
               "<a href=\"http://mathias-kettner.de\">Mathias Kettner</a></div>" % defaults.check_mk_version)
    html.write("</div>")
    html.set_focus('_username')
    html.end_form()

    html.footer()
    return apache.OK

def logout():
    # Remove eventual existing cookie
    del_auth_cookie()

    if config.auth_type == 'cookie':
        html.set_http_header('Location', defaults.url_prefix + 'check_mk/')
        raise apache.SERVER_RETURN, apache.HTTP_MOVED_TEMPORARILY
    else:
        # Implement HTTP logout with cookie hack
        if not html.has_cookie('logout'):
            html.set_http_header('WWW-Authenticate', 'Basic realm="%s"' % defaults.nagios_auth_name)
            html.set_cookie('logout', '1')
            raise apache.SERVER_RETURN, apache.HTTP_UNAUTHORIZED
        else:
            html.del_cookie('logout')
            html.set_http_header('Location', defaults.url_prefix + 'check_mk/')
            raise apache.SERVER_RETURN, apache.HTTP_MOVED_TEMPORARILY
