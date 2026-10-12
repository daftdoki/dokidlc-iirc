import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

import { actions, actionText, liveStatus, searchSetting, paragraphs, parseBrief, parseDoctor, parseRecall, parseRecovered, statusText, wrapPieces } from './register'
import type { IircStatus, SessionCounts } from '../types'

const RECALL =
  'iirc: 2 pages may apply. Read a page whose summary bears on this task; skip the rest: `iirc read alpha-page.md` (first summary (with parens)) · `iirc read beta.md` (second one) (suspect: 40 days; if it holds, `iirc verify beta.md`)'
const RECOVERY =
  'iirc: `uv tool` failed 2 times this session before it worked. If the fix was not obvious from a file in the repository, write one `iirc write` page.'
const BRIEF =
  'iirc: 68 pages, semantic via 127.0.0.1:11434. Topics: claude-code 21, questlog 19. Maintenance is due (1 near-duplicate pair); run /iirc run-maintenance. A hook names matching pages when the creator prompts; read one whose summary bears on the task. `iirc search QUERY` before an install, a fix, or a design.'
const STOP =
  'iirc: before you stop, note that `uv tool` (2 failures) failed and then worked this session, and nothing was written to iirc.'

// Stand-ins for the engine beneath the plugin: it stores rows, runs tools, reads
// files, and draws each row as plain text.
function engine(on: On, toml = '', isBandEmpty = false, isHintNative = false) {
  // Needs the test kit of 2.1.290 or later, which keeps rows beneath this hook.
  on('session.append', ($, e, next) => next(e))
  on('tool.call', () => ({ result: 'ok' }))
  on('session.root', () => ({ value: '/repo' }))
  on('fs.read', () => (toml ? { value: toml } : { deny: 'ENOENT' }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('command.run', () => ({ text: 'the skill ran' }))
  const kept = new Map<string, unknown>()
  on('store.get', ($, e) => ({ value: kept.get(e.key) }))
  on('store.set', ($, e) => (kept.set(e.key, e.value), { value: undefined }))
  on('ui.render', ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    // with no survey, the engine's band may hold nothing
    if (isBandEmpty && e.component === 'AbovePrompt') return h(Box, null)
    // the terminal may keep the hint line its own, live with its pills, and hand the hook an element with no text in it
    if (isHintNative && e.component === 'PromptHint') return h(Box, null)
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

const LINE = 'iirc status  68 pages'
const TODO = '▲ /iirc run-maintenance · 1 near-duplicate pair'

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

// the command that clears a status's first problem, as the card and the line under the prompt name it
const fixOf = (s: IircStatus) => actions(s, counts())[0]?.fix

// a session's counts: none, except what the test names
function counts(some: Partial<SessionCounts> = {}): SessionCounts {
  return { reads: 0, writes: 0, searches: 0, suggested: 0, used: 0, missed: [], match: { all: null, read: null, unread: null }, timeouts: 0, model: null, ...some }
}

// a drawn row as its Text parts: each part's text and the props it is drawn with
function parts(node: unknown): [string, Record<string, unknown>][] {
  const out: [string, Record<string, unknown>][] = []
  const walk = (n: unknown) => {
    if (!n || typeof n !== 'object') return
    const { type, props, children } = n as { type?: string; props?: Record<string, unknown>; children?: unknown[] }
    // a Text of spans is one wrapped run: its spans are the parts
    const isSpans = type === 'Text' && (children ?? []).some(c => c && typeof c === 'object')
    if (type === 'Text' && !isSpans) out.push([(children ?? []).filter(c => typeof c === 'string').join(''), JSON.parse(JSON.stringify(props ?? {}))])
    else for (const c of children ?? []) walk(c)
  }
  walk(node)
  return out
}

// The band above the prompt, mounted fresh each time.
function bandRow($: Engine, hasSurvey = false, bodyColumns = 80) {
  return $.ui.mount({
    plugin: 'iirc',
    surface: 'terminal',
    component: 'AbovePrompt',
    requestId: `band-${++mounts}`,
    props: { hasSurvey, isWorking: false, maxRows: 12, bodyColumns, scroll: { offset: 0, bodyRows: 11 }, view: {} },
  })
}

// Work the module starts on a timer lands a little after the clock settles.
async function waitFor($: Engine, text: string) {
  for (let i = 0; i < 30; i++) {
    if (await (await bandRow($)).find({ text })) return true
    await new Promise(r => setTimeout(r, 10))
  }
  return false
}

test('parses the recall line', () => {
  expect(parseRecall('UserPromptSubmit hook additional context: ' + RECALL)).toEqual([
    { name: 'alpha-page.md', summary: 'first summary (with parens)', isSuspect: false },
    { name: 'beta.md', summary: 'second one', isSuspect: true },
  ])
  expect(parseRecall('iirc: 2 pages may apply. Read a page whose summary bears on this task; skip the rest: `iirc read a.md` (one (x)) [69% match, meaning+term] · `iirc read b.md` (two…) [term match] (suspect: 3 days; if it holds, `iirc verify b.md`)')).toEqual([
    { name: 'a.md', summary: 'one (x)', isSuspect: false, match: '69% match, meaning+term' },
    { name: 'b.md', summary: 'two…', isSuspect: true, match: 'term match' },
  ])
  expect(parseRecall('nothing here')).toEqual([])
})

test('parses the recovery nudge and the brief', () => {
  expect(parseRecovered(RECOVERY)).toEqual([{ command: 'uv tool', failures: 2 }])
  expect(parseBrief(BRIEF)).toEqual({
    status: { level: 'warn', pages: 68, mode: 'semantic+keyword', note: null, problems: [{ level: 'warn', fix: '/iirc run-maintenance', why: 'maintenance is due (1 near-duplicate pair)' }] },
    warnings: ['Maintenance is due (1 near-duplicate pair); run /iirc run-maintenance.'],
  })
  const setup = parseBrief('iirc: not set up on this machine. Ask the creator; then run `iirc add-embedding-model MODEL HOST` with their answer.')!.status
  expect(setup.level).toBe('error')
  expect(statusText(setup, counts())).toBe('iirc status')
  const down = parseBrief('iirc: 5 pages, string only (127.0.0.1:11434 does not answer; `iirc doctor` to check). Topics: x 5.')!
  expect(down.status).toMatchObject({ level: 'warn', pages: 5, mode: 'keyword' })
  expect(fixOf(down.status)).toBe('iirc doctor')
  // a model id may hold a dot; inside the parentheses it does not end the mode
  const unserved = parseBrief('iirc: 5 pages, string only (this machine cannot serve qwen3-embedding-0.6b; `iirc doctor` names the ways out). Topics: x 5.')!
  expect(unserved.status).toMatchObject({ level: 'warn', pages: 5, mode: 'keyword' })
  expect(fixOf(unserved.status)).toBe('iirc doctor')
  expect(unserved.warnings).toEqual([])
  const cpu = parseBrief('iirc: 5 pages, string only (all-minilm-l6-v2 model files missing; `iirc add-embedding-model all-minilm-l6-v2 cpu` to fix).')!
  expect(fixOf(cpu.status)).toBe('iirc add-embedding-model all-minilm-l6-v2 cpu')
  expect(down.warnings).toEqual([])
  expect(statusText(parseBrief('iirc: this repository has no .iirc/. Ask the creator whether to create one; if yes, run `iirc init`.')!.status, counts())).toBe('iirc status')
  expect(fixOf(parseBrief('iirc: 9 pages, semantic via h:1. Maintenance is due (2 suspect pages (a.md, b.md)); run /iirc run-maintenance.')!.status)).toBe('/iirc run-maintenance')
  expect(fixOf(parseBrief('iirc: 9 pages, semantic via h:1. 2 store changes not committed.')!.status)).toBe('/iirc run-maintenance')
  // setup errors keep doctor --fix, even when maintenance is due too
  expect(fixOf(parseBrief('iirc: 9 pages, semantic via h:1. memoryfield-tool is not at the pin abc1234; every write refuses until `iirc doctor --fix` runs. Maintenance is due (1 store commit not pushed); run /iirc run-maintenance.')!.status)).toBe('iirc doctor --fix')
  expect(fixOf(parseBrief('iirc: 9 pages, semantic via h:1. Persistence: .claude/settings.json does not exist. Maintenance is due (1 near-duplicate pair); run /iirc run-maintenance.')!.status)).toBe('iirc doctor --fix')
  expect(parseBrief('iirc: 9 pages, semantic via h:1. Topics: x 9.')!.status).toMatchObject({ level: 'ok' })
  // a host with dots and a path: the mode ends at '. ', not at the first dot
  const dotted = parseBrief('iirc: 9 pages, semantic via llm.example.net/ollama. 2 store changes not committed.')!
  expect(dotted.status).toMatchObject({ level: 'warn', pages: 9, mode: 'semantic+keyword' })
  expect(fixOf(dotted.status)).toBe('/iirc run-maintenance')
  expect(dotted.warnings).toEqual(['2 store changes not committed.'])
  expect(parseBrief('iirc: 9 pages, semantic via llm.example.net/ollama.')!.status).toMatchObject({ level: 'ok', pages: 9, mode: 'semantic+keyword' })
  expect(fixOf(parseBrief("iirc: 9 pages, string only (this machine cannot serve nomic-embed-text; `iirc doctor` names the ways out). This machine's or repository's iirc settings have the old shape; `iirc doctor --fix` converts them.")!.status)).toBe('iirc doctor --fix')
  const one = parseBrief('iirc: 1 page, string search. Topics: x 1.')!.status
  expect(one.level).toBe('ok')
  expect(statusText(one, counts({ reads: 3, writes: 1, suggested: 4, used: 2 }))).toBe('iirc status  2/4 suggested read │ 3 read │ 1 written  string search · 1 page')
  expect(statusText(one, counts())).toBe('iirc status  string search · 1 page')
  expect(statusText(parseBrief("iirc: this repository or machine still uses the memory plugin's layout. Ask the creator whether to migrate; if yes, run `iirc migrate`.")!.status, counts())).toBe('iirc status')
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

test('draws the brief above the prompt and its fix under it, toasts its warnings, and toasts the stop nudge', async ($: Engine, on: On) => {
  engine(on)
  const toast: unknown[] = []
  on('ui.toast', ($, e) => (toast.push(e.text), { value: undefined }))
  expect(await (await hintRow($)).find({ key: 'iirc-todo' })).toBeUndefined()
  expect(await (await bandRow($)).find({ key: 'iirc-line' })).toBeUndefined()
  await hookRow($, 'SessionStart', BRIEF, 'h4')
  await hookRow($, 'Stop', STOP, 'h5')
  const band = await bandRow($)
  expect(await band.find({ text: LINE })).toBeDefined()
  expect(await band.find({ text: 'engine row' })).toBeDefined()
  const row = await hintRow($)
  expect(await row.find({ text: TODO })).toBeDefined()
  expect(await row.find({ text: LINE })).toBeUndefined()
  expect(await row.find({ text: 'engine row' })).toBeDefined()
  expect(toast[0]).toBe('iirc: Maintenance is due (1 near-duplicate pair); run /iirc run-maintenance.')
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
  expect(toast).toEqual(['iirc: Maintenance is due (1 near-duplicate pair); run /iirc run-maintenance.'])
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
  let isRead = false
  on('process.run', ($, e) => {
    argv.push([...e.argv])
    // nothing read until the read below; doctor refreshes the counts too, for the model they carry
    return e.argv.includes('summarize-session-usage') ? ran(JSON.stringify(isRead ? { session: 's1', read: ['a.md', 'b.md'], written: ['c.md'], suggested: ['a.md', 'd.md', 'e.md'], used: ['a.md'] } : { session: 's1' })) : ran(BRIEF)
  })
  on('ui.toast', () => ({ value: undefined }))
  await $.tool.call({ tool: 'Bash', command: 'iirc doctor --brief', tool_use_id: 't6' })
  await clock.settle()
  expect(await waitFor($, LINE)).toBe(true)
  isRead = true
  await $.tool.call({ tool: 'Bash', command: 'iirc read a.md b.md', tool_use_id: 't7' })
  await clock.settle()
  await clock.advance(4000)                                    // past the rise's light
  expect(await waitFor($, 'iirc status  1/3 suggested read │ 2 read │ 1 written')).toBe(true)
  expect(argv.at(-1)?.slice(1)).toEqual(['summarize-session-usage', 's1'])
  // read-matching-pages reads pages too, so it refreshes the counts
  const before = argv.length
  await $.tool.call({ tool: 'Bash', command: 'iirc read-matching-pages ollama', tool_use_id: 't8' })
  await clock.settle()
  expect(argv.slice(before).map(a => a.slice(1))).toContainEqual(['summarize-session-usage', 's1'])
  // a search is counted too
  const searched = argv.length
  await $.tool.call({ tool: 'Bash', command: 'iirc search ollama hangs', tool_use_id: 't8s' })
  await clock.settle()
  expect(argv.slice(searched).map(a => a.slice(1))).toContainEqual(['summarize-session-usage', 's1'])
  // and so is one the person ran with /iirc search
  const direct = argv.length
  await $.command.run({ command: 'iirc', args: 'search ollama' })
  await clock.settle()
  expect(argv.slice(direct).map(a => a.slice(1))).toEqual([['search', 'ollama'], ['summarize-session-usage', 's1']])
})

test('/iirc summary-line-visibility off hides the summary line, on shows it, and other /iirc args reach the skill', async ($: Engine, on: On) => {
  engine(on)
  on('ui.toast', () => ({ value: undefined }))
  await hookRow($, 'SessionStart', BRIEF, 'h7')
  expect(await (await bandRow($)).find({ text: LINE })).toBeDefined()
  expect((await $.command.run({ command: 'iirc', args: 'summary-line-visibility off' })).text).toBe('iirc summary-line-visibility off')
  expect(await (await bandRow($)).find({ text: LINE })).toBeUndefined()
  expect(await (await hintRow($)).find({ text: TODO })).toBeDefined()     // a problem still shows
  expect((await $.command.run({ command: 'iirc', args: 'summary-line-visibility' })).text).toContain('is off')
  expect((await $.command.run({ command: 'iirc', args: 'summary-line-visibility on' })).text).toBe('iirc summary-line-visibility on')
  expect(await (await bandRow($)).find({ text: LINE })).toBeDefined()
  expect((await $.command.run({ command: 'iirc', args: 'what do we know about hooks?' })).text).toBe('the skill ran')
  expect((await $.command.run({ command: 'iirc', args: 'add-remote-store x y' })).text).toBe('the skill ran')
  for (const args of ['run-maintenance', 'run-maintenance --unattended']) expect((await $.command.run({ command: 'iirc', args })).text).toBe('the skill ran')
  for (const old of ['status-line off', 'unfold-suggestions', 'stats', 'thresholds']) expect((await $.command.run({ command: 'iirc', args: old })).text).toBe('the skill ran')
})

test('a plain /iirc prints help with the session line, and does not load the skill', async ($: Engine, on: On) => {
  engine(on)
  on('ui.toast', () => ({ value: undefined }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'a suggestion line names up to 4 pages; ...\n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  await hookRow($, 'SessionStart', BRIEF, 'h8')
  const text = (await $.command.run({ command: 'iirc:iirc', args: '  ' })).text
  expect(text).toContain(LINE.replace(/^iirc status\s+/, ''))
  expect(text).toContain('/iirc help')
  expect(text).not.toContain('the skill ran')
  const helpText = (await $.command.run({ command: 'iirc', args: 'help' })).text
  expect(helpText).toContain('summary line on · max-suggested-pages 4')
  expect(helpText).toContain('/iirc max-suggested-pages N')
  expect(helpText).toContain('/iirc summary-line-visibility ')
  for (const cmd of ['tune-suggestions', 'audit-page-findability', 'set-embedding-model', 'estimate-context-tokens', 'find-suspect-pages', 'rebuild-search-index', 'show-page-topics', 'unfold-suggested-pages', 'show-suggestion-thresholds', 'show-page-stores', 'summarize-page-usage']) expect(helpText).toContain(`/iirc ${cmd} `)
  expect(helpText).toContain('summary line on · max-suggested-pages 4 · search semantic')
  // the help names the mode only when it is string search, and the model otherwise
  expect(searchSetting(parseBrief(BRIEF)!.status, 'qwen3-embedding-0.6b')).toEqual(['model', 'qwen3-embedding-0.6b'])
  expect(searchSetting(parseBrief('iirc: 9 pages, string search. Topics: x 9.')!.status, 'qwen3-embedding-0.6b')).toEqual(['search:', 'string, the fallback'])
  // where a command runs another one, the help says so
  expect(helpText).toMatch(/\/iirc tune-suggestions .*evaluate thresholds/)
  expect(helpText).not.toMatch(/\/iirc tune-suggestions .*audit/)   // auditing is its own step
  expect(helpText).toMatch(/\/iirc doctor --fix .*rebuild the index/)
  expect((helpText ?? '').indexOf('/iirc set-embedding-model')).toBeLessThan((helpText ?? '').indexOf('/iirc doctor'))   // a setting, listed with the others
  // the first maintenance row, before doctor: the one command a person needs
  expect(helpText).toMatch(/\/iirc run-maintenance +the only thing you need to run, weekly/)
  expect((helpText ?? '').indexOf('/iirc run-maintenance')).toBeLessThan((helpText ?? '').indexOf('/iirc doctor'))
  for (const surface of ['terminal', 'desktop'] as const) {
    const panel = await $.ui.mount({
      plugin: 'iirc',
      surface,
      component: 'CommandOutput',
      requestId: `help-${surface}`,
      props: { command: 'iirc:iirc', args: '', text, isErrored: false },
    })
    expect(await panel.find({ text: '68' })).toBeDefined()
    expect(await panel.find({ text: '/iirc help' })).toBeDefined()
    expect(await panel.find({ text: '/iirc doctor --fix' })).toBeUndefined()   // commands live in /iirc help
    expect(await panel.find({ text: 'ecall' })).toBeDefined()
    expect(await panel.find({ text: '/iirc status' })).toBeDefined()
    expect(await panel.find({ text: '▲ needs a look: trust, stores, session counts, and suggestion noise' })).toBeDefined()
    expect(await panel.find({ text: ' ▲ needs a look ' })).toBeUndefined()   // the chip lives in /iirc status
  }
  const demo = await $.ui.mount({
    plugin: 'iirc',
    surface: 'terminal',
    component: 'CommandOutput',
    requestId: 'demo',
    props: { command: 'iirc', args: 'demo', text: 'x', isErrored: false },
  })
  expect(await demo.find({ text: '142' })).toBeDefined()
  expect(await demo.find({ text: '74%' })).toBeDefined()
  expect(await demo.find({ text: 'SUGGESTION HIT RATE · THIS SESSION' })).toBeDefined()
  const other = await $.ui.mount({
    plugin: 'iirc',
    surface: 'terminal',
    component: 'CommandOutput',
    requestId: 'not-help',
    props: { command: 'iirc:iirc', args: 'summary-line-visibility', text: 'iirc summary-line-visibility is on', isErrored: false },
  })
  expect(await other.find({ text: 'up to 4' })).toBeUndefined()
  const status = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'status',
    props: { command: 'iirc', args: 'status', text: 'x', isErrored: false },
  })
  expect(await status.find({ text: '68' })).toBeDefined()
  expect(await status.find({ text: ' ▲ needs a look ' })).toBeDefined()   // /iirc status draws every number
  expect(await status.find({ text: '/iirc run-maintenance' })).toBeDefined()
  expect(await status.find({ text: 'ASK IN WORDS' })).toBeUndefined()
})

test('/iirc doctor, search, and read run the CLI directly', async ($: Engine, on: On) => {
  engine(on)
  const argv: string[][] = []
  on('process.run', ($, e) => (argv.push([...e.argv]), { value: { exitCode: 0, stdout: 'ok  uv on PATH\n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('ui.toast', () => ({ value: undefined }))
  expect((await $.command.run({ command: 'iirc:iirc', args: 'doctor' })).text).toBe('ok  uv on PATH')
  await $.command.run({ command: 'iirc', args: 'search plugin hooks' })
  await $.command.run({ command: 'iirc', args: 'read a.md b.md' })
  expect(argv.map(a => a.slice(1))).toContainEqual(['doctor'])
  expect(argv.map(a => a.slice(1))).toContainEqual(['search', 'plugin hooks'])
  expect(argv.map(a => a.slice(1))).toContainEqual(['read', 'a.md', 'b.md'])
})

const DOCTOR = 'iirc doctor exited 1:\nok  uv on PATH\nFAIL memoryfield-tool at 3e447e1  (iirc doctor --fix)\nnote near-duplicate pages (distance 0.060): a.md | b.md\n     index cache: /x (derived)\nRun `iirc doctor --fix` to repair what it can.'

test('parses doctor lines into checks, failures, notes, and info', () => {
  expect(parseDoctor(DOCTOR)).toEqual({
    ok: ['uv on PATH'],
    failed: [{ label: 'memoryfield-tool at 3e447e1', fix: 'iirc doctor --fix' }],
    notes: ['near-duplicate pages (distance 0.060): a.md | b.md'],
    info: ['index cache: /x (derived)'],
  })
  expect(parseDoctor('something else')).toBeNull()
})

test('/iirc doctor draws a card, and /iirc help draws the help card', async ($: Engine, on: On) => {
  engine(on)
  const doctor = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'doc',
    props: { command: 'iirc', args: 'doctor', text: DOCTOR, isErrored: false },
  })
  expect(await doctor.find({ text: ' ✖ 1 of 2 failed ' })).toBeDefined()
  expect(await doctor.find({ text: 'iirc doctor --fix' })).toBeDefined()
  expect(await doctor.find({ text: 'uv on PATH' })).toBeDefined()
  const help = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'help',
    props: { command: 'iirc', args: 'help', text: 'x', isErrored: false },
  })
  expect(await help.find({ text: '/iirc max-suggested-pages N' })).toBeDefined()
  // tune and audit are maintenance; setup is a setting, shown with the search mode in force
  expect(await help.find({ text: 'WITH CLAUDE' })).toBeUndefined()
  for (const cmd of ['tune-suggestions', 'audit-page-findability', 'set-embedding-model', 'estimate-context-tokens', 'find-suspect-pages', 'rebuild-search-index', 'show-page-topics', 'unfold-suggested-pages', 'show-suggestion-thresholds', 'show-page-stores', 'summarize-page-usage', '<request>']) expect(await help.find({ text: `/iirc ${cmd}` })).toBeDefined()
  expect(await help.find({ text: 'search' })).toBeDefined()
})

test('/iirc max-suggested-pages N asks the CLI to keep the number', async ($: Engine, on: On) => {
  engine(on)
  const argv: string[][] = []
  on('process.run', ($, e) => (argv.push([...e.argv]), { value: { exitCode: 0, stdout: 'a suggestion line names up to 5 pages\n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  expect((await $.command.run({ command: 'iirc:iirc', args: 'max-suggested-pages 5' })).text).toBe('a suggestion line names up to 5 pages')
  expect(argv[0].slice(1)).toEqual(['max-suggested-pages', '5'])
  await $.command.run({ command: 'iirc', args: 'max-suggested-pages' })
  expect(argv[1].slice(1)).toEqual(['max-suggested-pages'])
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

test('finds the pages when the row requestId has the uuid last group zeroed', async ($: Engine, on: On) => {
  engine(on)
  await promptRow($, '40d603b1-96c7-41d7-9dc0-00885dcac635')
  await hookRow($, 'UserPromptSubmit', RECALL, 'h9')
  const ui = await $.ui.mount({
    plugin: 'iirc',
    surface: 'terminal',
    component: 'UserMessage',
    requestId: '40d603b1-96c7-41d7-9dc0-000000000000',
    props: { text: 'a prompt', origin: { kind: 'composer' }, isExpanded: false },
  })
  expect(await ui.find({ text: 'pages suggested' })).toBeDefined()
  await ui.press({ key: 'toggle-40d603b1-96c7-41d7-9dc0' })
  expect(await ui.find({ text: 'alpha-page' })).toBeDefined()
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

test('a plain /iirc shows suspect pages, store state, and pages suggested but not read', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('session.id', () => ({ value: 's1' }))
  on('ui.toast', () => ({ value: undefined }))
  on('process.run', ($, e) => {
    if (e.argv.includes('--health')) {
      return ran(JSON.stringify({ suspect: ['old-fact.md'], stores: [{ name: 'shared', kind: 'remote', pages: 5, uncommitted: 0, unpushed: 2 }], due: ['1 suspect page (old-fact.md)', '2 store commits not pushed'] }))
    }
    if (e.argv.includes('summarize-session-usage')) {
      return ran(JSON.stringify({ read: ['a.md'], written: [], suggested: ['a.md', 'noisy.md'], used: ['a.md'], missed: [['noisy.md', 4]], match: { all: 62, read: 75, unread: 49 } }))
    }
    return ran(BRIEF)
  })
  await $.tool.call({ tool: 'Bash', command: 'iirc read a.md', tool_use_id: 't9' })
  await clock.settle()
  await hookRow($, 'SessionStart', BRIEF, 'h9')
  const text = (await $.command.run({ command: 'iirc', args: 'status' })).text
  expect(text).toContain('trust: 1 suspect: old-fact.md; fix with /iirc run-maintenance')
  expect(text).toContain('stores: shared 5 pages, 2 not pushed; fix with /iirc run-maintenance')
  expect(text).toContain('suggested, not read: noisy.md ×4')
  expect(text).toContain('average match: 62% · read 75% · not read 49%')
  const card = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'health',
    props: { command: 'iirc', args: 'status', text, isErrored: false },
  })
  expect(await card.find({ text: '1 suspect page: a cited file changed' })).toBeDefined()
  expect(await card.find({ text: 'old-fact' })).toBeDefined()
  expect(await card.find({ text: ' 5 pages, 2 not pushed' })).toBeDefined()
  expect(await card.find({ text: '/iirc run-maintenance' })).toBeDefined()
  expect(await card.find({ text: 'iirc sync' })).toBeUndefined()
  expect(await card.find({ text: 'iirc find-suspect-pages' })).toBeUndefined()
  expect(await card.find({ key: 'card-m-noisy.md' })).toBeDefined()           // a link to the reader
  expect(await card.find({ key: 'card-s-old-fact.md' })).toBeDefined()
  expect(await card.find({ text: '×4' })).toBeDefined()
  expect(await card.find({ text: '62%' })).toBeDefined()
  expect(await card.find({ text: ' · not read ' })).toBeDefined()
})


test('a config error reads as hooks off, and a timed-out recall turns the line yellow', () => {
  const off = parseBrief('iirc: hooks off, .claude/iirc.toml: [suggestions.nomic-embed-text] semantic_only must be a number from 0.1 to 0.6. Every iirc hook stays quiet until it is fixed; run `iirc doctor --fix`.')!
  expect(off.status.level).toBe('error')
  expect(statusText(off.status, counts())).toBe('iirc status')
  const ok = parseBrief('iirc: 9 pages, semantic via 127.0.0.1:11434. A hook names matching pages when the creator prompts; read one whose summary bears on the task.')!.status
  const c = counts({ reads: 1, suggested: 2, used: 1, timeouts: 2 })
  expect(liveStatus(ok, c).level).toBe('warn')
  expect(statusText(ok, c)).toBe('iirc status  1/2 suggested read │ 1 read  9 pages')
  const brief = parseBrief('iirc: 9 pages, semantic via 127.0.0.1:11434. Maintenance is due (3 suggestion lookups timed out this week); run /iirc run-maintenance.')!
  expect(brief.status.level).toBe('warn')
  expect(fixOf(brief.status)).toBe('/iirc run-maintenance')
})

test('/iirc reader opens the Session tab; a page name opens the reader tab, a linked page replaces it, Back returns', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const opened: string[] = []
  on('ui.open', ($, e) => (opened.push(`${e.id}:${e.title}`), { value: { isPlaced: true } }))
  on('session.id', () => ({ value: 's1' }))
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  const shown: string[] = []
  on('process.run', ($, e) => {
    if (e.argv.includes('show')) {
      const name = e.argv[e.argv.length - 1]
      shown.push(name)
      return ran(JSON.stringify({
        store: 'project', name, label: name, path: `/repo/.iirc/${name}`, body: `Body of ${name}`,
        fm: { title: `Title of ${name}`, kind: 'finding', summary: 'one line', topics: ['x'], updated: '2026-10-01T00:00:00Z' },
        links: name === 'a.md' ? ['b.md'] : [], signals: [],
      }))
    }
    if (e.argv.includes('--health')) return ran(JSON.stringify({ suspect: ['old.md'], stores: [] }))
    if (e.argv.includes('summarize-session-usage')) {
      return ran(JSON.stringify({ read: ['a.md'], written: ['w.md'], suggested: ['a.md', 'n.md', 'old-name.md'], used: ['a.md'], missed: [['n.md', 3]], match: {}, timeouts: 0, gone: ['old-name.md'] }))
    }
    return ran(BRIEF)
  })
  expect((await $.command.run({ command: 'iirc', args: 'reader' })).text).toContain('iirc reader opened')
  await clock.settle()
  expect(opened).toEqual(['iirc:iirc reader'])
  const pane = (requestId: string, title: string) => $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId,
    props: { title, isFocused: true, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
  })
  const view = await pane('iirc', 'iirc')
  expect(await view.find({ text: '×3' })).toBeDefined()
  expect(await view.find({ text: 'w' })).toBeDefined()                       // written
  expect(await view.find({ key: 'open-x-old.md' })).toBeDefined()           // suspect
  expect(await view.find({ key: 'tab-page' })).toBeUndefined()              // no page tab until a page is open
  expect(await view.find({ text: '  renamed or deleted' })).toBeDefined()
  expect(await view.find({ key: 'open-s-old-name.md' })).toBeUndefined()    // a renamed page is no link
  await view.press({ key: 'open-s-a.md' })
  expect(shown).toEqual(['a.md'])
  expect(opened).toEqual(['iirc:iirc reader', 'iirc:iirc reader'])                        // the same pane, never a second one
  expect(await view.find({ text: 'Title of a.md' })).toBeDefined()
  expect(await view.find({ text: 'one line' })).toBeDefined()
  expect(await view.find({ key: 'back' })).toBeUndefined()                  // nothing to go back to yet
  await view.press({ key: 'link-b.md' })
  expect(await view.find({ text: 'Title of b.md' })).toBeDefined()
  expect(await view.find({ key: 'back' })).toBeDefined()
  await view.press({ key: 'back' })
  expect(shown).toEqual(['a.md', 'b.md', 'a.md'])
  expect(await view.find({ text: 'Title of a.md' })).toBeDefined()
  expect(await view.find({ key: 'back' })).toBeUndefined()
  // the tab row switches without losing the page, and the close mark drops it
  await view.press({ key: 'tab-session' })
  expect(await view.find({ text: 'Title of a.md' })).toBeUndefined()
  expect(await view.find({ key: 'open-s-n.md' })).toBeDefined()
  await view.press({ key: 'tab-page' })
  expect(await view.find({ text: 'Title of a.md' })).toBeDefined()
  await view.press({ key: 'key-x' })
  expect(await view.find({ key: 'tab-page' })).toBeUndefined()            // x closes the page tab
  expect(await view.find({ key: 'key-x' })).toBeUndefined()

})

// A press's open is the person's, and Claude Code seats it at any width, only while the press is still running:
// the open must be the press handler's first call on the engine, before any state write or process run
function recordCalls(on: On, order: string[], health = '{"suspect":[],"stores":[]}') {
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('ui.open', ($, e) => (order.push(`open ${e.id}`), { value: { isPlaced: true } }))
  on('state.set', ($, e, next) => (order.push('state'), next(e)))
  on('process.run', ($, e) => {
    order.push('run')
    if (e.argv.includes('--health')) return ran(health)
    if (e.argv.includes('show')) return ran(JSON.stringify({ store: 'project', name: 'a.md', label: 'a.md', path: '/p', fm: {}, body: 'b', links: [], signals: [] }))
    return ran(OK_BRIEF)
  })
}

test('every press that opens the pane opens it before anything else: the band, a suggested page, a card\'s page', async ($: Engine, on: On) => {
  engine(on)
  const order: string[] = []
  on('ui.toast', () => ({ value: undefined }))
  recordCalls(on, order, JSON.stringify({ suspect: ['old.md'], stores: [] }))
  on('ui.close', () => ({ value: undefined }))
  await hookRow($, 'SessionStart', OK_BRIEF, 'ho1')
  // the band
  const band = await bandRow($)
  order.length = 0
  await band.press({ key: 'iirc-open' })
  expect(order[0]).toBe('open iirc')
  // a suggested page under a prompt
  await promptRow($, 'p-order')
  await hookRow($, 'UserPromptSubmit', 'iirc: 1 page may apply. Read a page whose summary bears on this task; skip the rest: `iirc read a.md` (one)', 'h-order')
  await $.command.run({ command: 'iirc', args: 'unfold-suggested-pages' })
  const row = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'UserMessage', requestId: 'p-order', props: { text: 'a prompt' } as never })
  order.length = 0
  await row.press({ key: 'open-p-order-0-0-1' })
  expect(order[0]).toBe('open iirc')
  // a page the /iirc status card names
  const text = (await $.command.run({ command: 'iirc', args: 'status' })).text
  const card = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'card-order', props: { command: 'iirc', args: 'status', text, isErrored: false } })
  order.length = 0
  await card.press({ key: 'card-s-old.md' })
  expect(order[0]).toBe('open iirc')
  // after the pane closes (here its own q: the test kit raises no person close), Claude Code forgets the person
  // opened it, so the 110-column floor no longer helps; a press is still theirs, the open first, at any width
  const pane = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId: 'iirc',
    props: { title: 'iirc', isFocused: true, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} } })
  await pane.press({ key: 'key-q' })
  order.length = 0
  await (await bandRow($)).press({ key: 'iirc-open' })
  expect(order[0]).toBe('open iirc')
})

test('a page name in the suggested-pages tree opens the reader', async ($: Engine, on: On) => {
  engine(on)
  const opened: string[] = []
  on('ui.open', ($, e) => (opened.push(`${e.id}:${e.title}`), { value: { isPlaced: true } }))
  on('process.run', ($, e) => ({ value: { exitCode: 0, stdout: JSON.stringify({ store: 'project', name: 'pysqlite3-install-override.md', label: 'pysqlite3-install-override.md', path: '/p', fm: {}, body: 'b', links: [], signals: [] }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  await promptRow($, 'p-tree')
  await hookRow($, 'UserPromptSubmit', 'iirc: 1 page may apply. Read a page whose summary bears on this task; skip the rest: `iirc read pysqlite3-install-override.md` (the uv override) [69% match, meaning+term]', 'h-tree')
  const row = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'UserMessage', requestId: 'p-tree', props: { text: 'a prompt' } as never })
  expect(await row.find({ key: 'open-p-tree-0-0-1' })).toBeUndefined()      // folded
  expect((await $.command.run({ command: 'iirc', args: 'unfold-suggested-pages' })).text).toContain('unfolded')
  expect(await row.find({ key: 'open-p-tree-0-0-1' })).toBeDefined()        // /iirc unfold-suggested-pages unfolds the latest row
  await row.press({ key: 'open-p-tree-0-0-1' })
  expect(opened).toEqual(['iirc:iirc reader'])
})


test('paragraphs split a body at blank lines and keep a fenced block whole', () => {
  expect(paragraphs('One.\n\nTwo\nlines.\n\n```\na\n\nb\n```\n\n- x\n- y\n')).toEqual(['One.', 'Two\nlines.', '```\na\n\nb\n```', '- x\n- y'])
})

test('vi keys: the cursor starts on the first page name; j and k move it; g and e jump; in a page, j steps by paragraph', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.id', () => ({ value: 's1' }))
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('process.run', ($, e) => {
    if (e.argv.includes('show')) {
      return ran(JSON.stringify({ store: 'project', name: 'a.md', label: 'a.md', path: '/p', fm: { title: 'A' }, body: 'First.\n\nSecond.', links: ['b.md'], signals: [] }))
    }
    if (e.argv.includes('--health')) return ran(JSON.stringify({ suspect: [], stores: [] }))
    if (e.argv.includes('summarize-session-usage')) return ran(JSON.stringify({ read: ['a.md'], written: [], suggested: ['a.md', 'n.md', 'gone.md'], used: ['a.md'], missed: [['n.md', 2]], match: {}, timeouts: 0, gone: ['gone.md'] }))
    return ran(BRIEF)
  })
  await $.command.run({ command: 'iirc', args: 'reader' })
  await clock.settle()
  const view = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId: 'iirc',
    props: { title: 'iirc', isFocused: true, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
  })
  // the drawn cursor sits in the row of the page it is on: the row's first Text
  const cursorOn = async () => {
    for (const name of ['a', 'n']) {
      const row = await view.find({ key: `s-${name}.md` })
      if (row && JSON.stringify(row).includes('"▶"')) return name
    }
    return null
  }
  expect(await cursorOn()).toBe('a')
  await view.press({ key: 'key-j' })
  expect(await cursorOn()).toBe('n')
  await view.press({ key: 'key-j' })                          // the renamed page is no stop: it stays on the last
  expect(await cursorOn()).toBe('n')
  await view.press({ key: 'key-k' })
  expect(await cursorOn()).toBe('a')
  await view.press({ key: 'key-e' })
  expect(await cursorOn()).toBe('n')
  await view.press({ key: 'key-g' })
  expect(await cursorOn()).toBe('a')
  await view.press({ key: 'open-s-a.md' })
  const paraOn = async () => {
    for (const i of [0, 1]) {
      const box = await view.find({ key: `p-${i}` })
      if (box && JSON.stringify(box).includes('"▶"')) return i
    }
    return null
  }
  expect(await paraOn()).toBe(0)
  await view.press({ key: 'key-j' })
  expect(await paraOn()).toBe(1)
  await view.press({ key: 'key-j' })                          // past the paragraphs: the linked page
  expect(await paraOn()).toBe(null)
  await view.press({ key: 'key-h' })
  expect(await view.find({ key: 'open-s-n.md' })).toBeDefined()
  await view.press({ key: 'key-l' })
  expect(await view.find({ text: 'A' })).toBeDefined()
})


test('the tab row and the keys stay on top while j scrolls the list under them; q closes the pane', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  const closed: string[] = []
  on('ui.close', ($, e) => (closed.push(e.id), { value: undefined }))
  on('session.id', () => ({ value: 's1' }))
  const names = Array.from({ length: 12 }, (_, i) => `p${i}.md`)
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('process.run', ($, e) => {
    if (e.argv.includes('--health')) return ran(JSON.stringify({ suspect: [], stores: [] }))
    if (e.argv.includes('summarize-session-usage')) return ran(JSON.stringify({ read: [], written: [], suggested: names, used: [], missed: [], match: {}, timeouts: 0, gone: [] }))
    return ran(BRIEF)
  })
  await $.command.run({ command: 'iirc', args: 'reader' })
  await clock.settle()
  // eight rows: three for the header, five for the list
  const view = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId: 'iirc',
    props: { title: 'iirc', isFocused: true, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 8 }, view: {} },
  })
  expect(await view.find({ text: '↑ 1 above' })).toBeUndefined()
  for (let i = 0; i < 8; i++) await view.press({ key: 'key-j' })
  expect(await view.find({ key: 'tab-session' })).toBeDefined()              // the header stays
  expect(await view.find({ key: 'key-q' })).toBeDefined()
  expect(await view.find({ key: 'open-s-p8.md' })).toBeDefined()             // the cursor's row is in view
  expect(await view.find({ key: 'open-s-p0.md' })).toBeUndefined()           // the top of the list scrolled away
  expect(JSON.stringify(await view.find({ key: 's-p8.md' }))).toContain('"▶"')
  await view.press({ key: 'key-g' })
  expect(await view.find({ text: 'SUGGESTED' })).toBeDefined()             // g shows the very top; the pane has no counts
  expect(await view.find({ text: '  ↑ 1 above' })).toBeUndefined()
  await view.press({ key: 'key-q' })
  expect(closed).toEqual(['iirc'])
})

