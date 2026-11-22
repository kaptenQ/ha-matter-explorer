# Test fixtures

Node dumps in the Matter Server `node` format.

- `liljebagge-node6.json`: an IKEA LILJEBAGGE radiator thermostat (Thread). Captured from a real device, then
  redacted.
- `lab-node.json`: a matter.js sample device (OnOff + temperature) from the development lab, also redacted.

## What was redacted

Everything that identifies a home or a fabric was replaced by fake values of the same type and shape; the rest is
untouched, so the fixtures still behave like real nodes.

| Attribute | Change |
| --- | --- |
| `0/40/5` NodeLabel (liljebagge) | "Living room thermostat" |
| `0/40/15` SerialNumber, `0/40/18` UniqueID | random values of the same length |
| `0/62/*` Operational Credentials | NOCs, fabric public keys and root certificates replaced by random bytes of the same length (not valid certificates) |
| `0/49/*` Network Commissioning | network ids replaced |
| `0/51/0` General Diagnostics | interface hardware addresses and IP addresses replaced (documentation range 192.0.2.0/24 where an IPv4 address is needed) |
| `0/53/*` Thread Network Diagnostics | network name, PAN id, extended PAN id, mesh-local prefix, neighbour and route tables (extended addresses, ids), channel mask replaced |
| `date_commissioned`, `last_interview`, `0/56/0`, `0/56/7` | shifted to other dates |

The matter.js sample's `0/40/15` and `0/40/18` were also replaced. `0/40/6` (Location) was already `**REDACTED**`.
Tests assert on the redacted values (for example the node name "Living room thermostat").
