Name:           open-fprintd
Version:        0.7
Release:        1.fork1%{?dist}
Summary:        fprintd replacement for standalone backend services

License:        GPL-2.0-only
URL:            https://github.com/uunicorn/%{name}
# Fork build (upstream plus the patches in its open PRs), made with:
#   git archive --prefix=open-fprintd-0.7/ -o ~/rpmbuild/SOURCES/open-fprintd-0.7.tar.gz integration
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  systemd-rpm-macros

# fprintd provides the D-Bus policy and activation file for
# net.reactivated.Fprint and the fprintd-* clients, and pam_fprintd
# (fprintd-pam) requires it. open-fprintd installs alongside it and
# takes over fprintd.service when enabled (see the description).
Requires:       fprintd
Requires:       python3-dbus
Requires:       python3-gobject-base

%description
fprintd replacement which allows you to have your own backend as a
standalone service, such as python-validity.

fprintd stays installed. To use open-fprintd in its place:

  systemctl enable open-fprintd.service
  systemctl stop fprintd.service

Enabling makes fprintd.service an alias for open-fprintd.service, so D-Bus
activation of net.reactivated.Fprint starts open-fprintd. Disable it to go
back to fprintd. open-fprintd-suspend.service and open-fprintd-resume.service
tell backends about system sleep; enable them if your backend needs that.

%prep
%autosetup -n %{name}-%{version}
%py3_shebang_fix dbus_service/open-fprintd scripts/*.py

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files openfprintd
# fprintd owns these names; its copies are used instead.
rm %{buildroot}%{_datadir}/dbus-1/system-services/net.reactivated.Fprint.service
rm %{buildroot}%{_datadir}/dbus-1/system.d/net.reactivated.Fprint.conf
install -Dpm 0644 fedora/open-fprintd.service %{buildroot}%{_unitdir}/open-fprintd.service
install -Dpm 0644 debian/open-fprintd-suspend.service %{buildroot}%{_unitdir}/open-fprintd-suspend.service
install -Dpm 0644 debian/open-fprintd-resume.service %{buildroot}%{_unitdir}/open-fprintd-resume.service

%post
%systemd_post open-fprintd.service open-fprintd-suspend.service open-fprintd-resume.service

%preun
%systemd_preun open-fprintd.service open-fprintd-suspend.service open-fprintd-resume.service

%postun
%systemd_postun_with_restart open-fprintd.service

%files -f %{pyproject_files}
%doc README.md
%license COPYING
%dir %{_prefix}/lib/%{name}
%attr(0755,root,root) %{_prefix}/lib/%{name}/open-fprintd
%attr(0755,root,root) %{_prefix}/lib/%{name}/suspend.py
%attr(0755,root,root) %{_prefix}/lib/%{name}/resume.py
%{_prefix}/lib/%{name}/__pycache__/
%{_unitdir}/open-fprintd.service
%{_unitdir}/open-fprintd-suspend.service
%{_unitdir}/open-fprintd-resume.service

%changelog
* Fri Sep 25 2026 Ash Hughes <spirit.returned@gmail.com> - 0.7-1.fork1
- Fork build: DeleteEnrolledFinger (#26), root-only RegisterDevice,
  Suspend and Resume and no RunCmd (#28), device properties from the
  backend, finger-present and finger-needed

* Fri Sep 25 2026 Ash Hughes <spirit.returned@gmail.com> - 0.7-1
- Update to 0.7
- Build with the pyproject macros
- Install alongside fprintd: use its D-Bus policy and activation file,
  and take over fprintd.service through an alias when enabled
- Sandboxed systemd unit

* Tue Nov 03 2020 Veit Wahlich <cru@zodia.de> - 0.6-1
- Initial build.
