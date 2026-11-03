import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BirthFeed from "../BirthFeed";

describe("BirthFeed", () => {
  it("renders nothing when empty", () => {
    const { container } = render(<BirthFeed items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows op chips with the memory text", () => {
    render(
      <BirthFeed
        items={[
          { key: 1, op: "NEW", text: "The vault code is AR-4401." },
          { key: 2, op: "SUPERSEDE", text: "Correction: the code is AR-4402." },
        ]}
      />
    );
    expect(screen.getByText("The vault code is AR-4401.")).toBeInTheDocument();
    expect(screen.getByText("Correction: the code is AR-4402.")).toBeInTheDocument();
    expect(screen.getByText("NEW")).toHaveClass("op-NEW");
    expect(screen.getByText("SUPERSEDE")).toHaveClass("op-SUPERSEDE");
  });
});
