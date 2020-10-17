
import dbus
import dbus.service
import logging
import pwd


INTERFACE_NAME = 'net.reactivated.Fprint.Device'

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

    def __init__(self, mgr, target_name):
        self.manager = mgr
        bus_name = mgr.bus_name
        dbus.service.Object.__init__(self, bus_name, '/net/reactivated/Fprint/Device/%d' % Device.cnt)
        Device.cnt += 1
        self.bus = bus_name.get_bus()

        self.target = self.bus.get_object(target_name, '/io/github/uunicorn/Fprint/Device', introspect=False)
        self.target_props = dbus.Dictionary({ 
                'name':  'DBus driver', 
                'num-enroll-stages': 5,
                'scan-type': 'press'
            })
        self.target = dbus.Interface(self.target, 'io.github.uunicorn.Fprint.Device')
        self.target.connect_to_signal('VerifyStatus', self.VerifyStatus)
        self.target.connect_to_signal('VerifyFingerSelected', self.VerifyFingerSelected)
        self.target.connect_to_signal('EnrollStatus', self.EnrollStatus)
        self.owner_watcher = None
        self.claimed_by = None
        self.claim_sender = None
        self.busy = False

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

        self.manager.proxy_call(cb)

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

    @dbus.service.signal(dbus_interface=INTERFACE_NAME, signature='s')
    def VerifyFingerSelected(self, finger):
        logging.debug('VerifyFingerSelected')

    @dbus.service.signal(dbus_interface=INTERFACE_NAME, signature='sb')
    def VerifyStatus(self, result, done):
        logging.debug('VerifyStatus')
        if done:
            self.busy = False

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


    @dbus.service.signal(dbus_interface=INTERFACE_NAME, signature='sb')
    def EnrollStatus(self, result, done):
        logging.debug('EnrollStatus')
        if done:
            self.busy = False

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