test('/iirc show PAGE draws the page as a card in the transcript', async ($: Engine, on: On) => {
  engine(on)
  on('session.id', () => ({ value: 's1' }))
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('process.run', ($, e) => (e.argv.includes('show')
    ? ran(JSON.stringify({ store: 'project', name: 'a.md', label: 'a.md', path: '/p', fm: { title: 'Title of a', kind: 'finding', summary: 'one line' }, body: 'First.\n\nSecond.', links: [], signals: [] }))
    : ran(BRIEF)))
  const showText = (await $.command.run({ command: 'iirc', args: 'show a.md' })).text
  expect(showText).toContain('Title of a')
  const pageCard = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'show-a', props: { command: 'iirc', args: 'show a.md', text: showText, isErrored: false } })
  expect(await pageCard.find({ text: 'Title of a' })).toBeDefined()
  expect(await pageCard.find({ text: ' finding ' })).toBeDefined()
  expect(await pageCard.find({ key: 'para-1' })).toBeDefined()
})

test('the status card is never wider than the terminal', async ($: Engine, on: On) => {
  engine(on)
  on('ui.toast', () => ({ value: undefined }))
  const mount = (requestId: string, columns: number) => $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId,
    viewport: { columns, rows: 30 }, props: { command: 'iirc', args: 'demo status', text: 'x', isErrored: false } } as never)
  const widthOf = async (requestId: string, columns: number) => {
    const card = await (await mount(requestId, columns)).find({ key: 'card' })
    return (card as { props?: { width?: number } } | undefined)?.props?.width
  }
  expect(await widthOf('narrow', 40)).toBe(40)
  const narrow = await mount('narrow-tagline', 40)
  expect(await narrow.find({ text: '…' })).toBeDefined()                 // the tagline is cut, not squeezed letter by letter
  expect(await widthOf('wide', 200)).toBeLessThan(200)          // a wide terminal: as wide as the widest row
})

