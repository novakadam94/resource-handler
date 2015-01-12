#
# Copyright (C) 2014 MTA SZTAKI
#

# To avoid self-importing this boto.py module
from __future__ import absolute_import
import boto
import boto.ec2

import urlparse
import occo.util.factory as factory
from occo.util import wet_method
from ..cloudhandler import CloudHandler
import itertools as it
import logging

import drett.client as drett

__all__ = ['BotoCloudHandler']

PROTOCOL_ID='boto'

log = logging.getLogger('occo.cloudhandler.backends.boto')

@factory.register(CloudHandler, PROTOCOL_ID)
class BotoCloudHandler(CloudHandler):
    def __init__(self, target, auth_data, drett_config,
                 name=None, dry_run=False,
                 **config):
        self.dry_run = dry_run
        self.name = name if name else target['endpoint']
        self.drett_config = drett_config
        self.setup_connection(target, auth_data)
        # The following is intentional. It is a constant yet,
        # but maybe it'll change in the future.
        self.resource_type = 'vm'

    @wet_method()
    def setup_connection(self, target, auth_data):
        endpoint = target['endpoint']
        url = urlparse.urlparse(endpoint)
        region = boto.ec2.regioninfo.RegionInfo(
            name=target['regionname'], endpoint=url.hostname)
        self.conn = boto.connect_ec2(
            aws_access_key_id=auth_data['username'],
            aws_secret_access_key=auth_data['password'],
            is_secure=(url.scheme == 'https'),
            region=region,
            port=url.port,
            path=url.path)

    @wet_method(1)
    def _start_instance(self, image_id, instance_type, context):
        reservation = self.conn.run_instances(image_id=image_id,
                                              instance_type=instance_type)
        return reservation.instances[0].id

    @wet_method()
    def _delete_vms(self, *vm_ids):
        self.conn.terminate_instances(instance_ids=vm_ids)

    @wet_method('occo-dummy-state')
    def _get_status(self, vm_id):
        reservations = self.conn.get_all_reservations(instance_ids=[vm_id])
        # TODO: ASSUMING len(reservations)==1 and len(instances)==1
        instance = reservations[0].instances[0]
        return instance.state

    def create_node(self, node_description):
        log.debug("[%s] Creating node: %r", self.name, node_description)
        image_id = node_description['image_id']
        instance_type = node_description['instance_type']
        context = node_description['context']

        with drett.Allocation(resource_owner=self.name,
                              resource_type=self.resource_type,
                              **self.drett_config) as a:
            vm_id = self._start_instance(image_id, instance_type, context)
            a.set_resource_data(vm_id)

        log.debug("[%s] Done; vm_id = %r", self.name, vm_id)
        return vm_id

    def drop_node(self, instance_data):
        node_id = instance_data['node_id']
        log.debug("[%s] Dropping node '%s'", self.name, node_id)

        self._delete_vms(node_id)

        drett \
            .ResourceTracker(url=self.drett_config['url']) \
            .resource_freed_by_attributes(resource_owner=self.name,
                                          resource_type=self.resource_type,
                                          resource_id=node_id)

        log.debug("[%s] Done", self.name)

    def get_node_state(self, instance_data):
        node_id = instance_data['node_id']
        log.debug("[%s] Acquiring node state for '%s'", self.name, node_id)
        retval = self._get_status(node_id)
        log.debug("[%s] Done; retval='%s'", self.name, retval)
        return retval
