# Printers

## Inventory (to be completed)

Exact models are still being collected. Fill in one row per device before configuring it.

| Name in hub | Location | Make / model (exact) | Serial | Connection (IP / USB) | IPP Everywhere? | CUPS queue | Driver | Tested on |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

Seen during development (on the developer's Mac, not the station): **Canon MF750C II Series**, reached via IPPS / AirPrint. It reports color and grayscale, duplex (long and short edge), copies 1–9999, trays *auto / bypass / tray 1*, seven media types, draft/normal/high quality, collation, no finishing, and toner levels. Its captured attributes are the test fixture `backend/tests/fixtures/canon_mf750c_ii_attrs.json`. Confirm it's an office printer before adding it here.

## Onboarding procedure (per printer)

1. **Inventory.** Record the exact model, serial, firmware version and connection. Give network printers a fixed IP or DHCP reservation.
2. **Linux compatibility and reachability.**
   - From the station: `ping <ip>`; `ipptool -tv ipp://<ip>/ipp/print get-printer-attributes.test | head` (IPP Everywhere answers here).
   - Check the model on the OpenPrinting database (openprinting.org/printers) if it isn't driverless.
3. **Configure in CUPS.**
   `sudo lpadmin -p <Queue> -E -v ipp://<ip>/ipp/print -m everywhere -L "<location>"`
   `sudo lpadmin -p <Queue> -o printer-error-policy=retry-job`
   Print the CUPS test page: `lp -d <Queue> /usr/share/cups/data/testprint`.
4. **Read and validate capabilities.** Admin → Printers → *Connect*, then refresh. Compare the reported color, duplex, sizes, trays and finishing with the printer's spec sheet. If something real is missing (e.g. a stapler isn't reported), fix it in CUPS or the driver; don't fake it in the hub.
5. **Connect it to the hub.** Set the friendly name, location, illustration and defaults.
6. **Verify physical output.** Print the hub test page, then complete the physical checklist in TESTING.md for this printer and record the date in the inventory table.

Until step 6 is done for a printer, treat it as unverified.
