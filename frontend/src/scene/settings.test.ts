import {
  settingsBody,
  settingsMessage,
  settingsShowsKeyField,
} from "@/scene/settings"

describe("settingsBody", () => {
  it("hides the field when the key arrived from the environment", () => {
    expect(settingsBody("environment", false)).toEqual({ kind: "environment" })
    expect(settingsBody("environment", true)).toEqual({ kind: "environment" })
  })

  it("offers a different key only for a key entered on the page", () => {
    expect(settingsBody("session", false)).toEqual({ kind: "session" })
    expect(settingsBody("session", true)).toEqual({
      kind: "form",
      replacing: true,
    })
  })

  it("shows the form when no key is set", () => {
    expect(settingsBody("unset", false)).toEqual({
      kind: "form",
      replacing: false,
    })
  })

  it("waits while the status is loading", () => {
    expect(settingsBody("loading", false)).toEqual({ kind: "loading" })
  })
})

describe("settingsMessage", () => {
  const bodies = [
    settingsBody("loading", false),
    settingsBody("environment", false),
    settingsBody("session", false),
    settingsBody("unset", false),
    settingsBody("session", true),
  ]

  it("keeps host, port, and catalogue URLs out of the modal", () => {
    for (const body of bodies) {
      const message = settingsMessage(body)
      expect(message).not.toMatch(/SCENE_HOST|SCENE_PORT|8765|catalogue URL|catalog URL/i)
    }
  })

  it("does not echo a key", () => {
    for (const body of bodies) {
      expect(settingsMessage(body)).not.toMatch(/sk-|api_key/i)
    }
  })

  it("says the environment key stays hidden", () => {
    expect(settingsMessage(settingsBody("environment", false))).toMatch(
      /environment/
    )
    expect(settingsMessage(settingsBody("environment", false))).toMatch(/hidden/i)
  })

  it("says a page key is cleared by a restart", () => {
    expect(settingsMessage(settingsBody("session", false))).toMatch(/[Rr]estart/)
    expect(settingsMessage(settingsBody("unset", false))).toMatch(/[Rr]estart/)
  })

  it("says Start still measures without a key", () => {
    expect(settingsMessage(settingsBody("unset", false))).toMatch(
      /Start still measures/
    )
  })
})

describe("settingsShowsKeyField", () => {
  it("is true only for the form", () => {
    expect(settingsShowsKeyField(settingsBody("unset", false))).toBe(true)
    expect(settingsShowsKeyField(settingsBody("session", true))).toBe(true)
    expect(settingsShowsKeyField(settingsBody("environment", false))).toBe(false)
    expect(settingsShowsKeyField(settingsBody("session", false))).toBe(false)
    expect(settingsShowsKeyField(settingsBody("loading", false))).toBe(false)
  })
})
