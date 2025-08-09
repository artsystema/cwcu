# cwcu
Custom water cooling unity software

## Dynamic state variables

The display exposes four global variables that represent the state of each
metric tile. They can be changed at runtime:

- `FANS`
- `PUMPS`
- `PROPES`
- `FLOW`

All variables default to `0` which indicates "no signal" for the
corresponding tile.
