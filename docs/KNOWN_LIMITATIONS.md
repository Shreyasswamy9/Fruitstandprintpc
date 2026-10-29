# Known limitations

## Not built yet (labeled as such in the UI)

- **Office documents** (Word, Excel, PowerPoint) aren't accepted. People are told to save as PDF. Conversion (e.g. LibreOffice headless) can change layout and fonts, so it should be added only with visible warnings and its own verification.
- **Brand typeface** is a system-font placeholder until the real font is supplied (BRANDING.md).
- **HTTPS** isn't built in; use a reverse proxy (OPERATIONS.md › Network).
- **Station PIN sign-in** isn't built; everyone uses username and password (ACCESS.md).

## Can't be known by the hub

- Whether paper physically came out. "Completed" is what CUPS reports.
- Jams, paper-outs or supply levels on printers that don't report them over IPP; these show as unknown.
- The exact appearance of output: margins, color conversion, duplex registration. The preview states these limits.
- The outcome of a job after CUPS purges its record, or when a restart happens mid-submission. These show as "Outcome unknown", and retrying requires confirmation.

## Behaviour to be aware of

- Borderless ("full bleed") and custom paper sizes reported by printers are hidden in this version to keep the size list readable.
- Copies are capped at 999 in the interface even if a printer reports more.
- Page ranges apply per PDF file; images are always one page.
- A cancel while a file is being sent ("Sending…") is refused with "try again in a moment" rather than racing the print system.
- Printer status refreshes every ~20 s; Admin → Printers → refresh checks immediately.
- Demo and production share the database if you switch modes on one data directory; demo jobs stay labeled as simulated.
- The frontend bundle is about 800 KB (240 KB gzipped) plus a 1.2 MB PDF worker, all served locally.

## Not verified yet

Everything listed under *Not yet tested* in TESTING.md: Linux Mint installation, systemd/autostart/power behaviour, office-network reachability, and real printing on each office printer.
