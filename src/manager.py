
import dbus.service
import logging

INTERFACE_NAME = 'net.reactivated.Fprint.Manager'

class Manager(dbus.service.Object):
    def __init__(self, bus_name, device):
        dbus.service.Object.__init__(self, bus_name, '/net/reactivated/Fprint/Manager')
        self.device=device

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature="", 
                         out_signature="ao",
                         connection_keyword='connection',
                         sender_keyword='sender')
    def GetDevices(self, sender, connection):
        logging.debug("GetDevices")
        return [self.device]

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature="", 
                         out_signature="o",
                         connection_keyword='connection',
                         sender_keyword='sender')
    def GetDefaultDevice(self, sender, connection):
        logging.debug("GetDefaultDevice")
        return self.device


