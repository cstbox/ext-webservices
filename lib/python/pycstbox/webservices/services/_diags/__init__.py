#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of CSTBox.
#
# CSTBox is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# CSTBox is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with CSTBox.  If not, see <http://www.gnu.org/licenses/>.

""" Internal web services for tests and diagnostics"""

__author__ = 'Eric PASCUAL - CSTB (eric.pascual@cstb.fr)'


from pycstbox import log
from pycstbox.webservices.wsapp import WSHandler


def _init_(logger=None, settings=None):
    """ Module init function, called by the application framework during the
    services discovery process."""

    # inject the logger in handlers default initialize parameters
    _handlers_initparms['logger'] = logger if logger else log.getLogger('svc.hello')


class HelloHandler(WSHandler):
    def do_get(self):
        to_who = self.get_argument('to', 'World')
        self._logger.debug("saying hello to %s", to_who)
        self.write({'message': 'Hello ' + to_who})


class RoutesHandler(WSHandler):
    def do_get(self, *args, **kwargs):
        routes = [handler[0] for handler in self.application.app_server._handlers]
        self.write({'routes': routes})

_handlers_initparms = {}

handlers = [
    ("/hello", HelloHandler, _handlers_initparms),
    ("/routes", RoutesHandler, _handlers_initparms),
]


