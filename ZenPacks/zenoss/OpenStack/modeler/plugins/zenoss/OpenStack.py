###########################################################################
#
# This program is part of Zenoss Core, an open source monitoring platform.
# Copyright (C) 2011, Zenoss Inc.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 or (at your
# option) any later version as published by the Free Software Foundation.
#
# For complete information please visit: http://www.zenoss.com/oss/
#
###########################################################################

import logging
log = logging.getLogger('zen.OpenStack')

import types

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap

from ZenPacks.zenoss.OpenStack.util import addLocalLibPath
addLocalLibPath()

import novaclient
from novaclient.v1_0.client import Client as v1_0_Client
from novaclient.v1_1.client import Client as v1_1_Client


class OpenStack(PythonPlugin):
    deviceProperties = PythonPlugin.deviceProperties + (
        'zCommandUsername',
        'zCommandPassword',
        'zOpenStackProjectId',
        'zOpenStackAuthUrl',
        'zOpenStackRegionName',
    )

    def collect(self, device, unused):
        client_class = None
        if 'v1.1' in device.zOpenStackAuthUrl:
            client_class = v1_1_Client
        else:
            client_class = v1_0_Client

        region_name = None
        if device.zOpenStackRegionName:
            region_name = device.zOpenStackRegionName

        client = client_class(
            device.zCommandUsername,
            device.zCommandPassword,
            device.zOpenStackProjectId,
            device.zOpenStackAuthUrl,
            region_name=region_name)

        results = {}

        log.info('Requesting flavors')
        results['flavors'] = client.flavors.list()

        log.info('Requesting images')
        results['images'] = client.images.list()

        log.info('Requesting servers')
        results['servers'] = client.servers.list()

        return results

    def process(self, devices, results, unused):
        flavors = []
        for flavor in results['flavors']:
            flavors.append(ObjectMap(data=dict(
                id='flavor{0}'.format(flavor.id),
                title=flavor.name,  # 256 server
                flavorId=int(flavor.id),  # 1
                flavorRAM=flavor.ram * 1024 * 1024,  # 256
                flavorDisk=flavor.disk * 1024 * 1024 * 1024,  # 10
            )))

        flavorsMap = RelationshipMap(
            relname='flavors',
            modname='ZenPacks.zenoss.OpenStack.Flavor',
            objmaps=flavors)

        images = []
        for image in results['images']:
            # Sometimes there's no created timestamp for an image.
            created = getattr(image, 'created', '')

            images.append(ObjectMap(data=dict(
                id='image{0}'.format(image.id),
                title=image.name,  # Red Hat Enterprise Linux 5.5
                imageId=int(image.id),  # 55
                imageStatus=image.status,  # ACTIVE
                imageCreated=created,  # 2010-09-17T07:19:20-05:00
                imageUpdated=image.updated,  # 2010-09-17T07:19:20-05:00
            )))

        imagesMap = RelationshipMap(
            relname='images',
            modname='ZenPacks.zenoss.OpenStack.Image',
            objmaps=images)

        servers = []
        for server in results['servers']:
            # Backup support is optional. Guard against it not existing.
            backup_schedule_enabled = None
            backup_schedule_daily = None
            backup_schedule_weekly = None

            try:
                backup_schedule_enabled = server.backup_schedule.enabled
                backup_schedule_daily = server.backup_schedule.daily
                backup_schedule_weekly = server.backup_schedule.weekly
            except (novaclient.exceptions.NotFound, AttributeError):
                backup_schedule_enabled = False
                backup_schedule_daily = 'DISABLED'
                backup_schedule_weekly = 'DISABLED'

            # The methods for accessing a server's IP addresses have changed a
            # lot. We'll try as many as we know.
            public_ips = set()
            private_ips = set()

            if hasattr(server, 'public_ip') and server.public_ip:
                if isinstance(server.public_ip, types.StringTypes):
                    public_ips.add(server.public_ip)
                elif isinstance(server.public_ip, types.ListType):
                    public_ips.update(server.public_ip)

            if hasattr(server, 'private_ip') and server.private_ip:
                if isinstance(server.private_ip, types.StringTypes):
                    private_ips.add(server.private_ip)
                elif isinstance(server.private_ip, types.ListType):
                    private_ips.update(server.private_ip)

            if hasattr(server, 'accessIPv4') and server.accessIPv4:
                public_ips.add(server.accessIPv4)

            if hasattr(server, 'accessIPv6') and server.accessIPv6:
                public_ips.add(server.accessIPv6)

            if hasattr(server, 'addresses') and server.addresses:
                for network_name, addresses in server.addresses.items():
                    for address in addresses:
                        if 'public' in network_name.lower():
                            if isinstance(address, types.DictionaryType):
                                public_ips.add(address['addr'])
                            elif isinstance(address, types.StringTypes):
                                public_ips.add(address)
                        else:
                            if isinstance(address, types.DictionaryType):
                                private_ips.add(address['addr'])
                            elif isinstance(address, types.StringTypes):
                                private_ips.add(address)

            # Flavor and Image IDs could be specified two different ways.
            flavor_id = None
            if hasattr(server, 'flavorId'):
                flavor_id = int(server.flavorId)
            else:
                flavor_id = int(server.flavor['id'])

            image_id = None
            if hasattr(server, 'imageId'):
                image_id = int(server.imageId)
            else:
                image_id = int(server.image['id'])

            servers.append(ObjectMap(data=dict(
                id='server{0}'.format(server.id),
                title=server.name,  # cloudserver01
                serverId=server.id,  # 847424
                serverStatus=server.status,  # ACTIVE
                serverBackupEnabled=backup_schedule_enabled,  # False
                serverBackupDaily=backup_schedule_daily,  # DISABLED
                serverBackupWeekly=backup_schedule_weekly,  # DISABLED
                publicIps=list(public_ips),  # 50.57.74.222
                privateIps=list(private_ips),  # 10.182.13.13
                setFlavorId=flavor_id,  # 1
                setImageId=image_id,  # 55

                # a84303c0021aa53c7e749cbbbfac265f
                hostId=server.hostId,
            )))

        serversMap = RelationshipMap(
            relname='servers',
            modname='ZenPacks.zenoss.OpenStack.Server',
            objmaps=servers)

        return (flavorsMap, imagesMap, serversMap)
