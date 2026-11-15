/** Escape closes the open tool. A dialog or a focused field handles it first. */
export function escapeClosesTool(input: {
  key: string
  dialogOpen: boolean
  fieldFocused: boolean
}): boolean {
  if (input.key !== "Escape") {
    return false
  }

  if (input.dialogOpen || input.fieldFocused) {
    return false
  }

  return true
}
