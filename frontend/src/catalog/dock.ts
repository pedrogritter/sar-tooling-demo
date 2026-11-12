/** Open is offered when the download names a scene other than the one on stage. */
export function dockCanOpen(
  downloadSceneId: string | null,
  openSceneId: string | null
): boolean {
  return Boolean(downloadSceneId) && downloadSceneId !== openSceneId
}
