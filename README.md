# open-fprintd
Fprintd replacement which allows you to have your own backend as a standalone service.

This is very much work in progress, but the intended architecture should look something like this:
```
  <libpam module (C)>    <Gnome settings>   <GDM>
            \                /              /
             \              /              /
       (net.reactivated.Fprint.* -- client DBus interfaces)
               \          /              /
                \        /              /
              <open-fprintd (this project)>
                /             \
               /               \ 
 (io.github.uunicorn.Fprint.* -- back-end DBus interfaces)
             /                   \
            /                     \
<python-validity (Python)>    <exsting drivers exposed by a single service linked against the offcial libfprint (C)>
```

## Warning

This is work in progress. Install and use at your own risk.  At this point this project does not enforce any auth 
checks against requests made on DBus.

## Setting up

On a Debian-based system, to re-install from sources (useful for testing):
```
./setup.py install --force --install-layout deb --prefix=/usr --root=/
```

## Why?

Existing architecture of `fprintd` and `libfprint` does not allow loosely coupled integration with 3rd party drivers. 
This is done on purpose to force hardware vendors to contribute their drivers as an open source. Unfortunately this 
approach prevents open source projects (like `python-validity`) to be integrated with the rest of the stack without 
creating a shim which could be exploited by the vendors to create a binary driver distributions. `open-fprintd` will 
allow anyone to contribute a backend implementation. I rust the end user should be responsible for making a choice between an 
open source driver and a binary blob provided by a hardware vendor. They have already chosen Linux over Windows anyway.

For more deatils about upstream politics, see [this issue](https://gitlab.freedesktop.org/libfprint/libfprint/-/issues/276).