test('every row of the help fits an 80-column terminal', async ($: Engine, on: On) => {
  engine(on)
  on('ui.toast', () => ({ value: undefined }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'a suggestion line names up to 10 pages\n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  // on a wide terminal the card is as wide as its widest row, so a card of 80 or less fits 80 columns unclamped
  const card = await (await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'help-80',
    viewport: { columns: 200, rows: 40 }, props: { command: 'iirc', args: 'help', text: 'x', isErrored: false } } as never)).find({ key: 'card' })
  expect((card as { props?: { width?: number } } | undefined)?.props?.width).toBeLessThanOrEqual(80)
  const text = (await $.command.run({ command: 'iirc', args: 'help' })).text ?? ''
  for (const line of text.split('\n')) expect(line.length).toBeLessThanOrEqual(76)
})


test('without the keys, the pane says so and how to get them', async ($: Engine, on: On) => {
  engine(on)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.id', () => ({ value: 's1' }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: '{}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  const pane = (requestId: string, isFocused: boolean) => $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId,
    props: { title: 'iirc', isFocused, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} },
  })
  const off = await pane('iirc', false)
  expect(await off.find({ text: 'keys off ' })).toBeDefined()
  expect(await off.find({ key: 'key-j' })).toBeUndefined()
})

test('the keys row is one line: labels in a wide pane, glyphs alone in a narrow one', async ($: Engine, on: On) => {
  engine(on)
  on('session.id', () => ({ value: 's1' }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: '{}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  const pane = (requestId: string, bodyColumns: number) => $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId,
    props: { title: 'iirc', isFocused: true, bodyColumns, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} },
  })
  const wide = await pane('iirc', 80)
  expect(await wide.find({ text: 'top' })).toBeDefined()
  expect(await wide.find({ text: '⤒' })).toBeUndefined()
})


