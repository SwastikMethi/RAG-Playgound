import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { Button, Status } from "./ui";

it("exposes an accessible loader and disables a loading button", () => {
  const html = renderToStaticMarkup(createElement(Button, { loading: true }, "Prepare selected"));

  expect(html).toContain("disabled");
  expect(html).toContain('role="status"');
  expect(html).toContain('aria-label="Loading"');
  expect(html).toContain("Prepare selected");
});

it("marks active work statuses as busy", () => {
  for (const value of ["queued", "processing", "preparing", "running", "building"])
    expect(renderToStaticMarkup(createElement(Status, { value }))).toContain('aria-busy="true"');
  expect(renderToStaticMarkup(createElement(Status, { value: "ready" }))).not.toContain(
    'aria-busy="true"',
  );
});
