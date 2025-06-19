
import dbus
import dbus.service
import logging
import pwd
import os
import time
from gi.repository import GLib

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

    def __init__(self, mgr):
        self.manager = mgr
        bus_name = mgr.bus_name
        dbus.service.Object.__init__(self, bus_name, '/net/reactivated/Fprint/Device/%d' % Device.cnt)
        Device.cnt += 1
        self.bus = bus_name.get_bus()
        self.target_props = dbus.Dictionary({ 
                'name':  'DBus driver', 
                'num-enroll-stages': 5,
                'scan-type': 'press'
            })
        self.owner_watcher = None
        self.claimed_by = None
        self.claim_sender = None
        self.busy = False
        self._session_monitor_id = None
        self._cleanup_timeout_id = None
        self._last_verify_time = 0
        self._cooldown_until = 0  # Initialize cooldown timer

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
        self.target = self.bus.get_object(sender, target_name, introspect=False)
        self.target = dbus.Interface(self.target, 'io.github.uunicorn.Fprint.Device')
        self.target.connect_to_signal('VerifyStatus', self.VerifyStatus)
        self.target.connect_to_signal('VerifyFingerSelected', self.VerifyFingerSelected)
        self.target.connect_to_signal('EnrollStatus', self.EnrollStatus)

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

    # ------------------ Verify --------------------------

    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='s', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def VerifyStart(self, finger_name, sender, connection):
        import time
        current_time = time.time()
        
        # Check if we're in cooldown period
        if current_time < self._cooldown_until:
            logging.debug('Skipping VerifyStart - in cooldown period')
            return
            
        logging.debug('VerifyStart')
        self.busy = True

        if self.owner_watcher is None or self.claim_sender != sender:
            raise ClaimDevice()

        return self.target.VerifyStart(self.claimed_by, finger_name, signature='ss')


    @dbus.service.method(dbus_interface=INTERFACE_NAME,
                         in_signature='', 
                         out_signature='',
                         connection_keyword='connection',
                         sender_keyword='sender')
    def VerifyStop(self, sender, connection):
        logging.debug('VerifyStop')
        
        # Skip if not busy or already released
        if not self.busy:
            logging.debug('Skipping VerifyStop - not busy')
            return
            
        # Check if we have a valid claim
        if self.owner_watcher is None or self.claim_sender != sender:
            logging.debug('Skipping VerifyStop - no owner watcher or invalid sender')
            self.busy = False
            return
        
        try:
            # Mark as not busy first to prevent re-entry
            self.busy = False
            # Then cancel any ongoing operation
            self.target.Cancel(signature='')
            logging.debug('VerifyStop completed successfully')
        except Exception as e:
            logging.debug('Error during VerifyStop: %s', e)
            # Ensure we don't leave the device in a busy state
            self.busy = False

    @dbus.service.signal(dbus_interface=INTERFACE_NAME, signature='s')
    def VerifyFingerSelected(self, finger):
        logging.debug('VerifyFingerSelected')

    @dbus.service.signal(dbus_interface=INTERFACE_NAME, signature='sb')
    def VerifyStatus(self, result, done):
        import time
        
        current_time = time.time()
        self._last_verify_time = current_time
        logging.debug('VerifyStatus (result: %s, done: %s, time: %.3f)' % (result, done, current_time))
        
        # If we got a successful match
        if done and (result is True or (isinstance(result, str) and 'match' in result)):
            logging.debug('Successful authentication detected')
            
            # Only apply special handling for kscreenlocker context
            if self._is_kscreenlocker_context():
                logging.debug('In kscreenlocker context, scheduling cleanup...')
                self._cleanup_verify()
                # Schedule a forced cleanup as a fallback
                self._schedule_cleanup(delay_seconds=2)
            else:
                # For non-kscreenlocker (like su/sudo), just do normal cleanup
                logging.debug('Not in kscreenlocker context, normal cleanup')
                self._cleanup_verify()
            
            # Add a cooldown period to prevent immediate re-verification
            self._cooldown_until = current_time + 5  # 5-second cooldown
            logging.debug(f'Added cooldown until {self._cooldown_until}')
            
        elif done:
            # If done but not a match, just mark as not busy
            self.busy = False
            
    def _is_kscreenlocker_context(self):
        """Check if we're in a kscreenlocker context by examining environment and caller.
        Returns True if we're likely running under kscreenlocker, False otherwise."""
        try:
            # Check if we have a display (not running in a console)
            display = os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
            if not display:
                return False
                
            # Check parent process to see if it's kscreenlocker
            try:
                import psutil
                parent = psutil.Process(os.getppid())
                if 'kscreenlocker' in parent.name().lower():
                    return True
            except Exception as e:
                logging.debug(f'Could not check parent process: {e}')
                
            # Check environment variables that might indicate kscreenlocker
            xdg_session_type = os.environ.get('XDG_SESSION_TYPE', '').lower()
            xdg_current_desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
            
            if 'kscreenlocker' in xdg_current_desktop or 'lock' in xdg_session_type:
                return True
                
            return False
            
        except Exception as e:
            logging.debug(f'Error checking kscreenlocker context: {e}')
            return False
    
    def _cleanup_verify(self, force=False):
        """Clean up verification state and release resources.
        
        Args:
            force: If True, force cleanup even if not marked as busy
        """
        if not force and not self.busy:
            logging.debug('Skipping cleanup - not busy')
            return

        if self.owner_watcher is None:
            logging.debug('Skipping cleanup - no owner watcher')
            self.busy = False
            return

        # Cancel any pending cleanup timeouts
        if self._cleanup_timeout_id is not None:
            GLib.source_remove(self._cleanup_timeout_id)
            self._cleanup_timeout_id = None

        logging.debug('Starting cleanup...')
        sender = self.claim_sender
        cleanup_complete = False

        try:
            # Only try to stop verification if we're still busy
            if (force or self.busy) and sender is not None:
                try:
                    logging.debug('Calling VerifyStop...')
                    self.VerifyStop(sender, None)
                    cleanup_complete = True
                except Exception as e:
                    logging.debug('Error in VerifyStop during cleanup: %s', e)

            # Only try to release if we haven't already completed cleanup
            if not cleanup_complete and self.owner_watcher is not None and sender is not None:
                try:
                    logging.debug('Calling Release...')
                    self.Release(sender, None)
                    cleanup_complete = True
                except Exception as e:
                    logging.debug('Error in Release during cleanup: %s', e)
        except Exception as e:
            logging.debug('Unexpected error during cleanup: %s', e)
        finally:
            if cleanup_complete or not self.busy:
                logging.debug('Cleanup completed successfully')
            else:
                logging.debug('Cleanup may not have completed successfully')
            self.busy = False
            
    def _schedule_cleanup(self, delay_seconds=5):
        """Schedule a forced cleanup after a delay.
        
        Only schedules if we're in a kscreenlocker context to avoid interfering
        with other authentication flows.
        """
        if not self._is_kscreenlocker_context():
            logging.debug('Skipping scheduled cleanup - not in kscreenlocker context')
            return
            
        if self._cleanup_timeout_id is not None:
            GLib.source_remove(self._cleanup_timeout_id)
        
        def cleanup_callback():
            self._cleanup_timeout_id = None
            if self._is_kscreenlocker_context():  # Double-check context
                logging.debug('Cleanup timeout triggered, forcing cleanup')
                self._cleanup_verify(force=True)
            else:
                logging.debug('Skipping cleanup - no longer in kscreenlocker context')
            return False  # Don't repeat
            
        self._cleanup_timeout_id = GLib.timeout_add_seconds(
            delay_seconds, cleanup_callback)
        logging.debug(f'Scheduled kscreenlocker cleanup in {delay_seconds} seconds')

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
