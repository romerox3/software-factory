# py-calc-round

## Why

`calc.round_half_up` documents ties as "rounded away from zero", but it is
implemented with the builtin `round`, which rounds ties to even:

```python
>>> from calc import round_half_up
>>> round_half_up(2.5)
2.0
```

Consumers of `py-calc` expect the documented behaviour: `2.5` must round to
`3`, `-2.5` to `-3`, and `0.125` with `ndigits=2` to `0.13`.

## What changes

- `round_half_up(x, ndigits=0)` returns the nearest value with ties rounded
  away from zero, for positive and negative `x`, and honours `ndigits`.
- `add` and `divide` keep their current behaviour.

## How it is checked

The visible tests in `tests/` cover the non-tie cases and the arithmetic. The
verifier runs additional tests on ties and on `ndigits`, plus the existing
suite as a regression check.

## Out of scope

- Changing the public signatures of `add`, `divide` or `round_half_up`.
- Editing anything under `tests/`.
