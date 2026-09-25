
import dbus
import dbus.service
import logging
import pwd
from gi.repository import GLib


INTERFACE_NAME = 'net.reactivated.Fprint.Device'
TARGET_INTERFACE_NAME = 'io.github.uunicorn.Fprint.Device'

# fprintd's device properties: D-Bus type, and the value used when the backend
# doesn't supply one.
PROPS = {
    'name': (dbus.String, 'DBus driver'),
    'num-enroll-stages': (dbus.Int32, 5),
    'scan-type': (dbus.String, 'press'),
    'finger-present': (dbus.Boolean, False),
    'finger-needed': (dbus.Boolean, False),
}

class AlreadyInUse(dbus.DBusException):
    _dbus_error_name = 'net.reactivated.Fprint.Error.AlreadyInUse'

    def __init__(self):
        super().__init__('Device is already in use')

class ClaimDevice(dbus.DBusException):
    _dbus_error_name = 'net.reactivated.Fprint.Error.ClaimDevice'

    def __init__(self):
        super().__init__('Client must claim device first')

class PermissionDenied(dbus.DBusException):
    _dbus_error_name = 'net.reactivated.Fprint.Error.PermissionDenied'

    def __init__(self):
        super().__init__('Permission denied')

class Device(dbus.service.Object):
    cnt=0

    def __init__(self, mgr):
        self.manager = mgr
        bus_name = mgr.bus_name
        dbus.service.Object.__init__(self, bus_name, '/net/reactivated/Fprint/Device/%d' % Device.cnt)
        Device.cnt += 1
        self.bus = bus_name.get_bus()
        self.target = None
        self.target_props = dbus.Dictionary(
                { k: t(v) for k, (t, v) in PROPS.items() }, signature='sv')
        self.owner_watcher = None
        self.claimed_by = None
        self.claim_sender = None
        self.busy = False

        self.suspended = False
        self.callbacks = []

    def proxy_call(self, cb):
        if self.suspended or self.target is None:
            logging.debug('The service is suspended / offline, delay the call')
            self.callbacks += [cb]
        else:
            cb()


    def call_cbs(self):
        for cb in self.callbacks:
            try:
                cb()
            except Exception as e:
                logging.debug('callback resulted in error: %s' % repr(e))

        logging.debug('Callbacks complete')

        self.suspended = False
        self.callbacks = []

    def set_target(self, target_name, sender):
        obj = self.bus.get_object(sender, target_name, introspect=False)
        self.target = dbus.Interface(obj, TARGET_INTERFACE_NAME)
        self.target.connect_to_signal('VerifyStatus', self.VerifyStatus)
        self.target.connect_to_signal('VerifyFingerSelected', self.VerifyFingerSelected)
        self.target.connect_to_signal('EnrollStatus', self.EnrollStatus)

        # A backend can describe the device (e.g. its number of enroll stages)
        # through org.freedesktop.DBus.Properties on its own interface. Ask
        # asynchronously: the backend may be blocked in RegisterDevice.
        dbus.Interface(obj, dbus.PROPERTIES_IFACE).GetAll(
                TARGET_INTERFACE_NAME,
                reply_handler=lambda props: self.update_props(props, reset=True),
                error_handler=self.no_target_props)
        # ...and update them, e.g. finger-needed while it waits for a touch.
        obj.connect_to_signal('PropertiesChanged', self.target_props_changed,
                              dbus_interface=dbus.PROPERTIES_IFACE)

        watcher = None
        def watch_cb(name):
            if name == '':
                logging.debug('%s went offline' % sender)
                self.unset_target()
                #self.remove_from_connection()
                watcher.cancel()
        watcher = self.connection.watch_name_owner(sender, watch_cb)

        # We called from RegisterDeivce DBus method. 
        # Calling device methods from here will cause a deadlock.
        # Postpone processing till RegisterDeivce method is finished.

        def process_offline():
            if not self.suspended:
                self.call_cbs()

        GLib.idle_add(process_offline)

    def unset_target(self):
        self.target = None
        self.clear_finger()

    def no_target_props(self, e):
        logging.debug('Backend has no properties (%s), using defaults' % e.get_dbus_name())
        self.update_props({}, reset=True)

    def target_props_changed(self, interface, changed, invalidated):
        if interface == TARGET_INTERFACE_NAME:
            self.update_props(changed)

    def clear_finger(self):
        # Nothing waits for a finger once the operation is over, whether or
        # not the backend said so.
        self.update_props({ 'finger-present': False, 'finger-needed': False })

    def update_props(self, props, reset=False):
        new = dict(self.target_props)
        if reset:
            new.update({ k: t(v) for k, (t, v) in PROPS.items() })

        for k, v in props.items():
            if k not in PROPS:
                logging.debug('Ignoring unknown backend property %s' % k)
                continue
            try:
                new[k] = PROPS[k][0](v)
            except (TypeError, ValueError):
                logging.warning('Ignoring bad value for backend property %s: %r' % (k, v))

        changed = { k: v for k, v in new.items() if self.target_props.get(k) != v }
        self.target_props = dbus.Dictionary(new, signature='sv')

        if changed:
            logging.debug('Properties changed: %r' % changed)
            self.PropertiesChanged(INTERFACE_NAME,
                                   dbus.Dictionary(changed, signature='sv'),
                                   dbus.Array([], signature='s'))

    def Resume(self):
        self.suspended = False

        if self.target is not None:
            self.target.Resume()

            self.call_cbs()

    def Suspend(self):
        self.suspended = True

        if self.target is not None:
            self.target.Suspend()

    # ------------------ Template Database --------------------------

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature="s", 
                         out_signature="as",
                         connection_keyword='connection',
                         sender_keyword='sender',
                         async_callbacks=('callback', 'errback'))
    def ListEnrolledFingers(self, username, sender, connection, callback, errback):
        logging.debug('ListEnrolledFingers')

        if username is None or username == '':
            uid=self.bus.get_unix_user(sender)
            pw=pwd.getpwuid(uid)
            username=pw.pw_name

        def cb():
            callback(self.target.ListEnrolledFingers(username, signature='s'))

        self.proxy_call(cb)

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='s', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def DeleteEnrolledFingers(self, username, sender, connection):
        logging.debug('DeleteEnrolledFingers: %s' % username)

        uid = self.bus.get_unix_user(sender)
        pw = pwd.getpwuid(uid)
        if username is None or len(username) == 0:
            username = pw.pw_name
        elif username != pw.pw_name and uid != 0:
            raise PermissionDenied()

        return self.target.DeleteEnrolledFingers(username, signature='s')

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def DeleteEnrolledFingers2(self, sender, connection):
        logging.debug('DeleteEnrolledFingers2')

        if self.owner_watcher is None or self.claim_sender != sender:
            raise ClaimDevice()

        return self.target.DeleteEnrolledFingers(self.claimed_by, signature='s')

    # ------------------ Claim/Release --------------------------

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='s', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def Claim(self, username, sender, connection):
        logging.debug('Claim')

        uid=self.bus.get_unix_user(sender)
        pw=pwd.getpwuid(uid)
        if username is None or len(username) == 0:
            username = pw.pw_name
        elif username != pw.pw_name and uid != 0:
            raise PermissionDenied()

        if self.owner_watcher is not None:
            raise AlreadyInUse()

        def watch_cb(x):
            if x == '':
                self.do_release()

        self.owner_watcher = self.connection.watch_name_owner(sender, watch_cb)
        self.claimed_by = username
        self.claim_sender = sender

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def Release(self, sender, connection):
        logging.debug('Release')

        if self.owner_watcher is None or self.claim_sender != sender:
            raise ClaimDevice()
        
        self.do_release()

    def do_release(self):
        logging.debug('do_release')
        self.claimed_by = None
        self.claim_sender = None

        if self.owner_watcher is not None:
            self.owner_watcher.cancel()
            self.owner_watcher = None

        if self.busy:
            self.target.Cancel(signature='')
            self.busy = False
            self.clear_finger()

    # ------------------ Verify --------------------------

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='s', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def VerifyStart(self, finger_name, sender, connection):
        logging.debug('VerifyStart')

        if self.owner_watcher is None or self.claim_sender != sender:
            raise ClaimDevice()

        self.busy = True
        return self.target.VerifyStart(self.claimed_by, finger_name, signature='ss')


    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def VerifyStop(self, sender, connection):
        logging.debug('VerifyStop')

        if self.owner_watcher is None or self.claim_sender != sender:
            raise ClaimDevice()
        
        self.busy = False
        self.target.Cancel(signature='')
        self.clear_finger()

    @dbus.service.signal(dbus_interface=INTERFACE_NAME, signature='s')
    def VerifyFingerSelected(self, finger):
        logging.debug('VerifyFingerSelected')

    @dbus.service.signal(dbus_interface=INTERFACE_NAME, signature='sb')
    def VerifyStatus(self, result, done):
        logging.debug('VerifyStatus')
        if done:
            self.busy = False
            self.clear_finger()

    # ------------------ Enroll --------------------------

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='s', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def EnrollStart(self, finger_name, sender, connection):
        logging.debug('EnrollStart')

        if self.owner_watcher is None or self.claim_sender != sender:
            raise ClaimDevice()

        self.busy = True
        logging.debug('Actually calling target...')
        rc = self.target.EnrollStart(self.claimed_by, finger_name, signature='ss')
        logging.debug('...rc=%s' % repr(rc))
        return rc


    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def EnrollStop(self, sender, connection):
        logging.debug('EnrollStop')

        if self.owner_watcher is None or self.claim_sender != sender:
            raise ClaimDevice()

        self.busy = False
        self.target.Cancel(signature='')
        self.clear_finger()


    @dbus.service.signal(dbus_interface=INTERFACE_NAME, signature='sb')
    def EnrollStatus(self, result, done):
        logging.debug('EnrollStatus')
        if done:
            self.busy = False
            self.clear_finger()

    # ------------------ Debug --------------------------

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='s', 
                         out_signature='s',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def RunCmd(self, s, sender, connection):
        logging.debug('RunCmd')
        return self.target.RunCmd(s, signature='s')

    # ------------------ Props --------------------------

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface, prop):
        logging.debug('Get %s.%s' % (interface, prop))
        
        return self.GetAll(interface)[prop]

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ssv')
    def Set(self, interface, prop, value):
        logging.debug('Set %s.%s=%s' % (interface, prop, repr(value)))
        
        if interface != INTERFACE_NAME:
            raise dbus.exceptions.DBusException('net.reactivated.Fprint.Error.UnknownInterface')
        
        raise dbus.exceptions.DBusException('net.reactivated.Fprint.Error.NotImplemented')

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        logging.debug('GetAll %s' % (interface))
        
        if interface != INTERFACE_NAME:
            raise dbus.exceptions.DBusException('net.reactivated.Fprint.Error.UnknownInterface')

        return self.target_props

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass
