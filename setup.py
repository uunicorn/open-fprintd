#!/usr/bin/python3

from setuptools import setup

setup(name='open-fprintd',
      version='0.6',
      py_modules = [],
      packages=['openfprintd'],
      scripts=[],
      data_files=[
          ('share/dbus-1/system-services/', ['dbus_service/net.reactivated.Fprint.service']),
          ('share/dbus-1/system.d/', ['dbus_service/net.reactivated.Fprint.conf']),
          ('lib/open-fprintd/', ['dbus_service/open-fprintd', 'scripts/suspend.py', 'scripts/resume.py']),
      ]
)
