import type { ModelKeySource } from "@/types"

/** Which body the Settings modal shows. The environment source has no field. */
export type SettingsBody =
  | { kind: "loading" }
  | { kind: "environment" }
  | { kind: "session" }
  | { kind: "form"; replacing: boolean }

/** The panel for this source. Replacing an environment key is ignored. */
export function settingsBody(
  source: ModelKeySource | "loading",
  replacing: boolean
): SettingsBody {
  if (source === "loading") {
    return { kind: "loading" }
  }

  if (source === "environment") {
    return { kind: "environment" }
  }

  if (source === "session" && !replacing) {
    return { kind: "session" }
  }

  return { kind: "form", replacing: source === "session" }
}

/** The sentence for that panel. It never contains the key. */
export function settingsMessage(body: SettingsBody): string {
  if (body.kind === "loading") {
    return "Checking whether an OpenAI key is set."
  }

  if (body.kind === "environment") {
    return "An OpenAI key arrived from the environment. It stays as it is, and this field stays hidden."
  }

  if (body.kind === "session") {
    return "A key entered here is set for this server. Restarting the container clears it."
  }

  return "Without a key, Start still measures and the lead is built from the summary rows. A key lets the model write that lead. A key saved here stays in this running server only. It is not written into the project or the image. Restarting the container clears it."
}

/** The password field is rendered only while a key can be saved. */
export function settingsShowsKeyField(body: SettingsBody): boolean {
  return body.kind === "form"
}
