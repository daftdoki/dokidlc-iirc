import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

import { parseBrief, parseRecall, parseRecovered } from './register'

const RECALL =
  'memory: 2 pages may apply. Read before you investigate: `memory read alpha-page.md` (first summary (with parens)) · `memory read beta.md` (second one) (suspect: 40 days; if it holds, `memory verify beta.md`)'
const RECOVERY =
  'memory: `uv tool` failed 2 times this session before it worked. If the fix was not obvious from a file in the repository, write one `memory write` page.'
const BRIEF =
  'memory: 68 pages, semantic via 127.0.0.1:11434. Topics: claude-code 21, questlog 19. 1 near-duplicate pair: memory doctor names them; merge each or keep both. A hook names matching pages when the creator prompts; read them. `memory search QUERY` before an install, a fix, or a design.'
const STOP =
  'memory: before you stop, note that `uv tool` (2 failures) failed and then worked this session, and nothing was written to memory.'

// Stand-ins for the engine beneath the plugin: it stores rows, runs tools, reads
// files, and draws each row as plain text.
function engine(on: On, toml = '') {
  // Needs the test kit of 2.1.290 or later, which keeps rows beneath this hook.
  on('session.append', ($, e, next) => next(e))
  on('tool.call', () => ({ result: 'ok' }))
  on('session.root', () => ({ value: '/repo' }))
  on('fs.read', () => (toml ? { value: toml } : { deny: 'ENOENT' }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return h(Text, null, 'engine row')
  })
}

async function hookRow($: Engine, event: string, text: string, uuid: string) {
  await $.session.append({
    message: { type: 'attachment', name: 'hook_additional_context', content: [{ type: 'text', text }] },
    door: 'hook-context',
    origin: { kind: 'hook', event },
    uuid,
  })
}

async function promptRow($: Engine, uuid: string) {
  await $.session.append({
    message: { type: 'user', role: 'user', content: [{ type: 'text', text: 'a prompt' }] },
    door: 'prompt',
    origin: { kind: 'composer' },
    uuid,
  })
}

test('parses the recall line', () => {
  expect(parseRecall('UserPromptSubmit hook additional context: ' + RECALL)).toEqual([
    { name: 'alpha-page.md', summary: 'first summary (with parens)', isSuspect: false },
    { name: 'beta.md', summary: 'second one', isSuspect: true },
  ])
  expect(parseRecall('nothing here')).toEqual([])
})

test('parses the recovery nudge and the brief', () => {
  expect(parseRecovered(RECOVERY)).toEqual([{ command: 'uv tool', failures: 2 }])
  expect(parseBrief(BRIEF)).toEqual({
    status: '◆ memory 68 · semantic',
    warnings: ['1 near-duplicate pair: memory doctor names them; merge each or keep both.'],
  })
  expect(parseBrief('memory: not set up on this machine. Ask the creator.')?.status).toBe('◆ memory: needs setup')
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`draws a folding list under the prompt on ${surface}`, async ($: Engine, on: On) => {
    engine(on)
    await promptRow($, 'p1')
    await hookRow($, 'UserPromptSubmit', RECALL, 'h1')
    const ui = await $.ui.mount({
      plugin: 'memory',
      surface,
      component: 'UserMessage',
      requestId: 'p1',
      props: { text: 'a prompt', origin: { kind: 'composer' }, isExpanded: false },
    })
    expect(await ui.find({ text: 'memory items retrieved' })).toBeDefined()
    expect(await ui.find({ text: 'alpha-page' })).toBeUndefined()
    await ui.press({ key: 'toggle-p1' })
    expect(await ui.find({ text: 'alpha-page' })).toBeDefined()
    expect(await ui.find({ text: '(suspect)' })).toBeDefined()
    await ui.press({ key: 'toggle-p1' })
    expect(await ui.find({ text: 'alpha-page' })).toBeUndefined()
  })

  test(`draws recalled pages and a recovery row under a tool row on ${surface}`, async ($: Engine, on: On) => {
    engine(on)
    await $.tool.call({ tool: 'Bash', input: { command: 'uv tool install x' }, tool_use_id: 't1' })
    await hookRow($, 'PostToolUseFailure', RECALL, 'h2')
    await $.tool.call({ tool: 'Bash', input: { command: 'uv tool install x --fix' }, tool_use_id: 't2' })
    await hookRow($, 'PostToolUse', RECOVERY, 'h3')
    const failed = await $.ui.mount({
      plugin: 'memory',
      surface,
      component: 'ToolUse',
      requestId: 't1',
      props: { tool_use_id: 't1', tool: 'Bash', input: {}, isRunning: false, isErrored: true, isInterrupted: false },
    })
    expect(await failed.find({ text: 'memory items match this error' })).toBeDefined()
    const fixed = await $.ui.mount({
      plugin: 'memory',
      surface,
      component: 'ToolUse',
      requestId: 't2',
      props: { tool_use_id: 't2', tool: 'Bash', input: {}, isRunning: false, isErrored: false, isInterrupted: false },
    })
    expect(await fixed.find({ text: /failed 2 times, then worked/ })).toBeDefined()
    const call = { tool: 'Bash', input: {}, isRunning: false, isErrored: false, isInterrupted: false }
    const group = await $.ui.mount({
      plugin: 'memory',
      surface,
      component: 'ToolGroup',
      requestId: 'g1',
      props: { calls: [{ ...call, tool_use_id: 't1' }, { ...call, tool_use_id: 't2' }, { ...call, tool_use_id: 't3' }], isActive: false, isExpanded: false },
    })
    expect(await group.find({ text: 'memory items match this error' })).toBeDefined()
    expect(await group.find({ text: /failed 2 times, then worked/ })).toBeDefined()
    await group.press({ key: 'toggle-t1' })
    expect(await group.find({ text: 'alpha-page' })).toBeDefined()
    const unfolded = await $.ui.mount({
      plugin: 'memory',
      surface,
      component: 'ToolGroup',
      requestId: 'g2',
      props: { calls: [{ ...call, tool_use_id: 't1' }], isActive: false, isExpanded: true },
    })
    expect(await unfolded.find({ text: 'memory items match this error' })).toBeUndefined()
  })
}

