import { expect, test } from 'vitest'
import { AVATAR_VIEW, avatarView } from './config'

test("the avatar page shows the upper body unless its URL says otherwise", () => {
  expect(avatarView('')).toEqual(AVATAR_VIEW)
  expect(avatarView('?top=0&bottom=1')).toEqual({ top: 0, bottom: 1 })
  expect(avatarView('?bottom=0.4')).toEqual({ top: AVATAR_VIEW.top, bottom: 0.4 })
  for (const search of ['?top=0.5&bottom=0.2', '?top=-0.1', '?bottom=1.5', '?top=abc']) {
    expect(avatarView(search)).toEqual(AVATAR_VIEW)
  }
})