test('/iirc reader opens fresh: no page tab is left from before', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.id', () => ({ value: 's1' }))
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('process.run', ($, e) => (e.argv.includes('show')
    ? ran(JSON.stringify({ store: 'project', name: 'a.md', label: 'a.md', path: '/p', fm: { title: 'A' }, body: 'b', links: [], signals: [] }))
    : e.argv.includes('summarize-session-usage') ? ran(JSON.stringify({ read: [], written: [], suggested: ['a.md'], used: [], missed: [], match: {}, timeouts: 0, gone: [] }))
    : ran('{"suspect": [], "stores": []}')))
  await $.command.run({ command: 'iirc', args: 'reader' })
  await clock.settle()
  const view = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId: 'iirc',
    props: { title: 'iirc', isFocused: true, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} } })
  await view.press({ key: 'open-s-a.md' })
  expect(await view.find({ key: 'tab-page' })).toBeDefined()
  await $.command.run({ command: 'iirc', args: 'reader' })
  expect(await view.find({ key: 'tab-page' })).toBeUndefined()
})

test('/iirc reader PAGE opens the reader on that page, over a fresh session tab', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const opened: string[] = []
  on('ui.open', ($, e) => (opened.push(`${e.id}:${e.title}`), { value: { isPlaced: true } }))
  on('session.id', () => ({ value: 's1' }))
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('process.run', ($, e) => (e.argv.includes('show')
    ? ran(JSON.stringify({ store: 'project', name: 'a.md', label: 'a.md', path: '/p', fm: { title: 'Title of a' }, body: 'b', links: [], signals: [] }))
    : e.argv.includes('summarize-session-usage') ? ran(JSON.stringify({ read: [], written: [], suggested: ['a.md'], used: [], missed: [], match: {}, timeouts: 0, gone: [] }))
    : ran('{"suspect": [], "stores": []}')))
  expect((await $.command.run({ command: 'iirc', args: 'reader a.md' })).text).toBe('iirc reader opened on a.md')
  await clock.settle()
  expect(opened[0]).toBe('iirc:iirc reader')
  const view = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId: 'iirc',
    props: { title: 'iirc reader', isFocused: true, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} } })
  expect(await view.find({ text: 'Title of a' })).toBeDefined()
  expect(await view.find({ key: 'tab-session' })).toBeDefined()
})

