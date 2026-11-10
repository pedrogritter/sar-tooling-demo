/**
 * Which edge panel is open. Clicking the active tool closes it.
 * Escape closes the panel that was opened most recently.
 */

export type LeftTool = "catalog" | "library" | "facts"
export type RightTool = "stage" | "measure" | "results"
export type Edge = "left" | "right"

export interface EdgeState {
  left: LeftTool | null
  right: RightTool | null
  last: Edge | null
}

export const CLOSED_EDGES: EdgeState = {
  left: null,
  right: null,
  last: null,
}

export function toggleLeft(state: EdgeState, tool: LeftTool): EdgeState {
  const left = state.left === tool ? null : tool
  return { ...state, left, last: left ? "left" : state.last }
}

export function toggleRight(state: EdgeState, tool: RightTool): EdgeState {
  const right = state.right === tool ? null : tool
  return { ...state, right, last: right ? "right" : state.last }
}

export function closeLast(state: EdgeState): EdgeState {
  if (state.last === "left") {
    return { ...state, left: null }
  }

  if (state.last === "right") {
    return { ...state, right: null }
  }

  return state
}
