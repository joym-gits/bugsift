import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("renders its children", () => {
    render(<Button>approve</Button>);
    expect(screen.getByRole("button", { name: /approve/i })).toBeDefined();
  });
});