test('near the auto-compact threshold, hands the model the write nudge once per compaction, and the summary keeps what is unwritten', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const NUDGE = 'iirc: context compaction is near. Write what you learned.'
  const SUMMARY = 'List each unwritten finding.'
  const asked: { argv: string[]; stdin?: string }[] = []
  const toast: string[] = []
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('session.id', () => ({ value: 's1' }))
  on('process.run', ($, e) => {
    asked.push({ argv: [...e.argv], stdin: e.init?.stdin })
    return e.argv.includes('compaction') ? ran(NUDGE + '\n') : e.argv.includes('show-compaction-instructions') ? ran(SUMMARY + '\n') : ran('')
  })
  on('ui.toast', ($, e) => (toast.push(e.text), { value: undefined }))
  // auto-compaction at 160,000 tokens of a 200,000 window
  let tokens = 0
  const context = () => ({ tokens, window: 200_000, percent: Math.round(tokens / 2000) })
  on('session.usage', () => ({ value: { startedAt: 0, rateLimits: [], context: { ...context(), breakdown: { autoCompactThreshold: 160_000, isAutoCompactEnabled: true } as never } } }))
  const measure = async (t: number) => {
    tokens = t
    await $.session.measure({ context: context(), rateLimits: [], changed: ['context'] })
    await clock.settle()
  }
  const instructions: (string | undefined)[] = []
  const summary = [{ role: 'user' as const, text: 'the summary', toolUses: [] }]
  on('session.compact', ($, e) => (instructions.push(e.instructions), { messages: summary }))
  on('prompt.submit', ($, e) => ({ text: e.text, context: e.context }))
  on('session.measure', ($, e) => ({ changed: e.changed }))
  const prompt = async () => (await $.prompt.submit({ text: 'go on', wait: false, origin: { kind: 'composer' } })).context ?? []
  const nudges = () => asked.filter(a => a.argv.includes('compaction'))

  await measure(100_000)
  expect(nudges()).toHaveLength(0)                     // far from the threshold: iirc is not asked
  expect(await prompt()).toEqual([])
  await measure(140_000)                               // 87.5% of the threshold: not yet
  expect(nudges()).toHaveLength(0)
  await measure(145_000)                               // past 90% of the threshold
  expect(nudges()).toHaveLength(1)
  expect(nudges()[0]?.argv.slice(1)).toEqual(['remind-to-write', '--at', 'compaction'])
  expect(JSON.parse(nudges()[0]?.stdin ?? '{}')).toEqual({ session_id: 's1' })
  await measure(150_000)
  expect(nudges()).toHaveLength(1)                     // asked once per compaction window
  const tool = await $.tool.call({ tool: 'Bash', command: 'ls', tool_use_id: 'c1' })
  expect('context' in tool ? tool.context : undefined).toEqual([NUDGE])   // the first tool result after it carries the line
  expect(toast.some(t => t.includes('compaction'))).toBe(true)
  expect(await prompt()).toEqual([])                   // and only that one

  await measure(155_000)
  await $.session.compact({ trigger: 'auto', instructions: 'keep the plan', messages: summary })
  expect(instructions.at(-1)).toBe(`keep the plan\n\n${SUMMARY}`)
  await $.session.compact({ trigger: 'precompute', messages: summary })
  expect(instructions.at(-1)).toBe(SUMMARY)

  await measure(146_000)                               // a new window after the compaction
  expect(nudges()).toHaveLength(2)
  expect(await prompt()).toEqual([NUDGE])              // a prompt carries it when it comes first
})


test('the status chip turns yellow when the CLI says maintenance is due, and only then', async ($: Engine, on: On) => {
  engine(on)
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  const OK = 'iirc: 9 pages, semantic via 127.0.0.1:11434. A hook names matching pages when the creator prompts; read one whose summary bears on the task.'
  let due: string[] = ['no run in the last 30 days, 6 sessions']
  on('ui.toast', () => ({ value: undefined }))
  on('process.run', ($, e) => e.argv.includes('--health')
    ? ran(JSON.stringify({ suspect: [], stores: [{ name: 'project', kind: 'project', pages: 9, uncommitted: 0, unpushed: 0 }], due }))
    : ran(OK))
  await hookRow($, 'SessionStart', OK, 'hd1')
  const chip = async (requestId: string) => {
    const text = (await $.command.run({ command: 'iirc', args: 'status' })).text
    return $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId, props: { command: 'iirc', args: 'status', text, isErrored: false } })
  }
  const due1 = await chip('due-1')
  expect(await due1.find({ text: ' ▲ needs a look ' })).toBeDefined()
  expect(await due1.find({ text: '/iirc run-maintenance' })).toBeDefined()
  due = []
  expect(await (await chip('due-0')).find({ text: ' ✔ all good ' })).toBeDefined()
})

