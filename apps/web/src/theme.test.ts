import { expect, it } from "vitest";
import { resolveTheme } from "./theme";

it("uses an explicit theme before the operating-system preference", () => {
  expect(resolveTheme("dark", false)).toBe("dark");
  expect(resolveTheme("light", true)).toBe("light");
  expect(resolveTheme(null, true)).toBe("dark");
  expect(resolveTheme("invalid", false)).toBe("light");
});
