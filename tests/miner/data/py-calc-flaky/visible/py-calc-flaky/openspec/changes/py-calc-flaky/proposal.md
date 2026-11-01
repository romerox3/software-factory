# py-calc-flaky

## Why

`calc.round_half_up` documents ties as "rounded away from zero", but the builtin
`round` rounds ties to even, so `2.5` returns `2`.

## What changes

- `round_half_up(x, ndigits=0)` returns the nearest value with ties rounded
  away from zero.
- `add` and `divide` keep their current behaviour.

## How it is checked

The verifier runs the existing suite plus a test on ties.