test('/iirc reader demo draws its sample numbers in the pane only; the summary line and a drawn card keep the real ones', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  const names = Array.from({ length: 12 }, (_, i) => `page-${i}.md`)
  on('session.id', () => ({ value: 's1' }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('process.run', ($, e) => {
    if (e.argv[0] === 'ls') return ran(['index.md', ...names].join('\n'))
    if (e.argv.includes('--health')) return ran(JSON.stringify({ suspect: [], stores: [{ name: 'project', kind: 'project', pages: 68, uncommitted: 0, unpushed: 0 }] }))
    if (e.argv.includes('summarize-session-usage')) {
      return ran(JSON.stringify({ read: ['a.md'], written: [], suggested: ['a.md', 'noisy.md'], used: ['a.md'], missed: [['noisy.md', 4]], match: { all: 62, read: 75, unread: 49 } }))
    }
    return ran(BRIEF)
  })
  await $.tool.call({ tool: 'Bash', command: 'iirc read a.md', tool_use_id: 'td1' })
  await clock.settle()
  await hookRow($, 'SessionStart', BRIEF, 'hd2')
  const REAL = 'iirc status  1/2 suggested read │ 1 read'
  expect(await waitFor($, REAL)).toBe(true)
  const text = (await $.command.run({ command: 'iirc', args: 'status' })).text
  const card = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'card-before-demo',
    props: { command: 'iirc', args: 'status', text, isErrored: false },
  })
  expect(await card.find({ text: '62%' })).toBeDefined()
  await $.command.run({ command: 'iirc', args: 'reader demo' })
  await clock.settle()
  const pane = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId: 'iirc',
    props: { title: 'iirc', isFocused: true, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} } })
  expect(await pane.find({ key: 'open-s-page-0.md' })).toBeDefined()        // the demo's pages, in the pane
  expect(await pane.find({ text: '×4' })).toBeDefined()
  // the summary line and the card drawn before the demo keep the real numbers
  expect(await (await bandRow($)).find({ text: '6/10 suggested read' })).toBeUndefined()
  expect(await waitFor($, REAL)).toBe(true)
  expect(await card.find({ text: '62%' })).toBeDefined()
  expect(await card.find({ text: '68%' })).toBeUndefined()
  // a plain reader after the demo shows the real session again
  await $.command.run({ command: 'iirc', args: 'reader' })
  await clock.settle()
  expect(await pane.find({ key: 'open-s-page-0.md' })).toBeUndefined()
  expect(await pane.find({ key: 'open-s-noisy.md' })).toBeDefined()
})

test('/iirc demo doctor draws the doctor card from sample checks and never runs doctor', async ($: Engine, on: On) => {
  engine(on)
  const argv: string[][] = []
  on('process.run', ($, e) => (argv.push([...e.argv]), { value: { exitCode: 1, stdout: 'FAIL a real failure on this machine', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('ui.toast', () => ({ value: undefined }))
  const text = (await $.command.run({ command: 'iirc', args: 'demo doctor' })).text
  expect(argv.map(a => a.slice(1))).not.toContainEqual(['doctor'])
  expect(parseDoctor(text)).not.toBeNull()
  const card = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'demo-doctor',
    props: { command: 'iirc', args: 'demo doctor', text, isErrored: false },
  })
  expect(await card.find({ text: ' ✖ 1 of 13 failed ' })).toBeDefined()
  expect(await card.find({ text: 'NOTES' })).toBeDefined()
  expect(await card.find({ text: 'a real failure on this machine' })).toBeUndefined()  // spaced as /iirc demo  status may be
  const spaced = (await $.command.run({ command: 'iirc', args: 'demo  doctor' })).text
  expect(spaced).toBe(text)
  const spacedCard = await $.ui.mount({
    plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'demo-doctor-spaced',
    props: { command: 'iirc', args: 'demo  doctor', text: spaced, isErrored: false },
  })
  expect(await spacedCard.find({ text: ' ✖ 1 of 13 failed ' })).toBeDefined()
})

// a session with real numbers and twelve page names for the demo, for the tests of how the demo ends
function demoFixture(on: On, placed: () => boolean) {
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  const names = Array.from({ length: 12 }, (_, i) => `page-${i}.md`)
  on('session.id', () => ({ value: 's1' }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.open', () => ({ value: placed() ? { isPlaced: true } : { isPlaced: false, reason: 'the terminal is too narrow' } }))
  on('ui.close', () => ({ value: undefined }))
  on('process.run', ($, e) => {
    if (e.argv[0] === 'ls') return ran(['index.md', ...names].join('\n'))
    if (e.argv.includes('show')) {
      const name = e.argv[e.argv.length - 1]
      return ran(JSON.stringify({ store: 'project', name, label: name, path: `/repo/.iirc/${name}`, body: 'b', fm: { title: name }, links: [], signals: [] }))
    }
    if (e.argv.includes('--health')) return ran(JSON.stringify({ suspect: [], stores: [] }))
    if (e.argv.includes('summarize-session-usage')) {
      return ran(JSON.stringify({ read: ['a.md'], written: [], suggested: ['a.md', 'noisy.md'], used: ['a.md'], missed: [['noisy.md', 4]], match: { all: 62, read: 75, unread: 49 } }))
    }
    return ran(BRIEF)
  })
}

const readerPane = ($: Engine, requestId = 'iirc') => $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'Pane', requestId,
  props: { title: 'iirc', isFocused: true, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} } })

test('q in the demo reader drops the demo: a page opened later shows the real session a tab away', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  demoFixture(on, () => true)
  await $.tool.call({ tool: 'Bash', command: 'iirc read a.md', tool_use_id: 'tq1' })
  await clock.settle()
  await $.command.run({ command: 'iirc', args: 'reader demo' })
  await clock.settle()
  const pane = await readerPane($)
  expect(await pane.find({ key: 'open-s-page-0.md' })).toBeDefined()
  await pane.press({ key: 'key-q' })
  const text = (await $.command.run({ command: 'iirc', args: 'status' })).text
  const card = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'card-after-q',
    props: { command: 'iirc', args: 'status', text, isErrored: false } })
  await card.press({ key: 'card-m-noisy.md' })
  await clock.settle()
  // the same Pane mount: Claude Code draws the reopened pane into it
  await pane.press({ key: 'tab-session' })
  expect(await pane.find({ key: 'open-s-page-0.md' })).toBeUndefined()
  expect(await pane.find({ key: 'open-s-noisy.md' })).toBeDefined()
})

test('a demo reader that Claude Code did not place leaves no demo behind', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  let placed = false
  demoFixture(on, () => placed)
  await $.tool.call({ tool: 'Bash', command: 'iirc read a.md', tool_use_id: 'tp1' })
  await clock.settle()
  await $.command.run({ command: 'iirc', args: 'reader demo' })
  await clock.settle()
  placed = true
  const text = (await $.command.run({ command: 'iirc', args: 'status' })).text
  const card = await $.ui.mount({ plugin: 'iirc', surface: 'terminal', component: 'CommandOutput', requestId: 'card-unplaced',
    props: { command: 'iirc', args: 'status', text, isErrored: false } })
  await card.press({ key: 'card-m-noisy.md' })
  await clock.settle()
  const pane = await readerPane($)
  await pane.press({ key: 'tab-session' })
  expect(await pane.find({ key: 'open-s-page-0.md' })).toBeUndefined()
  expect(await pane.find({ key: 'open-s-noisy.md' })).toBeDefined()
})


// the summary line above the prompt: a circle in the level's color, the accent bar, "iirc status", then what this session did
const OK_BRIEF = 'iirc: 110 pages, semantic via 127.0.0.1:11434. Topics: x 110.'
// "iirc status" a letter at a time along the card's gradient, from the accent orange to violet
const hex = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16))
const step = (t: number) => '#' + hex('#e8875f').map((v, i) => Math.round(v + (hex('#a78bfa')[i] - v) * t).toString(16).padStart(2, '0')).join('')
const WORDMARK: [string, Record<string, unknown>][] = [...'iirc status'].map((ch, k) => [ch, { bold: true, color: step(k / 10) }])
const head = (level: string): [string, Record<string, unknown>][] => [['● ', { color: level }], ['▍', { color: '#e8875f' }], ...WORDMARK]
const num = (n: string): [string, Record<string, unknown>] => [n, { bold: true, color: 'claude' }]
const word = (w: string): [string, Record<string, unknown>] => [w, { color: 'subtle' }]
const SP: [string, Record<string, unknown>] = ['  ', {}]
const DOT = word(' │ ')
const LINE_EXAMPLES: { name: string; usage: Record<string, unknown> | null; text: string; drawn: [string, Record<string, unknown>][]; todo: string }[] = [
  {
    name: 'a quiet session shows the page count',
    usage: null,
    text: 'iirc status  110 pages',
    drawn: [...head('success'), ['  ', {}], ['110 pages', { color: 'subtle' }]],
    todo: '',
  },
  {
    name: 'a busy session shows the suggested pages read and the counters, with no gauge',
    usage: { read: ['a.md', 'b.md', 'c.md'], written: ['w.md'], suggested: ['a.md', 'b.md', 'x.md', 'y.md', 'z.md'], used: ['a.md', 'b.md'], searches: 4, timeouts: 0 },
    text: 'iirc status  2/5 suggested read │ 4 searched │ 3 read │ 1 written  110 pages',
    drawn: [
      ...head('success'), SP, num('2'), num('/'), num('5'), word(' suggested read'), DOT, num('4'), word(' searched'), DOT, num('3'), word(' read'), DOT, num('1'), word(' written'), ['  ', {}], ['110 pages', { color: 'subtle' }],
    ],
    todo: '',
  },
  {
    name: 'a timed-out recall turns the circle yellow and asks for maintenance under the prompt',
    usage: { read: ['a.md', 'b.md', 'c.md'], written: [], suggested: [], used: [], searches: 0, timeouts: 1 },
    text: 'iirc status  3 read  110 pages',
    drawn: [...head('warning'), SP, num('3'), word(' read'), ['  ', {}], ['110 pages', { color: 'subtle' }]],
    todo: '▲ /iirc run-maintenance · 1 suggestion lookup timed out this session',
  },
]

for (const ex of LINE_EXAMPLES) {
  test(`the summary line above the prompt: ${ex.name}`, async ($: Engine, on: On) => {
    engine(on)
    const clock = mock.clock(on)
    const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    on('session.id', () => ({ value: 's1' }))
    on('ui.toast', () => ({ value: undefined }))
    on('process.run', ($, e) => (e.argv.includes('summarize-session-usage') ? ran(JSON.stringify({ missed: [], match: {}, gone: [], ...ex.usage })) : ran(OK_BRIEF)))
    await hookRow($, 'SessionStart', OK_BRIEF, `hl-${ex.text.length}`)
    if (ex.usage) {
      await $.tool.call({ tool: 'Bash', command: 'iirc read a.md', tool_use_id: `tl-${ex.text.length}` })
      await clock.settle()
    }
    expect(await waitFor($, `● ▍${ex.text}`)).toBe(true)
    expect(parts(await (await bandRow($)).find({ key: 'iirc-line' }))).toEqual(ex.drawn)
    // under the prompt, only a problem draws anything
    const hint = await hintRow($)
    if (ex.todo) expect(await hint.find({ text: ex.todo })).toBeDefined()
    else expect(await hint.find({ key: 'iirc-todo' })).toBeUndefined()
    expect(await hint.find({ text: 'engine row' })).toBeDefined()
  })
}

