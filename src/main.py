
import dbus
import dbus.mainloop.glib
import dbus.service
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
from gi.repository import GObject
import logging

from manager import Manager
from device import Device

logging.basicConfig(level=logging.DEBUG)

bus_name = dbus.service.BusName('net.reactivated.Fprint', dbus.SystemBus())
device = Device(bus_name, 'io.github.uunicorn.Fprint', '/io/github/uunicorn/Fprint/Device')
server = Manager(bus_name, device)

logging.debug('Looping...')
GObject.MainLoop().run()

