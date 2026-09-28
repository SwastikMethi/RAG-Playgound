import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { BackgroundWork, Button, Status } from "./ui";

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

it("explains queued work and replaces it with active preparation", () => {
  const queued = renderToStaticMarkup(createElement(BackgroundWork, { status: "queued" }));
  expect(queued).toContain("Starting the on-demand worker or waiting for earlier work");
  expect(queued).toContain("about a minute after inactivity");
  expect(queued).toContain('role="status"');

  const preparing = renderToStaticMarkup(
    createElement(BackgroundWork, { status: "preparing" }),
  );
  expect(preparing).toContain("Preparing selected pipelines");
  expect(preparing).not.toContain("Starting the on-demand worker");
});
