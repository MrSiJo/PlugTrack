import { describe, expect, it } from 'vitest'
import { Button } from './button'
import { Dialog } from './dialog'
import { Tabs } from './tabs'
import { Tooltip } from './tooltip'
import { Popover } from './popover'
import { DropdownMenu } from './dropdown-menu'
import { Command } from './command'
import { Input } from './input'
import { Label } from './label'
import { Switch } from './switch'

describe('shadcn primitive imports', () => {
  it('all primitives import without error', () => {
    expect(Button).toBeDefined()
    expect(Dialog).toBeDefined()
    expect(Tabs).toBeDefined()
    expect(Tooltip).toBeDefined()
    expect(Popover).toBeDefined()
    expect(DropdownMenu).toBeDefined()
    expect(Command).toBeDefined()
    expect(Input).toBeDefined()
    expect(Label).toBeDefined()
    expect(Switch).toBeDefined()
  })
})
