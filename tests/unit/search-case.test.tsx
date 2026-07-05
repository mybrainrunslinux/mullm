import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { BoardView } from '../../src/features/board/BoardView'

vi.mock('@dnd-kit/core', () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  closestCenter: {},
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
  PointerSensor: vi.fn(),
  KeyboardSensor: vi.fn(),
}))

vi.mock('@dnd-kit/sortable', () => ({
  useSortable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  }),
  SortableContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  verticalListSortingStrategy: {},
  arrayMove: vi.fn(),
}))

vi.mock('@dnd-kit/utilities', () => ({
  CSS: { Transform: { toString: () => '' } },
}))

vi.mock('../../src/store/AppContext', () => ({
  useAppContext: () => ({
    state: {
      cards: [
        {
          id: 'c1',
          // Title contains 'Login' (capital L) — case-sensitive includes('login') returns false
          // Case-insensitive toLowerCase().includes('login') returns true
          title: 'Fix Login Page Styles',
          description: '',
          columnId: 'col-1',
          assigneeId: null,
          labelIds: [],
          dueDate: null,
          priority: 'medium',
          sprintId: null,
          createdAt: '2026-01-01',
          order: 0,
        },
        {
          id: 'c2',
          title: 'Update Dashboard',
          description: '',
          columnId: 'col-1',
          assigneeId: null,
          labelIds: [],
          dueDate: null,
          priority: 'low',
          sprintId: null,
          createdAt: '2026-01-01',
          order: 1,
        },
      ],
      columns: [{ id: 'col-1', title: 'To Do', order: 0 }],
      users: [{ id: 'u1', name: 'Alice' }],
      labels: [],
      sprints: [],
      currentUserId: 'u1',
      // Lowercase query — must match 'Login' (uppercase) case-insensitively
      searchQuery: 'login',
      activeSprintId: null,
      sprintViewEnabled: false,
      boardName: 'Test Board',
    },
    dispatch: vi.fn(),
  }),
}))

describe('search-case', () => {
  it('shows cards whose title matches the search query case-insensitively', () => {
    render(<BoardView />)

    // 'Fix Login Page Styles'.includes('login') === false  → BUG: card hidden, test FAILS
    // 'Fix Login Page Styles'.toLowerCase().includes('login') === true  → FIX: card shown, test PASSES
    expect(screen.getByText('Fix Login Page Styles')).toBeInTheDocument()
  })

  it('hides cards whose title does not match the search query', () => {
    render(<BoardView />)

    // 'Update Dashboard' contains neither 'login' nor 'Login' — must be hidden after any fix
    expect(screen.queryByText('Update Dashboard')).not.toBeInTheDocument()
  })
})
