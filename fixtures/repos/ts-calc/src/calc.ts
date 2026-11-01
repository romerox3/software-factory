/** Toy calculator used as a fixture repository. */

export function add(a: number, b: number): number {
  return a + b;
}

export function divide(a: number, b: number): number {
  if (b === 0) {
    throw new Error("division by zero");
  }
  return a / b;
}

export function roundHalfUp(x: number, ndigits = 0): number {
  const factor = 10 ** ndigits;
  return Math.round(x * factor) / factor;
}
