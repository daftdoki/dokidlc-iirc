import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

import { parseBrief, parseRecall, parseRecovered, statusText, wrapPieces } from './register'

const RECALL =
  'iirc: 2 pages may apply. Read before you investigate: `iirc read alpha-page.md` (first summary (with parens)) · `iirc read beta.md` (second one) (suspect: 40 days; if it holds, `iirc verify beta.md`)'
const RECOVERY =
  'iirc: `uv tool` failed 2 times this session before it worked. If the fix was not obvious from a file in the repository, write one `iirc write` page.'
const BRIEF =
  'iirc: 68 pages, semantic via 127.0.0.1:11434. Topics: claude-code 21, questlog 19. 1 near-duplicate pair: iirc doctor names them; merge each, or link one page to the other with [[name]] if their kinds differ. A hook names matching pages when the creator prompts; read them. `iirc search QUERY` before an install, a fix, or a design.'
const STOP =
  'iirc: before you stop, note that `uv tool` (2 failures) failed and then worked this session, and nothing was written to iirc.'

// Stand-ins for the engine beneath the plugin: it stores rows, runs tools, reads
// files, and draws each row as plain text.
function engine(on: On, toml = '') {
  // Needs the test kit of 2.1.290 or later, which keeps rows beneath this hook.
  on('session.append', ($, e, next) => next(e))
  on('tool.call', () => ({ result: 'ok' }))
  on('session.root', () => ({ value: '/repo' }))
  on('fs.read', () => (toml ? { value: toml } : { deny: 'ENOENT' }))
  on('ui.status', () => ({ value: undefined }))
  on('command.run', () => ({ text: 'the skill ran' }))
  const kept = new Map<string, unknown>()
  on('store.get', ($, e) => ({ value: kept.get(e.key) }))
  on('store.set', ($, e) => (kept.set(e.key, e.value), { value: undefined }))
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

const LINE = 'iirc: [68] pages · [0/0] used · [0] reads · [0] writes · run iirc doctor'

// The hint row as the terminal draws it under the prompt, mounted fresh each time.
let mounts = 0
function hintRow($: Engine) {
  return $.ui.mount({
    plugin: 'iirc',
    surface: 'terminal',
    component: 'PromptHint',
    requestId: `hint-${++mounts}`,
    props: { isDraft: false, isWorking: false, hint: '? for shortcuts' },
  })
}

// Work the module starts on a timer lands a little after the clock settles.
async function waitFor($: Engine, text: string) {
  for (let i = 0; i < 30; i++) {
    if (await (await hintRow($)).find({ text })) return true
    await new Promise(r => setTimeout(r, 10))
  }
  return false
}

test('parses the recall line', () => {
  expect(parseRecall('UserPromptSubmit hook additional context: ' + RECALL)).toEqual([
    { name: 'alpha-page.md', summary: 'first summary (with parens)', isSuspect: false },
    { name: 'beta.md', summary: 'second one', isSuspect: true },
  ])
  expect(parseRecall('iirc: 2 pages may apply. Read before you investigate: `iirc read a.md` (one (x)) [69% match, meaning+term] · `iirc read b.md` (two…) [term match] (suspect: 3 days; if it holds, `iirc verify b.md`)')).toEqual([
    { name: 'a.md', summary: 'one (x)', isSuspect: false, match: '69% match, meaning+term' },
    { name: 'b.md', summary: 'two…', isSuspect: true, match: 'term match' },
  ])
  expect(parseRecall('nothing here')).toEqual([])
})

test('parses the recovery nudge and the brief', () => {
  expect(parseRecovered(RECOVERY)).toEqual([{ command: 'uv tool', failures: 2 }])
  expect(parseBrief(BRIEF)).toEqual({
    status: { level: 'warn', pages: 68, mode: 'semantic+keyword', note: null, fix: 'iirc doctor' },
    warnings: ['1 near-duplicate pair: iirc doctor names them; merge each, or link one page to the other with [[name]] if their kinds differ.'],
  })
  const setup = parseBrief('iirc: not set up on this machine. Ask the creator; then run `iirc setup` with their answer.')!.status
  expect(setup.level).toBe('error')
  expect(statusText(setup, { reads: 0, writes: 0, suggested: 0, used: 0 })).toBe('iirc: needs setup · run iirc setup')
  const down = parseBrief('iirc: 5 pages, string only (127.0.0.1:11434 does not answer; `iirc setup` to fix). Topics: x 5.')!
  expect(down.status).toMatchObject({ level: 'warn', pages: 5, mode: 'keyword', fix: 'iirc setup' })
  expect(down.warnings).toEqual([])
  expect(statusText(parseBrief('iirc: this repository has no .iirc/. Ask the creator whether to create one; if yes, run `iirc init`.')!.status, { reads: 0, writes: 0, suggested: 0, used: 0 })).toBe('iirc: needs init · run iirc init')
  expect(parseBrief('iirc: 9 pages, semantic via h:1. 2 suspect: a.md, b.md (cited file changed).')!.status.fix).toBe('iirc doubt')
  expect(parseBrief('iirc: 9 pages, semantic via h:1. Topics: x 9.')!.status).toMatchObject({ level: 'ok' })
  const one = parseBrief('iirc: 1 page, string search. Topics: x 1.')!.status
  expect(one.level).toBe('ok')
  expect(statusText(one, { reads: 3, writes: 1, suggested: 4, used: 2 })).toBe('iirc: [1] page · [2/4] used · [3] reads · [1] writes · [keyword] mode')
  expect(statusText(parseBrief("iirc: this repository or machine still uses the memory plugin's layout. Ask the creator whether to migrate; if yes, run `iirc migrate`.")!.status, { reads: 0, writes: 0, suggested: 0, used: 0 })).toBe('iirc: needs migration · run iirc migrate')
})

test('wraps page lines by word and keeps each part styled', () => {
  const name = { color: 'claude' as const, bold: true }
  const dim = { dimColor: true, italic: true }
  const lines = wrapPieces([{ text: 'alpha-page', style: name }, { text: '  one two three four', style: dim }], 16)
  expect(lines.map(l => l.map(p => p.text).join(''))).toEqual(['alpha-page  one', 'two three four'])
  expect(lines[0][0].style).toBe(name)
  expect(lines[1][0].style).toBe(dim)
  expect(wrapPieces([{ text: 'abcdefghij', style: dim }], 4).map(l => l[0].text)).toEqual(['abcd', 'efgh', 'ij'])
  expect(wrapPieces([{ text: 'short line', style: dim }], Infinity)).toHaveLength(1)
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`draws a folding list under the prompt on ${surface}`, async ($: Engine, on: On) => {
    engine(on)
    await promptRow($, 'p1')
    await hookRow($, 'UserPromptSubmit', RECALL, 'h1')
    const ui = await $.ui.mount({
      plugin: 'iirc',
      surface,
      component: 'UserMessage',
      requestId: 'p1',
      props: { text: 'a prompt', origin: { kind: 'composer' }, isExpanded: false },
    })
    expect(await ui.find({ text: 'pages suggested' })).toBeDefined()
    expect(await ui.find({ text: 'iirc: ' })).toBeDefined()
    expect(await ui.find({ text: 'alpha-page' })).toBeUndefined()
    await ui.press({ key: 'toggle-p1' })
    expect(await ui.find({ text: 'alpha-page' })).toBeDefined()
    expect(await ui.find({ text: '(suspect)' })).toBeDefined()
    await ui.press({ key: 'toggle-p1' })
    expect(await ui.find({ text: 'alpha-page' })).toBeUndefined()
  })

  test(`draws recalled pages and a recovery row under a tool row on ${surface}`, async ($: Engine, on: On) => {
    engine(on)
    await $.tool.call({ tool: 'Bash', command: 'uv tool install x', tool_use_id: 't1' })
    await hookRow($, 'PostToolUseFailure', RECALL, 'h2')
    await $.tool.call({ tool: 'Bash', command: 'uv tool install x --fix', tool_use_id: 't2' })
    await hookRow($, 'PostToolUse', RECOVERY, 'h3')
    const failed = await $.ui.mount({
      plugin: 'iirc',
      surface,
      component: 'ToolUse',
      requestId: 't1',
      props: { tool_use_id: 't1', tool: 'Bash', input: {}, isRunning: false, isErrored: true, isInterrupted: false },
    })
    expect(await failed.find({ text: 'pages suggested for this error' })).toBeDefined()
    const fixed = await $.ui.mount({
      plugin: 'iirc',
      surface,
      component: 'ToolUse',
      requestId: 't2',
      props: { tool_use_id: 't2', tool: 'Bash', input: {}, isRunning: false, isErrored: false, isInterrupted: false },
    })
    expect(await fixed.find({ text: /failed 2 times, then worked/ })).toBeDefined()
    const call = { tool: 'Bash', input: {}, isRunning: false, isErrored: false, isInterrupted: false }
    const group = await $.ui.mount({
      plugin: 'iirc',
      surface,
      component: 'ToolGroup',
      requestId: 'g1',
      props: { calls: [{ ...call, tool_use_id: 't1' }, { ...call, tool_use_id: 't2' }, { ...call, tool_use_id: 't3' }], isActive: false, isExpanded: false },
    })
    expect(await group.find({ text: 'pages suggested for this error' })).toBeDefined()
    expect(await group.find({ text: /failed 2 times, then worked/ })).toBeDefined()
    await group.press({ key: 'toggle-t1' })
    expect(await group.find({ text: 'alpha-page' })).toBeDefined()
    const unfolded = await $.ui.mount({
      plugin: 'iirc',
      surface,
      component: 'ToolGroup',
      requestId: 'g2',
      props: { calls: [{ ...call, tool_use_id: 't1' }], isActive: false, isExpanded: true },
    })
    expect(await unfolded.find({ text: 'pages suggested for this error' })).toBeUndefined()
  })
}

test('draws the brief in the hint row, toasts its warnings, and toasts the stop nudge', async ($: Engine, on: On) => {
  engine(on)
  const toast: unknown[] = []
  on('ui.toast', ($, e) => (toast.push(e.text), { value: undefined }))
  expect(await (await hintRow($)).find({ text: 'iirc:' })).toBeUndefined()
  await hookRow($, 'SessionStart', BRIEF, 'h4')
  await hookRow($, 'Stop', STOP, 'h5')
  const row = await hintRow($)
  expect(await row.find({ text: LINE })).toBeDefined()
  expect(await row.find({ text: 'engine row' })).toBeDefined()
  expect(toast[0]).toBe('iirc: 1 near-duplicate pair: iirc doctor names them; merge each, or link one page to the other with [[name]] if their kinds differ.')
  expect(String(toast[1])).toContain('`uv tool` (2 failures)')
})

test('at session start, asks iirc for the brief and toasts its warnings once', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const toast: unknown[] = []
  const argv: unknown[] = []
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('process.run', ($, e) => (argv.push(e.argv), { value: { exitCode: 0, stdout: BRIEF, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('ui.toast', ($, e) => (toast.push(e.text), { value: undefined }))
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  expect(await waitFor($, LINE)).toBe(true)
  expect(String((argv[0] as string[])[0])).toContain('bin/iirc')
  expect(toast).toEqual(['iirc: 1 near-duplicate pair: iirc doctor names them; merge each, or link one page to the other with [[name]] if their kinds differ.'])
})

test('after a command that changes the brief, asks iirc for it again', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const argv: string[][] = []
  on('process.run', ($, e) => (argv.push([...e.argv]), { value: { exitCode: 0, stdout: BRIEF, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('ui.toast', () => ({ value: undefined }))
  await $.tool.call({ tool: 'Bash', command: 'git status', tool_use_id: 't4' })
  await clock.settle()
  expect(argv).toEqual([])
  await $.tool.call({ tool: 'Bash', command: '~/x/bin/iirc migrate', tool_use_id: 't5' })
  await clock.settle()
  expect(await waitFor($, LINE)).toBe(true)
})

test('after a read or write, counts the pages this session read and wrote', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const argv: string[][] = []
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('session.id', () => ({ value: 's1' }))
  on('process.run', ($, e) => {
    argv.push([...e.argv])
    return e.argv.includes('stats') ? ran(JSON.stringify({ session: 's1', read: ['a.md', 'b.md'], written: ['c.md'], suggested: ['a.md', 'd.md', 'e.md'], used: ['a.md'] })) : ran(BRIEF)
  })
  on('ui.toast', () => ({ value: undefined }))
  await $.tool.call({ tool: 'Bash', command: 'iirc doctor --brief', tool_use_id: 't6' })
  await clock.settle()
  expect(await waitFor($, LINE)).toBe(true)
  await $.tool.call({ tool: 'Bash', command: 'iirc read a.md b.md', tool_use_id: 't7' })
  await clock.settle()
  expect(await waitFor($, 'iirc: [68] pages · [1/3] used · [2] reads · [1] writes · run iirc doctor')).toBe(true)
  expect(argv.at(-1)?.slice(1)).toEqual(['stats', '--session', 's1'])
})

test('/iirc status off hides the hint-row line, on shows it, and other /iirc args reach the skill', async ($: Engine, on: On) => {
  engine(on)
  on('ui.toast', () => ({ value: undefined }))
  await hookRow($, 'SessionStart', BRIEF, 'h7')
  expect(await (await hintRow($)).find({ text: LINE })).toBeDefined()
  expect((await $.command.run({ command: 'iirc', args: 'status off' })).text).toBe('iirc status off')
  expect(await (await hintRow($)).find({ text: LINE })).toBeUndefined()
  expect((await $.command.run({ command: 'iirc', args: 'status' })).text).toContain('is off')
  expect((await $.command.run({ command: 'iirc', args: 'status on' })).text).toBe('iirc status on')
  expect(await (await hintRow($)).find({ text: LINE })).toBeDefined()
  expect((await $.command.run({ command: 'iirc', args: 'search hooks' })).text).toBe('the skill ran')
})

test('/iirc max-suggested N asks the CLI to keep the number', async ($: Engine, on: On) => {
  engine(on)
  const argv: string[][] = []
  on('process.run', ($, e) => (argv.push([...e.argv]), { value: { exitCode: 0, stdout: 'recall suggests up to 5 pages\n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  expect((await $.command.run({ command: 'iirc:iirc', args: 'max-suggested 5' })).text).toBe('recall suggests up to 5 pages')
  expect(argv[0].slice(1)).toEqual(['max-suggested', '5'])
  await $.command.run({ command: 'iirc', args: 'max-suggested' })
  expect(argv[1].slice(1)).toEqual(['max-suggested'])
})

test('ui = false in iirc.toml draws nothing', async ($: Engine, on: On) => {
  engine(on, 'ui = false\n')
  await promptRow($, 'p2')
  await hookRow($, 'UserPromptSubmit', RECALL, 'h6')
  const ui = await $.ui.mount({
    plugin: 'iirc',
    surface: 'terminal',
    component: 'UserMessage',
    requestId: 'p2',
    props: { text: 'a prompt', origin: { kind: 'composer' }, isExpanded: false },
  })
  expect(await ui.find({ text: 'suggested' })).toBeUndefined()
})

test('leaves a prompt with no recall alone', async ($: Engine, on: On) => {
  engine(on)
  const ui = await $.ui.mount({
    plugin: 'iirc',
    surface: 'terminal',
    component: 'UserMessage',
    requestId: 'nope',
    props: { text: 'x', origin: { kind: 'composer' }, isExpanded: false },
  })
  expect(await ui.find({ text: 'suggested' })).toBeUndefined()
})
