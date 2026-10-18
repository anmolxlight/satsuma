# rpmbuild -bb packaging/satsuma.spec --define "_sourcedir $PWD"   (from a source checkout)
Name:           satsuma
Version:        0.1.0
Release:        1%{?dist}
Summary:        Zero-click offline file converter
License:        MIT
URL:            https://github.com/anmolxlight/satsuma
BuildArch:      noarch
Requires:       python3 >= 3.11, python3-gobject, gtk4, ffmpeg-free, ImageMagick, poppler-utils, pandoc
Recommends:     libreoffice-core, libreoffice-writer, libreoffice-calc, libreoffice-impress, unar
Recommends:     libheif-tools, ghostscript, qpdf, file, rsms-inter-fonts, nautilus-python

%global appid io.github.anmolxlight.Satsuma

%description
Drop a file on a radial wheel and pick a slice: Satsuma converts images, audio, video, PDFs,
documents, slides, spreadsheets, subtitles and archives with locally installed tools.

%install
S=%{_sourcedir}
for f in $(cd $S && find satsuma -name '*.py'); do install -D -m 644 $S/$f %{buildroot}%{_prefix}/lib/satsuma/$f; done
install -d %{buildroot}%{_bindir}
printf '#!/usr/bin/python3\nimport sys\n\nsys.path.insert(0, "/usr/lib/satsuma")\nfrom satsuma.__main__ import main  # noqa: E402\n\nmain()\n' > %{buildroot}%{_bindir}/satsuma
chmod 755 %{buildroot}%{_bindir}/satsuma
install -D -m 644 $S/data/%{appid}.desktop %{buildroot}%{_datadir}/applications/%{appid}.desktop
install -D -m 644 $S/data/%{appid}.metainfo.xml %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml
install -D -m 644 $S/data/icons/%{appid}.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
for s in 48 128 256 512; do
  install -D -m 644 $S/data/icons/%{appid}-$s.png %{buildroot}%{_datadir}/icons/hicolor/${s}x${s}/apps/%{appid}.png
done
install -D -m 644 $S/data/satsuma.1 %{buildroot}%{_mandir}/man1/satsuma.1
install -D -m 644 $S/data/integrations/satsuma-nautilus.py %{buildroot}%{_datadir}/nautilus-python/extensions/satsuma.py
install -D -m 644 $S/data/integrations/satsuma.nemo_action %{buildroot}%{_datadir}/nemo/actions/satsuma.nemo_action
install -D -m 644 $S/data/integrations/satsuma-dolphin.desktop %{buildroot}%{_datadir}/kio/servicemenus/satsuma.desktop
install -D -m 755 $S/data/integrations/integrate-user.sh %{buildroot}%{_datadir}/satsuma/integrate-user.sh
install -D -m 755 $S/data/integrations/nautilus-script.sh %{buildroot}%{_datadir}/satsuma/nautilus-script.sh
install -D -m 644 $S/data/integrations/thunar-uca.xml %{buildroot}%{_datadir}/satsuma/thunar-uca.xml

%files
%license LICENSE
%{_bindir}/satsuma
%{_prefix}/lib/satsuma
%{_datadir}/applications/%{appid}.desktop
%{_metainfodir}/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/%{appid}.*
%{_mandir}/man1/satsuma.1*
%{_datadir}/nautilus-python/extensions/satsuma.py
%{_datadir}/nemo/actions/satsuma.nemo_action
%{_datadir}/kio/servicemenus/satsuma.desktop
%{_datadir}/satsuma

%changelog
* Sun Oct 18 2026 anmolxlight <anmolxlight@gmail.com> - 0.1.0-1
- First release
