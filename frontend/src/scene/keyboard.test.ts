import { escapeClosesTool } from "@/scene/keyboard"

describe("escapeClosesTool", () => {
  it("closes the tool pane on Escape", () => {
    expect(
      escapeClosesTool({
        key: "Escape",
        dialogOpen: false,
        fieldFocused: false,
      })
    ).toBe(true)
  })

  it("ignores Escape while Settings is open", () => {
    expect(
      escapeClosesTool({
        key: "Escape",
        dialogOpen: true,
        fieldFocused: false,
      })
    ).toBe(false)
  })

  it("ignores Escape while a field is focused", () => {
    expect(
      escapeClosesTool({
        key: "Escape",
        dialogOpen: false,
        fieldFocused: true,
      })
    ).toBe(false)
  })

  it("ignores other keys", () => {
    expect(
      escapeClosesTool({
        key: "Enter",
        dialogOpen: false,
        fieldFocused: false,
      })
    ).toBe(false)
  })
})