test('a counter that rises lights up with its +N for four seconds, then settles; the first count lights nothing', async ($: Engine, on: On) => {
  engine(on)
  const clock = mock.clock(on)
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  let usage: Record<string, unknown> = { read: ['a.md'], written: [], suggested: [], used: [], searches: 1 }
  on('session.id', () => ({ value: 's1' }))
  on('ui.toast', () => ({ value: undefined }))
  on('process.run', ($, e) => (e.argv.includes('summarize-session-usage') ? ran(JSON.stringify({ missed: [], match: {}, gone: [], timeouts: 0, ...usage })) : ran(OK_BRIEF)))
  await hookRow($, 'SessionStart', OK_BRIEF, 'hf1')
  await $.tool.call({ tool: 'Bash', command: 'iirc read a.md', tool_use_id: 'tf1' })
  await clock.settle()
  expect(await waitFor($, 'iirc status  1 searched │ 1 read')).toBe(true)
  usage = { read: ['a.md', 'b.md', 'c.md'], written: [], suggested: [], used: [], searches: 1 }
  await $.tool.call({ tool: 'Bash', command: 'iirc read b.md c.md', tool_use_id: 'tf2' })
  await clock.settle()
  expect(await waitFor($, '1 searched │ 3 +2 read')).toBe(true)
  const lit = parts(await (await bandRow($)).find({ key: 'iirc-line' }))
  expect(lit).toContainEqual(['3', { bold: true, color: 'text' }])
  expect(lit).toContainEqual([' +2', { color: 'subtle' }])
  expect(lit).toContainEqual(['1', { bold: true, color: 'claude' }])          // searched did not rise
  await clock.advance(3900)
  expect(await (await bandRow($)).find({ text: '+2' })).toBeDefined()
  await clock.advance(200)
  expect(await waitFor($, '1 searched │ 3 read')).toBe(true)
  expect(await (await bandRow($)).find({ text: '+2' })).toBeUndefined()
})

test('the band\'s wordmark runs from the accent orange to violet, letter by letter', () => {
  expect(WORDMARK[0][1].color).toBe('#e8875f')
  expect(WORDMARK[10][1].color).toBe('#a78bfa')
})

test('the summary line hides zero counters and the suggested pages read with no suggestion; its right end keeps the page count', () => {
  const ok = parseBrief(OK_BRIEF)!.status
  expect(statusText(ok, counts())).toBe('iirc status  110 pages')
  expect(statusText(ok, counts({ searches: 1 }))).toBe('iirc status  1 searched  110 pages')
  expect(statusText(ok, counts({ writes: 2 }))).toBe('iirc status  2 written  110 pages')
  expect(statusText(ok, counts({ reads: 1, writes: 1 }))).toBe('iirc status  1 read │ 1 written  110 pages')
  // a suggestion nobody read still shows
  expect(statusText(ok, counts({ suggested: 3 }))).toBe('iirc status  0/3 suggested read  110 pages')
  expect(statusText(ok, counts({ suggested: 10, used: 1, model: 'nomic-embed-text' }))).toBe('iirc status  1/10 suggested read  nomic-embed-text · 110 pages')
  // the line holds no problem: a warning or an error leaves the counts alone, and an error with no pages leaves the name
  expect(statusText(parseBrief(BRIEF)!.status, counts())).toBe('iirc status  68 pages')
  expect(statusText({ level: 'error', pages: null, mode: null, note: 'needs setup' }, counts({ reads: 2 }))).toBe('iirc status  2 read')
  expect(statusText({ level: 'error', pages: null, mode: null, note: 'needs setup' }, counts())).toBe('iirc status')
  // with semantic search the model names itself; with string search the right end says so instead, once
  expect(statusText(ok, counts({ model: 'qwen3-embedding-0.6b' }))).toBe('iirc status  qwen3-embedding-0.6b · 110 pages')
  const down = parseBrief('iirc: 5 pages, string only (127.0.0.1:11434 does not answer; `iirc doctor` to check). Topics: x 5.')!.status
  expect(statusText(down, counts({ reads: 1, model: 'qwen3-embedding-0.6b' }))).toBe('iirc status  1 read  string search · 5 pages')
})

for (const isHintNative of [false, true]) {
  test(`the line under the prompt is its own row under the engine's hint${isHintNative ? ', even when the hint hands over no text' : ''}`, async ($: Engine, on: On) => {
    engine(on, '', false, isHintNative)
    on('ui.toast', () => ({ value: undefined }))
    await hookRow($, 'SessionStart', BRIEF, `hr-${isHintNative}`)
    type Node = { type?: string; props?: Record<string, unknown>; children?: Node[] }
    const root = (await (await hintRow($)).find({ text: TODO })) as Node
    // a column: the engine's hint first, as it handed it over, and the line second
    expect(root.type).toBe('Box')
    expect(root.props?.flexDirection).toBe('column')
    expect(root.children).toHaveLength(2)
    expect(JSON.stringify(root.children![0])).toBe(isHintNative ? JSON.stringify({ type: 'Box' }) : JSON.stringify({ type: 'Text', children: ['engine row'] }))
    expect(parts(root.children![1]).map(([t]) => t).join('')).toBe(TODO)
  })
}

test('over an empty engine band, the band is our one row and nothing else', async ($: Engine, on: On) => {
  engine(on, '', true)
  on('ui.toast', () => ({ value: undefined }))
  await hookRow($, 'SessionStart', OK_BRIEF, 'he1')
  const root = (await (await bandRow($)).find({ text: 'iirc status' })) as { type?: string; props?: Record<string, unknown>; children?: unknown[] }
  expect(root.type).toBe('Box')
  expect(root.props?.flexDirection).toBe('row')                // the keyed row itself, no column holding an empty element above it
  expect(parts(root).map(([t]) => t).join('')).toBe('● ▍iirc status  110 pages')
})

// Claude Code seats a pane a click opens only from 144 columns (110 once the person opened that id by hand);
// below that the open waits undrawn, so the press says so, as a suggested page's click does
const WAITING = 'unasked below 144 columns (129 now): placed when the person opens it, or when the terminal widens'
for (const isPlaced of [false, true]) {
  test(`a press on the band ${isPlaced ? 'opens the pane and toasts nothing' : 'says why the pane waits, and how to open it'}`, async ($: Engine, on: On) => {
    engine(on)
    const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    const toast: string[] = []
    const ids: string[] = []
    on('ui.toast', ($, e) => (toast.push(e.text), { value: undefined }))
    on('ui.open', ($, e) => (ids.push(e.id), { value: isPlaced ? { isPlaced: true } : { isPlaced: false, reason: WAITING } }))
    on('process.run', ($, e) => (e.argv.includes('--health') ? ran(JSON.stringify({ suspect: [], stores: [] })) : ran(OK_BRIEF)))
    await hookRow($, 'SessionStart', OK_BRIEF, `hw-${isPlaced}`)
    await (await bandRow($)).press({ key: 'iirc-open' })
    await new Promise(r => setTimeout(r, 20))
    // the pane /iirc reader opens, so the 110-column floor applies once the person has opened it by hand
    expect(ids).toEqual(['iirc'])
    expect(toast).toEqual(isPlaced ? [] : [`iirc: the reader is waiting: ${WAITING}; /iirc reader opens it`])
  })
}

test('a press on the band opens the iirc pane at once, and i presses it once the band has the focus', async ($: Engine, on: On) => {
  engine(on)
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  const order: string[] = []
  on('ui.toast', () => ({ value: undefined }))
  on('ui.open', ($, e) => (order.push(`open ${e.id}`), { value: { isPlaced: true } }))
  on('process.run', ($, e) => {
    if (e.argv.includes('--health')) return (order.push('health'), ran(JSON.stringify({ suspect: [], stores: [] })))
    return ran(OK_BRIEF)
  })
  await hookRow($, 'SessionStart', OK_BRIEF, 'hb1')
  const band = await bandRow($)
  const button = (await band.find({ key: 'iirc-open' })) as { type?: string; props?: Record<string, unknown> }
  expect(button.type).toBe('Button')
  expect(button.props?.hotkey).toBeUndefined()                 // a plain Button draws its hotkey before the label ("i: "), so the band has none
  // the open comes first, while the press is still the person's: an open after a slow doctor --health may count as unasked
  await band.press({ key: 'iirc-open' })
  expect(order[0]).toBe('open iirc')
  // a narrow band keeps the Button
  expect(((await (await bandRow($, false, 20)).find({ key: 'iirc-open' })) as { type?: string }).type).toBe('Button')
})

test('the band\'s right end: the model or string search, then the page count, dropped first at a narrow width', async ($: Engine, on: On) => {
  engine(on)
  const ran = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  on('ui.toast', () => ({ value: undefined }))
  const clock = mock.clock(on)
  let model = 'qwen3-embedding-0.6b'
  on('session.id', () => ({ value: 's1' }))
  const health: string[][] = []
  on('process.run', ($, e) => {
    if (e.argv.includes('--health')) health.push([...e.argv])
    return e.argv.includes('summarize-session-usage') ? ran(JSON.stringify({ read: [], written: [], suggested: [], used: [], missed: [], match: {}, timeouts: 0, searches: 0, model, gone: [] })) : ran(OK_BRIEF)
  })
  await hookRow($, 'SessionStart', OK_BRIEF, 'hc1')
  await $.tool.call({ tool: 'Bash', command: 'iirc read a.md', tool_use_id: 'tc1' })      // the counts carry the model
  await clock.settle()
  expect(await waitFor($, 'qwen3-embedding-0.6b · 110 pages')).toBe(true)
  const wide = parts(await (await bandRow($)).find({ key: 'iirc-line' }))
  expect(wide[0]).toEqual(['● ', { color: 'success' }])
  expect(wide.slice(-4)).toEqual([['  ', {}], ['qwen3-embedding-0.6b', { color: 'subtle' }], [' · ', { color: 'subtle' }], ['110 pages', { color: 'subtle' }]])
  // 3 + "iirc status" + 2 + "qwen3-embedding-0.6b · 110 pages" is 48 columns: at 40 the right end goes, and the line takes the page count back
  const narrow = parts(await (await bandRow($, false, 40)).find({ key: 'iirc-line' }))
  expect(narrow.map(([t]) => t).join('')).toBe('● ▍iirc status  110 pages')
  // a new model shows after the command that sets it, from the counts that command refreshes
  model = 'nomic-embed-text'
  await $.tool.call({ tool: 'Bash', command: 'iirc set-embedding-model nomic-embed-text', tool_use_id: 'tc2' })
  await clock.settle()
  expect(await waitFor($, 'nomic-embed-text · 110 pages')).toBe(true)
  // a press opens the pane and refreshes the counts; it runs no doctor --health
  await (await bandRow($)).press({ key: 'iirc-open' })
  await clock.settle()
  expect(health).toEqual([])
  // string search: the right end says so in yellow, the circle turns yellow, and the line under the prompt says why
  await hookRow($, 'SessionStart', 'iirc: 110 pages, string only (127.0.0.1:11434 does not answer; `iirc doctor` to check). Topics: x 110.', 'hc2')
  const string = parts(await (await bandRow($)).find({ key: 'iirc-line' }))
  expect(string[0]).toEqual(['● ', { color: 'warning' }])
  expect(string.slice(-4)).toEqual([['  ', {}], ['string search', { color: 'warning' }], [' · ', { color: 'subtle' }], ['110 pages', { color: 'subtle' }]])
  expect(string.filter(([t]) => t === 'string search')).toHaveLength(1)
  expect(await (await hintRow($)).find({ text: '▲ iirc doctor · 127.0.0.1:11434 does not answer' })).toBeDefined()
  // search_mode = string: no brief problem, but the circle is still yellow
  await hookRow($, 'SessionStart', 'iirc: 110 pages, string search. Topics: x 110.', 'hc3')
  expect(parts(await (await bandRow($)).find({ key: 'iirc-line' }))[0]).toEqual(['● ', { color: 'warning' }])
  expect(await (await hintRow($)).find({ key: 'iirc-todo' })).toBeUndefined()
})

