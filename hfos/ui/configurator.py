#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# HFOS - Hackerfleet Operating System
# ===================================
# Copyright (C) 2011-2017 Heiko 'riot' Weinen <riot@c-base.org> and others.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__author__ = "Heiko 'riot' Weinen"
__license__ = "GPLv3"

"""

Module: Configurator
=====================


"""

from hfos.events.client import send
from hfos.component import ConfigurableComponent, authorizedevent, handler
from hfos.schemata.component import ComponentConfigSchemaTemplate as Schema
from hfos.database import configschemastore, ValidationError, objectmodels
from hfos.logger import error, warn, verbose, hilight
from warmongo import model_factory

try:
    PermissionError
except NameError:  # pragma: no cover
    class PermissionError(Exception):
        pass


class list(authorizedevent):
    """A client requires a schema to validate data or display a form"""


class get(authorizedevent):
    """A client requires a schema to validate data or display a form"""


class put(authorizedevent):
    """A client requires a schema to validate data or display a form"""


class Configurator(ConfigurableComponent):
    """
    Provides a common configuration interface for all HFOS components.

    (You're probably looking at it right now)
    """

    channel = "hfosweb"

    configprops = {}

    def __init__(self, *args):
        super(Configurator, self).__init__('CONF', *args)

    def _check_permission(self, event):
        account = event.user.account

        if 'admin' not in account.roles:
            self.log('Missing permission to configure components',
                     lvl=warn)

            return False
        return True

    @handler(list)
    def list(self, event):
        """Processes configuration list requests

        :param event:
        """

        try:

            componentlist = model_factory(Schema).find({})
            data = []
            for comp in componentlist:
                data.append({
                    'name': comp.name,
                    'uuid': comp.uuid,
                    'class': comp.componentclass,
                    'active': comp.active
                })

            data = sorted(data, key=lambda x: x['name'])

            response = {
                'component': 'hfos.ui.configurator',
                'action': 'list',
                'data': data
            }
            self.fireEvent(send(event.client.uuid, response))
            return
        except Exception as e:
            self.log("List error: ", e, type(e), lvl=error, exc=True)

    @handler(put)
    def put(self, event):
        self.log("Configuration put request ",
                 event.user)

        try:
            if self._check_permission(event) is False:
                raise PermissionError

            component = model_factory(Schema).find_one({
                'uuid': event.data['uuid']
            })

            component.update(event.data)
            component.save()

            response = {
                'component': 'hfos.ui.configurator',
                'action': 'put',
                'data': True
            }
            self.log('Updated component configuration:',
                     component.name)
        except (KeyError, ValueError, ValidationError, PermissionError) as e:
            response = {
                'component': 'hfos.ui.configurator',
                'action': 'put',
                'data': False
            }
            self.log('Storing component configuration failed: ',
                     type(e), e, exc=True, lvl=error)

        self.fireEvent(send(event.client.uuid, response))
        return

    @handler(get)
    def get(self, event):
        if self._check_permission(event) is False:
            response = {
                'component': 'hfos.ui.configurator',
                'action': 'get',
                'data': False
            }
            self.log('No permission to access configuration', event.user,
                     lvl=warn)

            self.fireEvent(send(event.client.uuid, response))
            return

        try:
            comp = event.data['uuid']
        except KeyError:
            comp = None

        if not comp:
            self.log('Invalid get request without schema or component',
                     lvl=error)
            return

        self.log("Config data get  request for ", event.data, "from",
                 event.user)

        component = model_factory(Schema).find_one({
            'uuid': comp
        })
        response = {
            'component': 'hfos.ui.configurator',
            'action': 'get',
            'data': component.serializablefields()
        }
        self.fireEvent(send(event.client.uuid, response))
