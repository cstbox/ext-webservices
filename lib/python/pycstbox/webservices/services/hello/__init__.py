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

""" Test web service """

__author__ = 'Eric PASCUAL - CSTB (eric.pascual@cstb.fr)'


import sys, inspect

from pycstbox import log
from pycstbox.webservices.wsapp import WSHandler


def _init_(logger=None, settings=None):
    """ Module init function, called by the application framework during the
    services discovery process."""

    # inject the logger in handlers default initialize parameters
    _handlers_initparms['logger'] = logger if logger else log.getLogger('svc.hello')


class SayHelloHandler(WSHandler):
    """ Extended Web service base request handler """
    def do_post(self):
        to_who = self.get_argument('to', 'World')
        self._logger.debug("saying hello to %s", to_who)
        self.write({'message': 'Hello ' + to_who})

_handlers_initparms = {}

handlers = [
    ("/say", SayHelloHandler, _handlers_initparms),
]


