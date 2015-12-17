#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" This module defines the base components used to implement Web services inside the CSTBox.

It provides the :py:class:`AppServer` top level class, which provide the server level features,
including the automatic discovery if services packaged with the application.

Individual services are managed as plugins, and must thus be provided as sub-packages of
the `pycstbox.webservices.services` package, conforming to specific conventions in order to be
identified as such. These conventions are described in :py:meth:`AppServer._discover_services` method
documentation.

It must be noted that the discovery is done at application startup time only, and thus
service hot-(un)pluging is not supported (and will never be, since not really useful in
the context of CSTBox framework usage).
"""

import os
import ConfigParser
import importlib
import signal
import sys
import re
from collections import namedtuple

import tornado.web
import tornado.httpserver
import tornado.ioloop

from pycstbox import log, config, sysutils

__author__ = 'Eric Pascual - CSTB (eric.pascual@cstb.fr)'

_here = os.path.dirname(__file__)

MANIFEST_FILE_NAME = 'MANIFEST'
MANIFEST_MAIN_SECTION = 'service'
MANIFEST_SETTINGS_SECTION = 'settings'
SERVICES_PACKAGE_NAME = 'pycstbox.webservices.services'


class WSHandler(tornado.web.RequestHandler):
    """ Web service base request handler """

    _logger = None

    def initialize(self, logger=None, **kwargs): #pylint: disable=W0221
        if logger:
            self._logger = logger
            if self.application.settings['debug']:
                self._logger.setLevel(log.DEBUG)

    def _process_request(self, method, *args, **kwargs):
        try:
            method(*args, **kwargs)
        except Exception as e:
            if self._logger:
                self._logger.exception(e)
            if isinstance(e, tornado.web.HTTPError):
                raise
            else:
                self.exception_reply(e)
        else:
            # force a write of the reply now, to avoid some clients considering they are stalled,
            # (tolerate request no more opened situation)
            try:
                self.flush()
            except RuntimeError:
                # request was already finished
                pass

    def get(self, *args, **kwargs):
        self._process_request(self.do_get, *args, **kwargs)

    def do_get(self, *args, **kwargs):
        self.reply_not_implemented()

    def post(self, *args, **kwargs):
        self._process_request(self.do_post, *args, **kwargs)

    def do_post(self, *args, **kwargs):
        self.reply_not_implemented()

    def put(self, *args, **kwargs):
        self._process_request(self.do_put, *args, **kwargs)

    def do_put(self, *args, **kwargs):
        self.reply_not_implemented()

    def delete(self, *args, **kwargs):
        self._process_request(self.do_delete, *args, **kwargs)

    def do_delete(self, *args, **kwargs):
        self.reply_not_implemented()

    def write_error(self, status_code, exc_info=None, **kwargs):
        """ Overridden version of error reporting, returning the reply as JSON data.
        """
        exception = exc_info[1]
        if isinstance(exception, tornado.web.HTTPError):
            self.write({'message': exception.log_message})
            self.set_status(status_code)
        else:
            self.exception_reply(exception)

    def exception_reply(self, e):
        type_, value, _tb = sys.exc_info()
        if self._logger:
            self._logger.exception("unexpected error '%s' with message '%s'" % (type_.__name__, value))
            self._logger.error('--- end of traceback ---')

        self.set_status(500)
        data = {
            'errtype': type_.__name__,
            'message': str(value),
            'additInfos': str(e.reason) if hasattr(e, 'reason') else ''
        }
        self.write(data)

    def error_reply(self, message, status_code=500, addit_infos=None):
        self.set_status(status_code)
        data = {
            'message': message,
            'additInfos': addit_infos or ''
        }
        if self._logger:
            if addit_infos:
                self._logger.error('request error: %s (addit infos: %s)', message, addit_infos)
            else:
                self._logger.error('request error: %s', message)
        self.write(data)

    def reply_not_implemented(self):
        self.set_status(501)
        data = {
            'message': 'not yet implemented'
        }
        self.write(data)


class ServiceDescriptor(namedtuple('ServiceDescriptor', 'name label handlers')):
    """ Descriptor of a service.

    Included attributes:
        - the service symbolic name
        - the label to be displayed under the icon and to be used asthe title
        - the base URL of the service
        - a list of (url pattern, handler) mapping tuples
    """


class AppServer(object):
    """ Implements the application server, including installed services automatic discovery.
    """
    APP_NAME = "wsapi"

    _logger = None
    _services_home = os.path.join(_here, "services")

    def __init__(self, url_base="/api/", port=8888, debug=False):
        """ Constructor

        :Parameters:
            port : int
                the port the server will listen to (default: 8888)
        """
        self._app_url_base = url_base
        self._port = port
        self._debug = debug
        self._logger = log.getLogger(self.APP_NAME)
        self._services = None
        self._ioloop = None

        if self._debug:
            self._logger.setLevel(log.DEBUG)
            self._logger.warn(
                "AppServer instantiated with debug mode activated")

    def _get_services(self):
        # Since the list is immutable once the server is started, we cache the
        # result and compute it only if not yet done.
        if self._services is None:
            self._services = self._discover_services()
            if len(self._services) == 0:
                self._logger.warn("No service found")
        return self._services

    services = property(
        _get_services,
        doc=""" The read-only list of discovered services """
    )

    _services_cfg_defaults = {
        'mapping': 'handlers'
    }

    def _discover_services(self, home=None):    # pylint: disable=R0912
        """ Discover the services stored in the directory which path is provided.

        A service must be packaged as a Python sub-package, providing the following
        mandatory items:

            - the standard `__init__.py` module, which exposes the service request
            handler(s) and auxiliary definitions. Exposure can be done either by
            importing from sub-modules, or by directly containing the involved
            definitions.

            - MANIFEST file, in the form of a config file with the following
            minimal content :
                [service]
                label=<display label>
                mapping=<module attribute containing the route table>

        The `mapping` key can be omitted, and will be defaulted to `handlers` in this case.

        Services developers are free to use the manifest file to store additional
        properties they would need. These custom settings should be stored in the
        predefined `settings` section.

        The route table is mandatory and is the one used by Tornado application class
        to build the dispatch table for routing requests to the appropriate handlers.

        IMPORTANT: URLs included in the service routing table are relative. A kind-of
        namespace mechanism is used when merging service level routing tables to build
        the application global one, by prefixing the provided URLs by the service name.
        As a result, the effective URL of a route declared as `/bar` in
        the `foo` service local table will be `/api/foo/bar`. There is thus no risk of
        name clash in the case to services declare similar URLs. When building the resulting
        effective URL, care is taken to properly manage "/" at the concatenation point,
        so that the process is tolerant to the form of the local URLs (with or without
        a starting "/").

        If the service module requires some global initialization, it can be placed
        in a global reserved function named `_init_`. Although simple variables
        initialization statements can live as module level statements, all other
        processing should be placed in this `_init_` method, especially if it
        involves runtime dependencies, such as the connection with other
        services. This way, there will be no problem when importing the service
        module in contexts other than standard runtime, for instance during
        unit tests or automatic documentation generation.
        The `_init_` function is called when the module is imported during the discovery process,
        but since the order is undefined, its logic cannot rely on what is done in other
        service plugins.
        It has two keyword parameters :
            - logger : used to pass the owner service logger if defined
            - settings : used to pass the dictionary containing the content of the manifest
            "settings" section if any

        Parameters:
            home : src
                the path of the services home directory

        Result:
            a list of ServiceDescriptor
        """
        if not home:
            home = self._services_home

        self._logger.debug("discovering services stored in %s" % home)
        services = []

        # We build the services list by scanning sub-directories of the home
        # one, keeping only the ones containing the mandatory files. They are
        # then sorted by service names.
        marker_files = {MANIFEST_FILE_NAME, '__init__.py'}
        for service_name in sorted([d for d in os.listdir(home) if os.path.isdir(os.path.join(home, d))]):
            service_path = os.path.join(home, service_name)
            # next filtering could have been done in a more Pythonic way inside for loop definition,
            # but doing this explicitly provides more information in the logs in case of trouble
            self._logger.info("analysing directory %s...", service_path)
            if not marker_files.issubset(os.listdir(service_path)):
                self._logger.info("*** expected files not found => discarded")
                continue

            self._logger.info("... valid service location")
            manifest_path = os.path.join(service_path, MANIFEST_FILE_NAME)
            mf = ConfigParser.SafeConfigParser(self._services_cfg_defaults)
            mf.read(manifest_path)
            label = mf.get(MANIFEST_MAIN_SECTION, 'label')
            mapping_attr = mf.get(MANIFEST_MAIN_SECTION, 'mapping')

            module_name = '.'.join([SERVICES_PACKAGE_NAME, service_name])
            self._logger.info("... loading service '%s' from module '%s'...", service_name, module_name)
            try:
                module = importlib.import_module(module_name)
                # run the module initialization code if any
                if hasattr(module, '_init_'):
                    init_func = getattr(module, '_init_')
                    if callable(init_func):
                        self._logger.info('... invoking module _init_ function...')
                        svc_logger = self._logger.getChild(service_name)
                        svc_logger.setLevel(self._logger.getEffectiveLevel())

                        # load settings if any
                        try:
                            settings = dict(mf.items(MANIFEST_SETTINGS_SECTION))
                        except ConfigParser.NoSectionError:
                            settings = None

                        init_func(logger=svc_logger, settings=settings)
                        self._logger.info('... module _init_ OK')

                url_base = "%s/%s/" % (self._app_url_base.rstrip('/'), service_name)
                mapping = getattr(module, mapping_attr)
                # expand the URL in mappings if needed
                handlers = []
                for rule in mapping:
                    effective_url = url_base + rule[0].lstrip('/')
                    # check first if the rule is valid as a regexp
                    try:
                        re.compile(effective_url)
                    except re.error as e:
                        raise Exception('"%s" is an invalid route specification (%s)' % (effective_url, e.message))
                    else:
                        handlers.append(((effective_url,) + rule[1:]))
                services.append(ServiceDescriptor(service_name, label, handlers))
                self._logger.info(">>> success")

            except (ImportError, AttributeError) as e:
                msg = '[%s] %s' % (e.__class__.__name__, str(e))
                self._logger.exception(msg)
                raise
            except Exception as e:
                self._logger.exception(e)
                self._logger.error("*** Could not load service '%s' because of previous exception", service_name)
        return services

    class InvalidRequest(WSHandler):
        def do_get(self, *args, **kwargs):
                self.set_status(404)

        def do_post(self, *args, **kwargs):
            self.do_get()

    # built-in handlers
    toplevel_handlers = [
    ]

    fallback_handlers = [
        (r"/.*", InvalidRequest),
    ]

    def _setup_handlers(self, services):
        """ Build the effective request handlers list.

        The following logic is used :
            - initialize the list with the content of toplevel_handlers
            attribute
            - for each discovered service:
                - add the rules for the service
            - add the rules defined in fallback_handlers attribute
            - add the rule for application static resources, using res_home
            attribute for the path

        """

        handlers = self.toplevel_handlers

        for service in services:
            handlers.extend(service.handlers)

        handlers.extend(self.fallback_handlers)

        return handlers

    def _sigterm_handler(self, _signum, _frame):
        """ Handles the SIGTERM signal to gently stop the server """
        self._logger.info("SIGTERM received.")
        if self._ioloop:
            self._logger.info("stopping server loop.")
            self._ioloop.stop()

    def get_services_home(self):
        return self._services_home

    def set_services_home(self, path):
        if path == self._services_home:
            return
        if not os.path.isabs(path):
            path = os.path.abspath(os.path.join(_here, path))
        self._logger.info("services_home overridden to %s" % path)
        self._services_home = sysutils.checked_dir(path)

    services_home = property(
        get_services_home, set_services_home,
        doc="the home directory in which services are stored"
    )

    def start(self, custom_settings):
        """ Starts the configured server """
        if self._ioloop is not None:
            raise RuntimeError('server already started')

        self._logger.info("server initializing")

        # prepare the application settings dictionary
        # 1/ basic part
        settings = {
            'debug': self._debug,
        }

        # 2/  specific settings as defined in custom_settings
        if custom_settings:
            settings.update(custom_settings)

        # setup request handlers by merging the one provided by the services
        self._handlers = self._setup_handlers(self.services)
        self._logger.info("url dispatch rules:")
        for rule in self._handlers:
            pattern, handler = rule[:2]
            self._logger.info(" - %s -> %s", pattern, handler.__name__)

        settings['log_function'] = self._log_request
        self._application = tornado.web.Application(self._handlers, **settings) #pylint: disable=W0142
        self._application.app_server = self
        self._http_server = tornado.httpserver.HTTPServer(self._application)
        self._http_server.listen(self._port)
        self._logger.info("listening on port %d", self._port)

        signal.signal(signal.SIGTERM, self._sigterm_handler)

        self._ioloop = tornado.ioloop.IOLoop.instance()

        self._logger.info("web server started")
        try:
            self._ioloop.start()

        except KeyboardInterrupt:
            self._logger.info("SIGINT received.")
            self._ioloop.stop()

        self._ioloop = None
        self._logger.info("terminated")

    # custom request logging mechanism
    _muted_requests = []

    def _log_request(self, handler):
        """ Custom request logging function, allowing to mute periodic requests,
        such as notification checking for instance.

        This is needed to avoid having log files being filled by useless
        information.

        For a given request To be muted, its handler must define the attribute
        'disable_request_logging' and set it to True. When such a request is
        processed here, we log it only the first time and issue a warning to
        tell it.

        If disable_request_logging is not defined, the default logging strategy
        is applied.

        IMPORTANT:
            Only successful requests are filtered by this mechanism, all other
            ones being logged
        """
        if handler.get_status() < 400:
            key = handler.request.uri
            if key in self._muted_requests:
                return
            try:
                dont_log = handler.disable_request_logging
            except AttributeError:
                dont_log = False
            if dont_log:
                self._muted_requests.append(key)
                self._logger.warning("request '%s' is muted => last time we log it", key)
            log_method = self._logger.info

        elif handler.get_status() < 500:
            log_method = self._logger.warning

        else:
            log_method = self._logger.error

        request_time = 1000.0 * handler.request.request_time()
        log_method(
            "%d %s %.2fms", handler.get_status(),
            handler._request_summary(), request_time
        )    # pylint: disable=W0212
