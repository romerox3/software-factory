import { add, divide, roundHalfUp } from "./calc";

describe("add", () => {
  it("adds integers", () => {
    expect(add(2, 3)).toBe(5);
  });

  it("adds negative numbers", () => {
    expect(add(-4, 1)).toBe(-3);
  });
});

describe("divide", () => {
  it("divides integers", () => {
    expect(divide(9, 3)).toBe(3);
  });

  it("rejects division by zero", () => {
    expect(() => divide(1, 0)).toThrow("division by zero");
  });
});

describe("roundHalfUp", () => {
  it("rounds below the half up", () => {
    expect(roundHalfUp(0.4)).toBe(0);
  });

  it("rounds above the half up", () => {
    expect(roundHalfUp(0.6)).toBe(1);
  });

  it("keeps one decimal digit", () => {
    expect(roundHalfUp(1.24, 1)).toBe(1.2);
  });
});
