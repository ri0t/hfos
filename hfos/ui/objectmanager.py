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

Module: OM
==========

OM manager


"""

from uuid import uuid4

from hfos.events.objectmanager import objectcreation, objectchange, \
    objectdeletion, list, search, get, change, put, delete, subscribe, \
    unsubscribe
from hfos.events.client import send
from hfos.component import handler, ConfigurableComponent
from hfos.database import objectmodels, ValidationError, schemastore
from hfos.logger import verbose, debug, error, warn, critical, hilight

from pprint import pprint

WARNSIZE = 500


class ObjectManager(ConfigurableComponent):
    """
    Handles object requests and updates.
    """

    channel = "hfosweb"

    configprops = {}

    def __init__(self, *args):
        super(ObjectManager, self).__init__('OM', *args)

        self.subscriptions = {}

        self.log("Started")

    def _check_permissions(self, subject, action, obj):
        self.log('Roles of user:', subject.account.roles, lvl=verbose)

        if 'perms' not in obj._fields:
            if 'admin' in subject.account.roles:
                self.log('Access to administrative object granted',
                         lvl=verbose)
                return True
            else:
                self.log('Access to administrative object failed',
                         lvl=verbose)
                return False

        if 'owner' in obj.perms[action]:
            try:
                if subject.uuid == obj.owner:
                    self.log('Access granted via ownership', lvl=verbose)
                    return True
            except AttributeError as e:
                self.log('Schema has ownership permission but no owner:',
                         obj._schema['name'], obj._fields, e, type(e),
                         lvl=warn, exc=True)
        for role in subject.account.roles:
            if role in obj.perms[action]:
                self.log('Access granted', lvl=verbose)
                return True

        self.log('Access denied', lvl=verbose)
        return False

    def _check_create_permission(self, subject, schema):
        for role in subject.account.roles:
            if role in schemastore[schema]['schema']['roles_create']:
                return True
        return False

    def _cancel_by_permission(self, schema, data, client):
        self.log('No permission:', schema, data, client.useruuid,
                 lvl=error)

        msg = {
            'component': 'hfos.events.objectmanager',
            'action': 'fail',
            'data': {
                'reason': 'No permission',
                'data': data,
                'req': data.get('req')
            }
        }
        self.fire(send(client.uuid, msg))

    def _cancel_by_error(self, event, reason="malformed"):
        self.log('Bad request:', reason, lvl=error)

        msg = {
            'component': 'hfos.events.objectmanager',
            'action': 'fail',
            'data': {
                'reason': reason,
                'req': event.data.get('req', None)
            }
        }
        self.fire(send(event.client.uuid, msg))

    def _get_schema(self, event):
        try:
            data = event.data
        except AttributeError:
            return

        if 'schema' not in data or data['schema'] not in \
                objectmodels.keys():
            self._cancel_by_error(event, 'invalid_schema')
            return
        else:
            schema = data['schema']

        return schema

    def _get_filter(self, event):
        data = event.data
        if 'filter' in data:
            object_filter = data['filter']
        else:
            object_filter = {}

        return object_filter

    def _get_args(self, event):
        data = event.data
        schema = self._get_schema(event)
        user = event.user
        client = event.client

        return data, schema, user, client

    def _respond(self, notification, result, event):
        if notification:
            try:
                self.log('Firing notification', lvl=verbose)
                self.fireEvent(notification)
            except Exception as e:
                self.log("Transmission error during notification: %s" % e,
                         lvl=error)

        if result:
            try:
                self.log('Transmitting result', lvl=verbose)
                if isinstance(event.data, dict):
                    result['data']['req'] = event.data.get('req', None)
                self.fireEvent(send(event.client.uuid, result))
            except Exception as e:
                self.log("Transmission error during response: %s" % e,
                         lvl=error, exc=True)

    @handler(get)
    def get(self, event):
        try:
            data, schema, user, client = self._get_args(event)
        except AttributeError:
            self._cancel_by_error(event)
            return

        object_filter = self._get_filter(event)

        if 'subscribe' in data:
            do_subscribe = data['subscribe'] is True
        else:
            do_subscribe = False

        try:
            uuid = str(data['uuid'])
        except (KeyError, TypeError):
            uuid = ""

        opts = schemastore[schema].get('options', {})
        hidden = opts.get('hidden', [])

        if object_filter == {}:
            if uuid == "":
                self.log('Object with no filter/uuid requested:', schema,
                         data,
                         lvl=warn)
                return
            object_filter = {'uuid': uuid}

        storage_object = None
        storage_object = objectmodels[schema].find_one(object_filter)

        if not storage_object:
            self._cancel_by_error(event, uuid + ' of ' + schema +
                                  'unavailable')
            return

        if storage_object:
            self.log("Object found, checking permissions: ", data, lvl=debug)

            if not self._check_permissions(user, 'read',
                                           storage_object):
                self._cancel_by_permission(schema, data, event.client)
                return

            for field in hidden:
                storage_object._fields.pop(field, None)

            if do_subscribe and uuid != "":
                self._add_subscription(uuid, event)

            result = {
                'component': 'hfos.events.objectmanager',
                'action': 'get',
                'data': {
                    'schema': schema,
                    'uuid': uuid,
                    'object': storage_object.serializablefields()
                }
            }

        self._respond(None, result, event)

    @handler(search)
    def search(self, event):
        try:
            data, schema, user, client = self._get_args(event)
        except AttributeError:
            self._cancel_by_error(event)
            return

        # object_filter['$text'] = {'$search': str(data['search'])}
        if 'fulltext' in data:
            object_filter = {
                'name': {
                    '$regex': str(data['search']),
                    '$options': '$i'
                }
            }
        else:
            if isinstance(data['search'], dict):
                object_filter = data['search']
            else:
                object_filter = {}

        if 'fields' in data:
            fields = data['fields']
        else:
            fields = []

        object_list = []

        if objectmodels[schema].count() > WARNSIZE:
            self.log("Getting a very long list of items for ", schema,
                     lvl=warn)

        opts = schemastore[schema].get('options', {})
        hidden = opts.get('hidden', [])

        self.log("object_filter: ", object_filter, ' Schema: ', schema,
                 "Fields: ", fields,
                 lvl=verbose)

        for item in objectmodels[schema].find(object_filter):
            if not self._check_permissions(user, 'list', item):
                continue
            self.log("Search found item: ", item, lvl=verbose)

            try:
                list_item = {'uuid': item.uuid}
                if fields in ('*', ['*']):
                    item_fields = item.serializablefields()
                    for field in hidden:
                        item_fields.pop(field, None)
                    object_list.append(item_fields)
                else:
                    if 'name' in item._fields:
                        list_item['name'] = item.name

                    for field in fields:
                        if field in item._fields and field not in \
                                hidden:
                            list_item[field] = item._fields[field]
                        else:
                            list_item[field] = None

                    object_list.append(list_item)
            except Exception as e:
                self.log("Faulty object or field: ", e, type(e),
                         item._fields, fields, lvl=error, exc=True)
        # self.log("Generated object search list: ", object_list)

        result = {
            'component': 'hfos.events.objectmanager',
            'action': 'search',
            'data': {
                'schema': schema,
                'list': object_list,
            }
        }

        self._respond(None, result, event)

    @handler(list)
    def objectlist(self, event):
        self.log('LEGACY LIST FUNCTION CALLED!', lvl=warn)
        try:
            data, schema, user, client = self._get_args(event)
        except AttributeError:
            self._cancel_by_error(event)
            return

        object_filter = self._get_filter(event)
        self.log('Object list for', schema, 'requested from',
                 user.account.name, lvl=debug)

        if 'fields' in data:
            fields = data['fields']
        else:
            fields = []

        object_list = []

        opts = schemastore[schema].get('options', {})
        hidden = opts.get('hidden', [])

        if objectmodels[schema].count(object_filter) > WARNSIZE:
            self.log("Getting a very long list of items for ", schema,
                     lvl=warn)

        try:
            for item in objectmodels[schema].find(object_filter):
                try:
                    if not self._check_permissions(user, 'list', item):
                        continue
                    if fields in ('*', ['*']):
                        item_fields = item.serializablefields()
                        for field in hidden:
                            item_fields.pop(field, None)
                        object_list.append(item_fields)
                    else:
                        list_item = {'uuid': item.uuid}

                        if 'name' in item._fields:
                            list_item['name'] = item._fields['name']

                        for field in fields:
                            if field in item._fields and field not in hidden:
                                list_item[field] = item._fields[field]
                            else:
                                list_item[field] = None

                        object_list.append(list_item)
                except Exception as e:
                    self.log("Faulty object or field: ", e, type(e),
                             item._fields, fields, lvl=error, exc=True)
        except ValidationError as e:
            self.log('Invalid object in database encountered!', e, exc=True,
                     lvl=warn)
        # self.log("Generated object list: ", object_list)

        result = {
            'component': 'hfos.events.objectmanager',
            'action': 'list',
            'data': {
                'schema': schema,
                'list': object_list
            }
        }

        self._respond(None, result, event)

    @handler(change)
    def change(self, event):
        try:
            data, schema, user, client = self._get_args(event)
        except AttributeError:
            self._cancel_by_error(event, 'missing_args')
            return

        try:
            uuid = data['uuid']
            change = data['change']
            field = change['field']
            new_data = change['value']
        except KeyError as e:
            self.log("Update request with missing arguments!", data, e,
                     lvl=critical)
            self._cancel_by_error(event, 'missing_args')
            return

        storage_object = None

        try:
            storage_object = objectmodels[schema].find_one({'uuid': uuid})
        except Exception as e:
            self.log('Change for unknown object requested:', schema,
                     data, lvl=warn)
            self._cancel_by_error(event, 'not_found')
            return

        if not self._check_permissions(user, 'write', storage_object):
            self._cancel_by_permission(schema, data, client)
            return

        self.log("Changing object:", storage_object._fields, lvl=debug)
        storage_object._fields[field] = new_data

        self.log("Storing object:", storage_object._fields, lvl=debug)
        try:
            storage_object.validate()
        except ValidationError:
            self.log("Validation of changed object failed!",
                     storage_object, lvl=warn)
            self._cancel_by_error('invalid_object')
            return

        storage_object.save()

        self.log("Object stored.")

        result = {
            'component': 'hfos.ui.objectmanager',
            'action': 'change',
            'data': {
                'schema': schema,
                'uuid': uuid
            }
        }

        self._respond(None, result, event)

    @handler(put)
    def put(self, event):
        try:
            data, schema, user, client = self._get_args(event)
        except AttributeError:
            self._cancel_by_error(event)
            return

        try:
            clientobject = data['obj']
            uuid = clientobject['uuid']
        except KeyError as e:
            self.log("Put request with missing arguments!", e, data,
                     lvl=critical)
            return

        try:
            model = objectmodels[schema]

            if uuid != 'create':
                storage_object = model.find_one({'uuid': uuid})
            if uuid == 'create' or model.count({
                'uuid': uuid
            }) == 0:
                if uuid == 'create':
                    uuid = str(uuid4())
                clientobject['uuid'] = uuid
                clientobject['owner'] = user.uuid
                storage_object = model(clientobject)
                if not self._check_create_permission(user, schema):
                    self._cancel_by_permission(schema, data, client)
                    return

            if storage_object:
                if not self._check_permissions(user, 'write', storage_object):
                    self._cancel_by_permission(schema, data, client)
                    return

                self.log("Updating object:", storage_object._fields, lvl=debug)
                storage_object.update(clientobject)

            else:
                storage_object = model(clientobject)
                if not self._check_permissions(user, 'write', storage_object):
                    self._cancel_by_permission(schema, data, client)
                    return

                self.log("Storing object:", storage_object._fields, lvl=debug)
                try:
                    storage_object.validate()
                except ValidationError:
                    self.log("Validation of new object failed!", clientobject,
                             lvl=warn)

            storage_object.save()

            self.log("Object stored.")

            # Notify backend listeners

            if uuid == 'create':
                notification = objectcreation(storage_object.uuid, schema,
                                              client)
            else:
                notification = objectchange(storage_object.uuid, schema,
                                            client)

            self._update_subscribers(storage_object)

            result = {
                'component': 'hfos.events.objectmanager',
                'action': 'put',
                'data': {
                    'schema': schema,
                    'object': storage_object.serializablefields(),
                    'uuid': storage_object.uuid,
                }
            }

            self._respond(notification, result, event)

        except Exception as e:
            self.log("Error during object storage:", e, type(e), data,
                     lvl=error, exc=True, pretty=True)

    @handler(delete)
    def delete(self, event):
        try:
            data, schema, user, client = self._get_args(event)
        except AttributeError:
            self._cancel_by_error(event)
            return

        try:
            uuid = data['uuid']

            if schema in objectmodels.keys():
                self.log("Looking for object to be deleted:", uuid, lvl=debug)
                storage_object = objectmodels[schema].find_one({'uuid': uuid})

                if not storage_object:
                    self._cancel_by_error(event, 'not found')
                    return

                self.log("Found object.", lvl=debug)

                if not self._check_permissions(user, 'write', storage_object):
                    self._cancel_by_permission(schema, data, client)
                    return

                self.log("Fields:", storage_object._fields, "\n\n\n",
                         storage_object.__dict__)
                storage_object.delete()

                self.log("Preparing notification.", lvl=debug)
                notification = objectdeletion(uuid, schema, client)

                if uuid in self.subscriptions:
                    deletion = {
                        'component': 'hfos.events.objectmanager',
                        'action': 'deletion',
                        'data': {
                            'schema': schema,
                            'uuid': uuid,
                        }
                    }
                    for recipient in self.subscriptions[uuid]:
                        self.fireEvent(send(recipient, deletion))

                    del (self.subscriptions[uuid])

                result = {
                    'component': 'hfos.events.objectmanager',
                    'action': 'delete',
                    'data': {
                        'schema': schema,
                        'uuid': storage_object.uuid
                    }
                }

                self._respond(notification, result, event)
            else:
                self.log("Unknown schema encountered: ", schema, lvl=warn)
        except Exception as e:
            self.log("Error during delete request: ", e, type(e),
                     lvl=error)

    @handler(subscribe)
    def subscribe(self, event):
        uuid = event.data

        self._add_subscription(uuid, event)
        result = {
            'component': 'hfos.events.objectmanager',
            'action': 'subscribe',
            'data': {
                'uuid': uuid, 'success': True
            }
        }
        self._respond(None, result, event)

    def _add_subscription(self, uuid, event):
        self.log('Adding subscription for', uuid, event.user, lvl=debug)
        if uuid in self.subscriptions:
            if event.client.uuid not in self.subscriptions[uuid]:
                self.subscriptions[uuid][event.client.uuid] = event.user
        else:
            self.subscriptions[uuid] = {event.client.uuid: event.user}

    @handler(unsubscribe)
    def unsubscribe(self, event):
        # TODO: Automatic Unsubscription
        uuid = event.data

        if uuid in self.subscriptions:
            self.subscriptions[uuid].pop(event.client.uuid)

            if len(self.subscriptions[uuid]) == 0:
                del (self.subscriptions[uuid])

        result = {
            'component': 'hfos.events.objectmanager',
            'action': 'unsubscribe',
            'data': {
                'uuid': uuid, 'success': True
            }
        }

        self._respond(None, result, event)

    def update_subscriptions(self, event):
        """OM event handler for to be stored and client shared objectmodels
        :param event: OMRequest with uuid, schema and object data
        """

        self.log("Event: '%s'" % event.__dict__)
        try:
            data = event.data
            self._update_subscribers(data)

        except Exception as e:
            self.log("Error during subscription update: ", type(e), e,
                     exc=True)

    def _update_subscribers(self, update_object):
        # Notify frontend subscribers

        self.log('Notifying subscribers about update.', lvl=debug)
        if update_object.uuid in self.subscriptions:
            update = {
                'component': 'hfos.events.objectmanager',
                'action': 'update',
                'data': update_object.serializablefields()
            }

            # pprint(self.subscriptions)

            for client, recipient in self.subscriptions[
                update_object.uuid
            ].items():
                if not self._check_permissions(recipient, 'read',
                                               update_object):
                    continue

                self.log('Notifying subscriber: ', client, recipient,
                         lvl=verbose)
                self.fireEvent(send(client, update))