test('the drawn summary line: the circle takes the level\'s theme color, the search mode note is a warning, and a survey or off hides the line', async ($: Engine, on: On) => {
  engine(on)
  on('ui.toast', () => ({ value: undefined }))
  expect(await (await bandRow($)).find({ key: 'iirc-line' })).toBeUndefined()      // no brief yet
  await hookRow($, 'SessionStart', 'iirc: 5 pages, string only (127.0.0.1:11434 does not answer; `iirc doctor` to check). Topics: x 5.', 'hm1')
  const drawn = parts(await (await bandRow($)).find({ key: 'iirc-line' }))
  expect(drawn[0]).toEqual(['● ', { color: 'warning' }])
  expect(drawn).toContainEqual(['string search', { color: 'warning' }])
  expect(await (await bandRow($, true)).find({ key: 'iirc-line' })).toBeUndefined()
  await $.command.run({ command: 'iirc', args: 'summary-line-visibility off' })
  expect(await (await bandRow($)).find({ key: 'iirc-line' })).toBeUndefined()
  // the line under the prompt does not follow the setting
  expect(await (await hintRow($)).find({ text: '▲ iirc doctor · 127.0.0.1:11434 does not answer' })).toBeDefined()
  await $.command.run({ command: 'iirc', args: 'summary-line-visibility on' })
  await hookRow($, 'SessionStart', 'iirc: not set up on this machine. Ask the creator; then run `iirc add-embedding-model MODEL HOST` with their answer.', 'hm2')
  expect(parts(await (await bandRow($)).find({ key: 'iirc-line' }))).toEqual(head('error'))
})

test('the line under the prompt: what to do and why, in the brief\'s words, the most severe first', () => {
  const ok = parseBrief(OK_BRIEF)!.status
  expect(actionText(null, counts())).toBe('')
  expect(actionText(ok, counts())).toBe('')
  expect(actionText(parseBrief(BRIEF)!.status, counts())).toBe(TODO)
  expect(actionText(ok, counts({ timeouts: 2 }))).toBe('▲ /iirc run-maintenance · 2 suggestion lookups timed out this session')
  expect(actionText(parseBrief('iirc: this repository has no .iirc/. Ask the creator whether to create one; if yes, run `iirc init`.')!.status, counts()))
    .toBe('✖ iirc init · this repository has no .iirc/')
  expect(actionText(parseBrief("iirc: this repository or machine still uses the memory plugin's layout. Ask the creator whether to migrate; if yes, run `iirc migrate`.")!.status, counts()))
    .toBe("✖ iirc migrate · this repository or machine still uses the memory plugin's layout")
  expect(actionText(parseBrief("iirc: 9 pages, semantic via h:1. This machine's or repository's iirc settings have the old shape; `iirc doctor --fix` converts them.")!.status, counts()))
    .toBe("▲ iirc doctor --fix · this machine's or repository's iirc settings have the old shape")
  // setup before upkeep, and the rest counted
  const two = parseBrief('iirc: 9 pages, semantic via h:1. Maintenance is due (1 store commit not pushed); run /iirc run-maintenance. Persistence: .claude/settings.json does not exist.')!.status
  expect(actionText(two, counts({ timeouts: 1 }))).toBe('▲ iirc doctor --fix · persistence: .claude/settings.json does not exist · +2 more')
  // a fix that is not a command is the instruction itself
  expect(actionText({ level: 'error', pages: null, mode: null, note: 'needs a plugin update', problems: [{ level: 'error', fix: 'update the plugin', why: 'this repository needs a newer iirc plugin' }] }, counts({ timeouts: 1 })))
    .toBe('✖ Update the plugin · this repository needs a newer iirc plugin · +1 more')
})

test('the line under the prompt shows run-maintenance\'s first due reason and counts the rest, and keeps other lists whole', () => {
  const due = parseBrief('iirc: 9 pages, semantic via h:1. Maintenance is due (1 near-duplicate pair; 2 suspect pages (a.md, b.md); 2 store commits not pushed); run /iirc run-maintenance.')!.status
  expect(actionText(due, counts())).toBe('▲ /iirc run-maintenance · 1 near-duplicate pair · +2 more')
  expect(actionText(due, counts({ timeouts: 1 }))).toBe('▲ /iirc run-maintenance · 1 near-duplicate pair · +3 more')
  // the creator's example: a due list of one, and this session's timeout as the one more
  const week = parseBrief('iirc: 9 pages, semantic via h:1. Maintenance is due (2 suggestion lookups timed out this week); run /iirc run-maintenance.')!.status
  expect(actionText(week, counts({ timeouts: 1 }))).toBe('▲ /iirc run-maintenance · 2 suggestion lookups timed out this week · +1 more')
  const git = parseBrief('iirc: 9 pages, semantic via h:1. Persistence: .claude/settings.json does not exist; .gitignore does not ignore .iirc/.cache.')!.status
  expect(actionText(git, counts())).toBe('▲ iirc doctor --fix · persistence: .claude/settings.json does not exist; .gitignore does not ignore .iirc/.cache')
})

test('only a warning with a command to run reaches the line under the prompt, and it names that command', () => {
  const at = (sentence: string) => actionText(parseBrief(`iirc: 9 pages, semantic via h:1. ${sentence}`)!.status, counts())
  expect(at('Store shared was not pulled (diverged from origin); run iirc sync.')).toBe('▲ iirc sync · store shared was not pulled (diverged from origin)')
  expect(at("This repository names no embedding model, so it uses nomic-embed-text, the first on this machine's list; ask the creator whether to keep it, and `iirc set-embedding-model nomic-embed-text` writes it."))
    .toBe("▲ iirc set-embedding-model nomic-embed-text · this repository names no embedding model, so it uses nomic-embed-text, the first on this machine's list")
  expect(at('Two hosts serve nomic-embed-text on this machine and none is preferred, so it uses a:1; ask the creator which to use, and `iirc prefer-embedding-host nomic-embed-text HOST` records it.'))
    .toBe('▲ iirc prefer-embedding-host nomic-embed-text HOST · two hosts serve nomic-embed-text on this machine and none is preferred, so it uses a:1')
  // news, and a warning that names no command, draw nothing
  expect(at('Pulled 3 pages from remote stores; reindexing in the background.')).toBe('')
  expect(parseBrief('iirc: 9 pages, semantic via h:1. Pulled 3 pages from remote stores; reindexing in the background.')!.status.level).toBe('ok')
  expect(at('The start scan took 2.4 s over 30 cited files, past the 1 s budget; tell the creator.')).toBe('')
})

test('the drawn line under the prompt: the mark and the reason in the level\'s color, the command bold', async ($: Engine, on: On) => {
  engine(on)
  on('ui.toast', () => ({ value: undefined }))
  await hookRow($, 'SessionStart', 'iirc: this repository has no .iirc/. Ask the creator whether to create one; if yes, run `iirc init`.', 'ha1')
  expect(parts(await (await hintRow($)).find({ key: 'iirc-todo' }))).toEqual([
    ['✖ ', { bold: true, color: 'error' }], ['iirc init', { bold: true, color: 'error' }], [' · ', { color: 'subtle' }], ['this repository has no .iirc/', { color: 'error' }],
  ])
})

// A row Box lays each sibling out as a column of its own, and a long reason wrapped beside the command
// (Claude Code, 200 columns): the line is one Text of inline spans, so it wraps as one run of prose
test('the line under the prompt and the summary line are each one Text of spans, so each wraps as a whole', async ($: Engine, on: On) => {
  engine(on)
  on('ui.toast', () => ({ value: undefined }))
  await hookRow($, 'SessionStart', 'iirc: 9 pages, semantic via h:1. Maintenance is due (2 suggestion lookups timed out this week); run /iirc run-maintenance. Persistence: .claude/settings.json does not exist.', 'hw1')
  // each column of the keyed row (the line, and the band's right end) holds one Text, and that Text holds only Text spans
  type Node = { type?: string; children?: unknown[] }
  const isSpans = (row: unknown) => {
    const columns = ((row ?? {}) as Node).children ?? []
    return columns.length > 0 && columns.every(col => {
      const kids = (col as Node).children ?? []
      const text = (kids[0] ?? {}) as Node
      // the band's line is a Button of spans, so a click opens the pane
      return kids.length === 1 && (text.type === 'Text' || text.type === 'Button') && !!text.children?.length && text.children.every(c => !!c && typeof c === 'object' && (c as Node).type === 'Text')
    })
  }
  const todo = await (await hintRow($)).find({ key: 'iirc-todo' })
  expect(isSpans(todo)).toBe(true)
  expect(parts(todo)).toEqual([
    ['▲ ', { bold: true, color: 'warning' }], ['iirc doctor --fix', { bold: true, color: 'warning' }], [' · ', { color: 'subtle' }],
    ['persistence: .claude/settings.json does not exist', { color: 'warning' }], [' · ', { color: 'subtle' }], ['+1 more', { color: 'subtle' }],
  ])
  expect(isSpans(await (await bandRow($)).find({ key: 'iirc-line' }))).toBe(true)
})
