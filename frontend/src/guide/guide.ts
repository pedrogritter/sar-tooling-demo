/** Parse GET /api/guide. The sentences stay on the server. */

export const GUIDE_LOADING = "Opening the usage guide."
export const GUIDE_UNAVAILABLE = "The usage guide could not be read."
export const GUIDE_HEADING = "Documentation"
export const GUIDE_CONTENTS_LABEL = "In this guide"

export interface GuideSection {
  id: string
  title: string
  paragraphs: string[]
}

export interface GuideDocument {
  sections: GuideSection[]
}

export interface GuideContentsEntry {
  id: string
  title: string
}

export function guideDocument(payload: unknown): GuideDocument {
  if (!isRecord(payload) || !Array.isArray(payload.sections)) {
    throw new Error(GUIDE_UNAVAILABLE)
  }

  if (payload.sections.length === 0) {
    throw new Error(GUIDE_UNAVAILABLE)
  }

  return { sections: payload.sections.map(guideSection) }
}

export function contentsEntries(document: GuideDocument): GuideContentsEntry[] {
  return document.sections.map((section) => ({
    id: section.id,
    title: section.title,
  }))
}

function guideSection(value: unknown): GuideSection {
  if (!isRecord(value) || !Array.isArray(value.paragraphs)) {
    throw new Error(GUIDE_UNAVAILABLE)
  }

  if (value.paragraphs.length === 0) {
    throw new Error(GUIDE_UNAVAILABLE)
  }

  return {
    id: requiredText(value.id),
    title: requiredText(value.title),
    paragraphs: value.paragraphs.map(requiredText),
  }
}

function requiredText(value: unknown): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(GUIDE_UNAVAILABLE)
  }

  return value
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}