test('sets the status line and toasts the brief warnings, and toasts the stop nudge', async ($: Engine, on: On) => {
  engine(on)
  const status: unknown[] = []
  const toast: unknown[] = []
  on('ui.status', ($, e) => (status.push(e.text), { value: undefined }))
  on('ui.toast', ($, e) => (toast.push(e.text), { value: undefined }))
  await hookRow($, 'SessionStart', BRIEF, 'h4')
  await hookRow($, 'Stop', STOP, 'h5')
  expect(status).toEqual(['◆ memory 68 · semantic'])
  expect(toast[0]).toBe('memory: 1 near-duplicate pair: memory doctor names them; merge each or keep both.')
  expect(String(toast[1])).toContain('`uv tool` (2 failures)')
})

test('at session start, asks memory for the brief and shows it once', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const status: unknown[] = []
  const toast: unknown[] = []
  const argv: unknown[] = []
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('process.run', ($, e) => (argv.push(e.argv), { value: { exitCode: 0, stdout: BRIEF, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('ui.status', ($, e) => (status.push(e.text), { value: undefined }))
  on('ui.toast', ($, e) => (toast.push(e.text), { value: undefined }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  for (let i = 0; i < 30 && status.length < 2; i++) await new Promise(r => setTimeout(r, 10))
  expect(String((argv[0] as string[])[0])).toContain('bin/memory')
  expect(status).toEqual(['◆ memory 68 · semantic', '◆ memory 68 · semantic'])
  expect(toast).toEqual(['memory: 1 near-duplicate pair: memory doctor names them; merge each or keep both.'])
})

test('ui = false in memory.toml draws nothing', async ($: Engine, on: On) => {
  engine(on, 'ui = false\n')
  await promptRow($, 'p2')
  await hookRow($, 'UserPromptSubmit', RECALL, 'h6')
  const ui = await $.ui.mount({
    plugin: 'memory',
    surface: 'terminal',
    component: 'UserMessage',
    requestId: 'p2',
    props: { text: 'a prompt', origin: { kind: 'composer' }, isExpanded: false },
  })
  expect(await ui.find({ text: 'retrieved' })).toBeUndefined()
})

test('leaves a prompt with no recall alone', async ($: Engine, on: On) => {
  engine(on)
  const ui = await $.ui.mount({
    plugin: 'memory',
    surface: 'terminal',
    component: 'UserMessage',
    requestId: 'nope',
    props: { text: 'x', origin: { kind: 'composer' }, isExpanded: false },
  })
  expect(await ui.find({ text: 'retrieved' })).toBeUndefined()
})
