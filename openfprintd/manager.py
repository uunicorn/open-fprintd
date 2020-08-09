import logging
import typing

import dbus.service

from openfprintd.device import Device

INTERFACE_NAME = 'net.reactivated.Fprint.Manager'


class NoSuchDevice(dbus.DBusException):
    _dbus_error_name = 'net.reactivated.Fprint.Error.NoSuchDevice'


class Manager(dbus.service.Object):
    def __init__(self, bus_name):
        dbus.service.Object.__init__(self, bus_name, '/net/reactivated/Fprint/Manager')
        self.bus_name = bus_name
        self.devices: typing.List[Device] = []

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='',
                         out_signature='ao',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def GetDevices(self, sender, connection):
        logging.debug("GetDevices")
        return self.devices

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='',
                         out_signature='o',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def GetDefaultDevice(self, sender, connection):
        logging.debug("GetDefaultDevice")

        if len(self.devices) == 0:
            raise NoSuchDevice()

        return self.devices[0]

    # TODO: use a different interface name for this
    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='o',
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def RegisterDevice(self, dev, sender, connection):
        # TODO: polkit: make sure we're talking to a root process!
        logging.debug('RegisterDevice')

        # TODO: don't ignore dev parameter.
        # For now, one bus name may have only one device with a well known path
        wrap = Device(self.bus_name, sender)
        self.devices += [wrap]

        watcher = None

        def watch_cb(name):
            if name == '':
                logging.debug('%s went offline' % sender)
                self.devices.remove(wrap)
                wrap.remove_from_connection()
                watcher.cancel()

        watcher = connection.watch_name_owner(sender, watch_cb)
