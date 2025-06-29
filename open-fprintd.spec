Name:           open-fprintd
Version:        0.6
Release:        1%{?dist}
Summary:        fprintd replacement for standalone backend services

License:        GPLv2
URL:            https://github.com/uunicorn/%{name}
Source0:        %{name}-%{version}.tar.gz
#Source0:        https://github.com/uunicorn/%{name}/archive/%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel
Requires:       fprintd-clients

%description
fprintd replacement which allows you to have your own backend as a standalone service.

%prep
%autosetup -n %{name}-%{version}

%build
%py3_build

%install
%py3_install
%__install -d -m 0755 $RPM_BUILD_ROOT%{_prefix}/lib/systemd/system
%__install -m 0644 debian/open-fprintd.service $RPM_BUILD_ROOT%{_prefix}/lib/systemd/system/
%__install -m 0644 debian/open-fprintd-suspend.service $RPM_BUILD_ROOT%{_prefix}/lib/systemd/system/
%__install -m 0644 debian/open-fprintd-resume.service $RPM_BUILD_ROOT%{_prefix}/lib/systemd/system/

%post
%systemd_post open-fprintd.service

%preun
%systemd_preun open-fprintd.service

%files
%doc README.md
%license COPYING
%{python3_sitelib}/openfprintd/
%{python3_sitelib}/open_fprintd-%{version}-py*.egg-info/
%{_prefix}/lib/%{name}/open-fprintd
%{_prefix}/lib/%{name}/suspend.py
%{_prefix}/lib/%{name}/resume.py
%{_prefix}/lib/systemd/system/%{name}*.service
%{_datadir}/dbus-1/system-services/net.reactivated.Fprint.service
%{_datadir}/dbus-1/system.d/net.reactivated.Fprint.conf

%changelog
* Tue Nov 03 2020 Veit Wahlich <cru@zodia.de> - 0.6-1
- Initial build.
