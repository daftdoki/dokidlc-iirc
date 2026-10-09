import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, ResolveInput } from 'claude-code'

import type { IircStatus, RecalledPage, SessionCounts, ToolNote } from '../types'

// The command hooks in hooks.json put lines into the model's context. This module
// catches each line as its row is stored and draws it for the person: recalled
// pages as a folding list under the prompt or the failed command, a pencil row
// under a command that failed and then worked, the session brief and the count
// of pages read this session in the hint row under the prompt, and warnings as
// toasts.
// `ui = false` in .claude/iirc.toml turns it off.

const byPrompt = atom({ plugin: 'iirc', key: 'byPrompt' } as const, {})
const byTool = atom({ plugin: 'iirc', key: 'byTool' } as const, {})
const open = atom({ plugin: 'iirc', key: 'open' } as const, {})
const lastPrompt = atom({ plugin: 'iirc', key: 'lastPrompt' } as const, null)
const lastTool = atom({ plugin: 'iirc', key: 'lastTool' } as const, null)
const briefShown = atom({ plugin: 'iirc', key: 'briefShown' } as const, null)
const status = atom({ plugin: 'iirc', key: 'status' } as const, null)
const counts = atom({ plugin: 'iirc', key: 'counts' } as const, { reads: 0, writes: 0, suggested: 0, used: 0 })
const isStatusShown = atom({ plugin: 'iirc', key: 'isStatusShown' } as const, true)
const maxSuggested = atom({ plugin: 'iirc', key: 'maxSuggested' } as const, null)

const RECALL_RE = /iirc: \d+ pages? may apply\. Read before you investigate: (.*)/
const RECOVERED_RE = /`([^`]+)` failed (\d+) times this session before it worked/g
const STOP_RE = /iirc: before you stop, note that (.*?) failed and then worked/
const MIGRATE_RE = /^iirc: this repository or machine still uses the memory plugin's layout/
const BRIEF_RE = /iirc: (\d+) pages?, (semantic via \S*[^\s.]|string only \([^)]*\)|string search)[^.]*\.\s*(.*)/s
// the command that clears each kind of warning, in the order the line under the prompt names one
const WARNING_FIX: [RegExp, string][] = [
  [/memoryfield-tool is not at the pin/, 'iirc doctor --fix'],
  [/suspect:/, 'iirc doubt'],
  [/not pushed/, 'iirc sync'],
  [/Persistence:/, 'iirc doctor --fix'],
  [/near-duplicate/, 'iirc doctor'],
]
// sentences of the brief that are instructions to the model, not news for the person
const BRIEF_QUIET = /^(Topics:|Stores:|A hook names|Context was just compacted)/
// commands that change the page count or the setup the brief reports, and commands that read pages
const CHANGES_BRIEF_RE = /\biirc\s+(write|delete|sync|migrate|setup|init|doctor)\b/
const COUNTS_RE = /\biirc\s+(read|pull|write)\b/
// fixed red, yellow, green rather than the theme's, whose success color may be blue
const LEVEL_COLOR = { ok: '#57ab5a', warn: '#d4a72c', error: '#e5534b' } as const
const STATUS_ARGS_RE = /^\s*status(?:\s+(on|off))?\s*$/
// iirc commands a person may run straight from /iirc; the rest go to the skill, which asks first
const DIRECT_RE = /^(doctor(?:\s+--fix)?|doubt(?:\s+--all)?|stores|sync|stats(?:\s+--days\s+\d+)?|index|cost|search\s+\S.*|read(?:\s+\S+)+)$/s
const MAX_SUGGESTED_ARGS_RE = /^\s*max-suggested(?:\s+(\S+))?\s*$/
// columns left of a page's text: the fold's indent (3), the list's (2), and the branch (3), plus one spare
const PAGE_INDENT = 9
// red, amber, green: the hit-rate gauge, stepped by position along the bar
const GAUGE = ['#e5534b', '#d4a72c', '#57ab5a'] as const
// sample numbers for `/iirc demo`
const DEMO_STATUS: IircStatus = { level: 'ok', pages: 142, mode: 'semantic+keyword', note: null }
const DEMO_COUNTS: SessionCounts = { reads: 58, writes: 9, suggested: 42, used: 31 }
// the commands /iirc runs directly, as the card and the text help list them
const COMMANDS: [string, string, 'MAINTENANCE' | 'LOOK UP'][] = [
  ['doctor', 'check the setup and the pages', 'MAINTENANCE'],
  ['doctor --fix', 'install or repair what doctor finds', 'MAINTENANCE'],
  ['doubt', 'pages that may be wrong', 'MAINTENANCE'],
  ['sync', 'commit, pull, and push remote stores', 'MAINTENANCE'],
  ['stores', 'the stores, and anything not pushed', 'MAINTENANCE'],
  ['stats', 'how the pages are being used', 'MAINTENANCE'],
  ['index', 'rebuild the search index and index.md', 'MAINTENANCE'],
  ['search QUERY', 'ranked pages for a query', 'LOOK UP'],
  ['read PAGE', 'one page, with its trust markers', 'LOOK UP'],
]
const KEEP = 200

/**
 * A prompt's key: its uuid's first four groups. The UserMessage row's requestId
 * can carry the prompt's uuid with the last group zeroed
 * (40d603b1-96c7-41d7-9dc0-000000000000 for …-00885dcac635, Claude Code 2.1.295),
 * so the two meet on the part they share.
 */
export function promptKey(id: string): string {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id) ? id.slice(0, 23) : id
}

export function textOf(content: unknown): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .map(b => (b && typeof b === 'object' && typeof (b as { text?: unknown }).text === 'string' ? (b as { text: string }).text : ''))
    .join('\n')
}

export function parseRecall(text: string): RecalledPage[] {
  const m = RECALL_RE.exec(text)
  if (!m) return []
  const pages: RecalledPage[] = []
  for (const entry of m[1].split(' · ')) {
    const name = /`iirc read ([^`]+)`/.exec(entry)?.[1]
    if (!name) continue
    const isSuspect = entry.includes('`iirc verify ')
    let rest = entry.slice(entry.indexOf('`', entry.indexOf(name)) + 1).trim()
    if (rest.startsWith('(')) rest = rest.slice(1)
    // (summary) [how it matched] (suspect: ...), the last two optional
    const match = /\) \[([^\]]+)\]/.exec(rest)
    const cut = match ? match.index : isSuspect ? rest.lastIndexOf(') (') : rest.lastIndexOf(')')
    pages.push({ name, summary: (cut >= 0 ? rest.slice(0, cut) : rest).trim(), isSuspect, ...(match ? { match: match[1] } : {}) })
  }
  return pages
}

export function parseRecovered(text: string): ToolNote['recovered'] {
  return [...text.matchAll(RECOVERED_RE)].map(m => ({ command: m[1], failures: Number(m[2]) }))
}

/** What the hint row shows and the warnings worth a toast, from the SessionStart line. */
export function parseBrief(text: string): { status: IircStatus; warnings: string[] } | null {
  const at = text.indexOf('iirc: ')
  if (at < 0) return null
  const line = text.slice(at)
  const m = BRIEF_RE.exec(line)
  if (!m) {
    // each of these lines names the command that fixes it, in backticks
    const fix = /`(iirc [^`]+)`/.exec(line)?.[1] ?? (/newer iirc plugin/.test(line) ? 'update the plugin' : undefined)
    const note = MIGRATE_RE.test(line)
      ? 'needs migration'
      : /not set up/.test(line)
        ? 'needs setup'
        : /no \.iirc\//.test(line)
          ? 'needs init'
          : /no store/.test(line)
            ? 'needs a store'
            : /newer iirc plugin/.test(line)
              ? 'needs a plugin update'
              : 'needs setup'
    const warnings = MIGRATE_RE.test(line) ? [] : [line.split('. ')[0].replace(/^iirc: /, '')]
    return { status: { level: 'error', pages: null, mode: null, note, ...(fix ? { fix } : {}) }, warnings }
  }
  // semantic search also matches terms; without an embedding host it matches terms alone
  const isHostDown = m[2].startsWith('string only')
  const mode = m[2].startsWith('semantic') ? 'semantic+keyword' : 'keyword'
  const warnings = m[3]
    .split(/(?<=\.)\s+(?=[A-Z0-9])/)
    .map(s => s.trim())
    .filter(s => s && !BRIEF_QUIET.test(s))
  const fix = isHostDown ? 'iirc setup' : WARNING_FIX.find(([re]) => warnings.some(w => re.test(w)))?.[1]
  const level = isHostDown || warnings.length > 0 ? 'warn' : 'ok'
  return { status: { level, pages: Number(m[1]), mode, note: null, ...(fix ? { fix } : {}) }, warnings }
}

/** The hint row's text after the circle. */
export function statusText(s: IircStatus, c: SessionCounts): string {
  const fix = s.level !== 'ok' && s.fix ? ` · run ${s.fix}` : ''
  if (s.pages === null) return `iirc: ${s.note}${fix}`
  // the mode shows only when it is not the default, so a weaker search stands out
  const mode = s.mode === 'semantic+keyword' ? '' : ` · [${s.mode}] mode`
  return `iirc: [${s.pages}] ${s.pages === 1 ? 'page' : 'pages'} · [${c.used}/${c.suggested}] used · [${c.reads}] reads · [${c.writes}] writes${mode}${fix}`
}

function keepLast<T>(map: Record<string, T>, key: string, value: T): Record<string, T> {
  const next = { ...map, [key]: value }
  const keys = Object.keys(next)
  for (const k of keys.slice(0, Math.max(0, keys.length - KEEP))) delete next[k]
  return next
}

async function uiEnabled($: EngineInterface): Promise<boolean> {
  try {
    const toml = await $.fs.read(`${await $.session.root()}/.claude/iirc.toml`)
    return !/^\s*ui\s*=\s*false\b/m.test(toml)
  } catch {
    return true
  }
}

/** The brief in the hint row, and its warnings as a toast once per distinct brief. */
async function showBrief($: EngineInterface, text: string) {
  const brief = parseBrief(text)
  if (!brief) return
  await update($, status, () => brief.status)
  const warned = brief.warnings.join(' ')
  if (warned && (await read($, briefShown)) !== warned) {
    await update($, briefShown, () => warned)
    $.ui.toast(`iirc: ${brief.warnings.join(' ')}`)
  }
}

/** Run one iirc command for the person and return what it printed. A search keeps its words as one query. */
async function runDirect($: EngineInterface, args: string): Promise<string> {
  const [verb, ...rest] = args.split(/\s+/)
  const argv = verb === 'search' ? [verb, rest.join(' ')] : [verb, ...rest]
  // these may embed or fetch: up to ten minutes
  const slow = args === 'doctor --fix' || verb === 'sync' || verb === 'index'
  try {
    const ran = await $.process.run([`${$.plugin.root}/bin/iirc`, ...argv], { cwd: await $.session.root(), timeoutMs: slow ? 600000 : 60000 })
    if (['doctor', 'sync', 'index'].includes(verb)) refreshBrief($)
    const out = `${ran.stdout}${ran.stderr}`.trim() || '(no output)'
    return ran.exitCode === 0 ? out : `iirc ${args} exited ${ran.exitCode}:\n${out}`
  } catch (err) {
    return `iirc ${args} did not finish: ${String(err)}`
  }
}

/** What a plain /iirc prints: the session's line, the two settings, and the forms /iirc takes. */
async function helpText($: EngineInterface): Promise<string> {
  const s = await read($, status)
  let max = '?'
  try {
    const ran = await $.process.run([`${$.plugin.root}/bin/iirc`, 'max-suggested'], { cwd: await $.session.root(), timeoutMs: 15000 })
    max = /up to (\d+)/.exec(ran.stdout)?.[1] ?? '?'
  } catch {}
  if (max !== '?') await update($, maxSuggested, () => Number(max))
  // the engine puts the plugin's name in front of a command's text
  const head = s === null ? 'no session brief yet' : statusText(s, await read($, counts)).replace(/^iirc: /, '')
  const shown = (await read($, isStatusShown)) ? 'on' : 'off'
  return [
    `${head} · status ${shown} · max-suggested ${max}`,
    '/iirc status on|off       show or hide the line under the prompt',
    '/iirc max-suggested N     pages recall suggests at most (1-10)',
    ...COMMANDS.map(([cmd, what]) => `/iirc ${cmd.padEnd(20)}${what}`),
    "/iirc <request>           ask iirc in words: search, remember, what's out of date",
  ].join('\n')
}

/** Ask iirc how many distinct pages this session has read and written, from its log. */
function refreshCounts($: EngineInterface) {
  $.clock.after(0, () => {
    void (async () => {
      if (!(await uiEnabled($))) return
      const ran = await $.process.run([`${$.plugin.root}/bin/iirc`, 'stats', '--session', await $.session.id()], {
        cwd: await $.session.root(),
        timeoutMs: 15000,
      })
      if (ran.exitCode !== 0) return
      const got = JSON.parse(ran.stdout) as Record<string, unknown>
      const n = (key: string) => (Array.isArray(got[key]) ? (got[key] as unknown[]).length : 0)
      await update($, counts, () => ({ reads: n('read'), writes: n('written'), suggested: n('suggested'), used: n('used') }))
    })().catch(() => {})
  })
}

/** Ask iirc for the brief and show it. Without --hook, doctor --brief reads no stdin and pulls nothing. */
function refreshBrief($: EngineInterface) {
  // on a timer, so the run outlives this dispatch and no prompt or tool waits for it
  $.clock.after(0, () => {
    void (async () => {
      if (!(await uiEnabled($))) return
      const ran = await $.process.run([`${$.plugin.root}/bin/iirc`, 'doctor', '--brief'], {
        cwd: await $.session.root(),
        timeoutMs: 15000,
      })
      if (ran.exitCode === 0) await showBrief($, ran.stdout)
    })().catch(() => {})
  })
}

export const register: Register = on => {
  // A resumed session stores its SessionStart line where neither session.append
  // nor $.session.messages() shows it, so ask iirc for the brief directly.
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    $.ui.status(undefined)   // earlier versions drew the brief on the status line
    refreshBrief($)
    refreshCounts($)
    try {
      if ((await $.store.get('isStatusShown')) === false) await update($, isStatusShown, () => false)
    } catch {}   // the line stays on, the default
    return result
  })

  on('tool.call', async ($, e, next) => {
    if (e.agentId === undefined) await update($, lastTool, () => e.tool_use_id)
    const result = await next(e)
    // keep the hint row's page count and read count current within the session
    if (e.tool === 'Bash') {
      if (CHANGES_BRIEF_RE.test(e.command)) refreshBrief($)
      if (COUNTS_RE.test(e.command)) refreshCounts($)
    }
    return result
  })

  on('session.append', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    if (e.door === 'prompt') {
      await update($, lastPrompt, () => promptKey(e.uuid))
      return next(e)
    }
    if (e.door !== 'hook-context' || e.origin.kind !== 'hook') return next(e)
    const text = textOf(e.message.content)
    if (!text.includes('iirc: ') || !(await uiEnabled($))) return next(e)

    const event = e.origin.event
    if (event === 'UserPromptSubmit') {
      const pages = parseRecall(text)
      const prompt = await read($, lastPrompt)
      if (pages.length > 0 && prompt !== null) await update($, byPrompt, map => keepLast(map, prompt, pages))
      if (pages.length > 0) refreshCounts($)
    } else if (event === 'PostToolUse' || event === 'PostToolUseFailure') {
      const tool = await read($, lastTool)
      const pages = parseRecall(text)
      const recovered = parseRecovered(text)
      if (pages.length > 0) refreshCounts($)
      if (tool !== null && (pages.length > 0 || recovered.length > 0)) {
        await update($, byTool, map => keepLast(map, tool, { pages, recovered }))
      }
    } else if (event === 'Stop') {
      const names = STOP_RE.exec(text)?.[1]
      if (names) $.ui.toast(`✎ iirc: ${names} failed and then worked; Claude was asked to write it up before stopping`)
    } else if (event === 'SessionStart') {
      await showBrief($, text)
    }
    return next(e)
  }).catch(($, e, next) => (next.called ? undefined : next(e)))

  // A plain `/iirc` prints help, `/iirc status on|off` turns the hint-row line on or off, and
  // `/iirc max-suggested N` sets how many pages recall suggests; every other /iirc goes to the skill.
  on('command.run', async ($, e, next) => {
    if (e.command !== 'iirc' && e.command !== 'iirc:iirc') return next(e)
    // bare, it is help; the skill loads by itself when a task needs it
    if (!e.args.trim()) return { text: await helpText($) }
    // the card with sample numbers, for a screenshot that shows the design rather than one session
    if (e.args.trim() === 'demo') return { text: 'the /iirc card with sample numbers' }
    const direct = DIRECT_RE.exec(e.args.trim())
    if (direct) return { text: await runDirect($, direct[1]) }
    const maxArgs = MAX_SUGGESTED_ARGS_RE.exec(e.args)
    if (maxArgs) {
      // the recall hook runs in the CLI, so the CLI keeps the number, in the machine config
      const ran = await $.process.run([`${$.plugin.root}/bin/iirc`, 'max-suggested', ...(maxArgs[1] ? [maxArgs[1]] : [])], {
        cwd: await $.session.root(),
        timeoutMs: 15000,
      })
      return { text: (ran.stdout || ran.stderr).trim() }
    }
    const m = STATUS_ARGS_RE.exec(e.args)
    if (!m) return next(e)
    if (m[1]) {
      const isOn = m[1] === 'on'
      await $.store.set('isStatusShown', isOn)
      await update($, isStatusShown, () => isOn)
      return { text: `iirc status ${m[1]}` }
    }
    return { text: `iirc status is ${(await read($, isStatusShown)) ? 'on' : 'off'}; /iirc status on|off changes it` }
  })

  // A plain /iirc draws its help as a panel in place of the text row.
  on('ui.render', { component: 'CommandOutput' }, async ($, e, next) => {
    const isIirc = e.props.command === 'iirc' || e.props.command === 'iirc:iirc'
    const args = e.props.args.trim()
    if (!isIirc || (args !== '' && args !== 'demo') || e.props.isErrored) return next(e)
    if (args === 'demo') return drawHelp($, e, DEMO_STATUS, DEMO_COUNTS, true, 3)
    return drawHelp($, e, await read($, status), await read($, counts), await read($, isStatusShown), await read($, maxSuggested))
  })

  // The brief under the prompt, beside the engine's hint: a status line takes no color.
  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    const s = await read($, status)
    const original = await next(e)
    if (s === null || !(await read($, isStatusShown))) return original
    const c = await read($, counts)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {original}
        <Box flexDirection="row">
          <Text color={LEVEL_COLOR[s.level]}>● </Text>
          <Text color="subtle">{statusText(s, c)}</Text>
        </Box>
      </Box>
    )
  })

  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const key = promptKey(e.requestId)
    const pages = (await read($, byPrompt))[key]
    if (!pages || pages.length === 0) return next(e)
    const original = await next(e)
    const isOpen = (await read($, open))[key] === true
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {original}
        {drawPages($, e, key, pages, isOpen, 'suggested')}
      </Box>
    )
  })

  // A tool call draws as its own ToolUse row, or folded into a ToolGroup line
  // ("Ran 3 shell commands"). Draw under whichever the person sees; an
  // expanded group's calls are ToolUse rows of their own.
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    const note = (await read($, byTool))[e.requestId]
    if (!note) return next(e)
    const original = await next(e)
    const opened = await read($, open)
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {original}
        {drawNote($, e, e.requestId, note, opened[e.requestId] === true)}
      </Box>
    )
  })

  on('ui.render', { component: 'ToolGroup' }, async ($, e, next) => {
    if (e.props.isExpanded) return next(e)
    const notes = await read($, byTool)
    const ids = e.props.calls.map(c => c.tool_use_id).filter((id): id is string => !!id && !!notes[id])
    if (ids.length === 0) return next(e)
    const original = await next(e)
    const opened = await read($, open)
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {original}
        {ids.map(id => drawNote($, e, id, notes[id], opened[id] === true))}
      </Box>
    )
  })

}

/** The gauge color at position t, 0 to 1: red to amber to green. */
function gaugeColor(t: number): string {
  const hex = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16))
  const [a, b, u] = t < 0.5 ? [GAUGE[0], GAUGE[1], t * 2] : [GAUGE[1], GAUGE[2], (t - 0.5) * 2]
  const [x, y] = [hex(a), hex(b)]
  return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * u).toString(16).padStart(2, '0')).join('')
}

function drawHelp($: EngineInterface, e: ResolveInput, s: IircStatus | null, c: SessionCounts, isShown: boolean, max: number | null) {
  const { Box, Text } = $.ui.resolve(e)
  const level = s ? s.level : 'warn'
  const tone = LEVEL_COLOR[level]
  const width = Math.max(48, Math.min(72, (e.viewport?.columns ?? 76) - 4))
  // flat arrays of elements: a fragment inside a row lays out as a column on the terminal
  const head: unknown[] = [
    <Text key="dot" color={tone}>● </Text>,
    <Text key="name" bold color="claude">iirc</Text>,
    <Text key="gap">{'   '}</Text>,
  ]
  // "If I Recall Correctly", each initial lit, then what the plugin does
  // spaces lead each word: a Text's trailing space is not drawn
  for (const [k, word] of ['If', 'I', 'Recall', 'Correctly'].entries()) {
    head.push(<Text key={`i${k}`} bold color="claude">{(k > 0 ? ' ' : '') + word[0]}</Text>)
    if (word.length > 1) head.push(<Text key={`w${k}`} color="subtle">{word.slice(1)}</Text>)
  }

  const chipText = level === 'ok' ? '✔ all good' : level === 'warn' ? '▲ needs a look' : `✖ ${s ? s.note : 'no brief yet'}`
  const statusRow: unknown[] = [
    <Box key="label" width={10} flexShrink={0}><Text bold color="subtle">STATUS</Text></Box>,
    <Text key="chip" bold color="#0d1117" backgroundColor={tone}>{` ${chipText} `}</Text>,
  ]
  if (s && level !== 'ok' && s.fix) {
    statusRow.push(<Text key="fixlead" color="subtle">{'   fix with '}</Text>, <Text key="fix" bold color="claude">{s.fix}</Text>)
  }
  if (s && s.mode && s.mode !== 'semantic+keyword') statusRow.push(<Text key="mode" color={LEVEL_COLOR.warn}>{`   ${s.mode} mode`}</Text>)
  const tiles: [string, string][] = s && s.pages !== null
    ? [[String(s.pages), s.pages === 1 ? 'page' : 'pages'], [`${c.used}/${c.suggested}`, 'used'], [String(c.reads), 'reads'], [String(c.writes), 'writes']]
    : []
  const share = c.suggested > 0 ? c.used / c.suggested : 0
  const BAR = 36
  const filled = Math.round(share * BAR)
  const pct = Math.round(share * 100)
  const band = pct >= 50 ? GAUGE[2] : pct >= 25 ? GAUGE[1] : GAUGE[0]
  // each cell takes the gradient color of its position, so a fuller bar runs from red into green
  const cells = Array.from({ length: BAR }, (_, k) =>
    k < filled ? <Text key={k} color={gaugeColor(k / (BAR - 1))}>█</Text> : <Text key={k} color="inactive">░</Text>,
  )
  // command first, in the same column as the MAINTENANCE and LOOK UP rows
  const setting = (label: string, value: string, command: string) => (
    <Box key={label} flexDirection="row" paddingLeft={2}>
      <Box width={24} flexShrink={0}><Text color="suggestion">{command}</Text></Box>
      <Box width={24} flexShrink={0}><Text color="subtle">{label}</Text></Box>
      <Text bold color="claude">{value}</Text>
    </Box>
  )
  const heading = (text: string) => <Text bold color="subtle">{text}</Text>
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={tone} paddingX={1} width={width}>
      {/* two lines: one row this wide would shrink every piece and wrap each word */}
      <Box flexDirection="row">{head}</Box>
      <Box flexDirection="row" paddingLeft={9}>
        <Text color="subtle" italic>what past sessions learned, found by meaning</Text>
      </Box>
      <Text> </Text>
      <Box flexDirection="row">{statusRow}</Box>
      {tiles.length > 0 && <Text> </Text>}
      {tiles.length > 0 && (
        <Box flexDirection="row" paddingLeft={2}>
          {tiles.map(([n, label]) => (
            <Box key={label} flexDirection="column" width={13} flexShrink={0}>
              <Text bold color="claude">{n}</Text>
              <Text color="subtle">{label}</Text>
            </Box>
          ))}
        </Box>
      )}
      {c.suggested > 0 && <Text> </Text>}
      {c.suggested > 0 && (
        <Box flexDirection="row" width={BAR + 2}>
          <Box flexGrow={1}>{heading('RECALL HIT RATE')}</Box>
          <Text bold color={band}>{`${pct}%`}</Text>
        </Box>
      )}
      {c.suggested > 0 && <Box flexDirection="row" paddingLeft={2}>{cells}</Box>}
      {c.suggested > 0 && (
        <Box flexDirection="row" paddingLeft={2}>
          <Text bold color="claude">{String(c.used)}</Text>
          <Text color="subtle">{' of '}</Text>
          <Text bold color="claude">{String(c.suggested)}</Text>
          <Text color="subtle">{' suggested pages were read'}</Text>
        </Box>
      )}
      <Text> </Text>
      {heading('SETTINGS')}
      {setting('line under the prompt', isShown ? 'on' : 'off', '/iirc status on|off')}
      {setting('suggested pages', max === null ? '?' : `up to ${max}`, '/iirc max-suggested N')}
      {(['MAINTENANCE', 'LOOK UP'] as const).map(group => (
        <Box key={group} flexDirection="column">
          <Text> </Text>
          {heading(group)}
          {COMMANDS.filter(([, , g]) => g === group).map(([cmd, what]) => (
            <Box key={cmd} flexDirection="row" paddingLeft={2}>
              <Box width={24} flexShrink={0}><Text color="suggestion">{`/iirc ${cmd}`}</Text></Box>
              <Text color="subtle">{what}</Text>
            </Box>
          ))}
        </Box>
      ))}
      <Text> </Text>
      <Box flexDirection="row">
        <Box width={16} flexShrink={0}>{heading('ASK IN WORDS')}</Box>
        <Text color="suggestion">/iirc &lt;request&gt;</Text>
      </Box>
      {['what do we know about ollama hangs?', 'remember that the NAS keeps its firmware in /etc', "what's out of date?"].map(example => (
        <Box key={example} flexDirection="row" paddingLeft={2}>
          <Text color="claude">{'› '}</Text>
          <Text dimColor italic>{example}</Text>
        </Box>
      ))}
    </Box>
  )
}

function drawNote($: EngineInterface, e: ResolveInput, id: string, note: ToolNote, isOpen: boolean) {
  const { Box, Text } = $.ui.resolve(e)
  return (
    <Box key={`iirc-note-${id}`} flexDirection="column">
      {note.pages.length > 0 && drawPages($, e, id, note.pages, isOpen, 'match this error')}
      {note.recovered.map(r => (
        <Box flexDirection="row" paddingLeft={3}>
          <Text color="warning">✎ </Text>
          <Text color="subtle">iirc: </Text>
          <Text bold color="claude">{r.command}</Text>
          <Text color="subtle">{` failed ${r.failures} times, then worked; Claude was asked to write a page`}</Text>
        </Box>
      ))}
    </Box>
  )
}

function drawPages($: EngineInterface, e: ResolveInput, id: string, pages: RecalledPage[], isOpen: boolean, verb: string) {
  const { Box, Button, Text } = $.ui.resolve(e)
  const toggle = () => update($, open, map => keepLast(map, id, !(map[id] === true)))
  const noun = pages.length === 1 ? 'page' : 'pages'
  const label = verb === 'suggested' ? `${noun} suggested` : `${noun} suggested for this error`
  return (
    <Box key={`iirc-${id}`} flexDirection="column" paddingLeft={3}>
      {/* the whole row is one button, so a click on the words opens the list too */}
      <Button key={`toggle-${id}`} plain onPress={toggle}>
        <Text bold color="suggestion">{isOpen ? '[−]' : '[+]'}</Text>
        <Text> </Text>
        <Text bold color="claude">iirc: </Text>
        <Text color="subtle">[</Text>
        <Text bold color="claude">{String(pages.length)}</Text>
        <Text color="subtle">] </Text>
        <Text color="suggestion">{label}</Text>
      </Button>
      {isOpen &&
        pages.map((p, i) => {
          const isLast = i === pages.length - 1
          const pieces: Piece[] = [
            { text: '◆ ', style: { color: p.isSuspect ? 'warning' : 'success' } },
            { text: p.name.replace(/\.md$/, ''), style: { bold: true, color: 'claude' } },
            ...(p.isSuspect ? [{ text: ' (suspect)', style: { color: 'warning' } } as Piece] : []),
            ...(p.match ? [{ text: `  [${p.match}]`, style: { color: 'suggestion' } } as Piece] : []),
            { text: '  ' + p.summary, style: { dimColor: true, italic: true } },
          ]
          // wrap here, so each wrapped line keeps the tree's gutter; unmeasured, one line
          const width = e.viewport ? e.viewport.columns - PAGE_INDENT : Infinity
          return wrapPieces(pieces, width).map((line, j) => (
            <Box key={`iirc-${id}-${i}-${j}`} flexDirection="row" paddingLeft={2}>
              {/* a fixed column: a Text's trailing space is not drawn */}
              <Box width={3} flexShrink={0}>
                <Text color="subtle">{j > 0 ? (isLast ? ' ' : '│') : isLast ? '└─' : '├─'}</Text>
              </Box>
              {line.map(piece => (
                <Text {...piece.style} wrap="truncate-end">
                  {piece.text}
                </Text>
              ))}
            </Box>
          ))
        })}
    </Box>
  )
}

/** Text with its style, so a wrapped line keeps each part's color. */
type Piece = { text: string; style: { color?: 'success' | 'warning' | 'claude' | 'suggestion'; bold?: boolean; dimColor?: boolean; italic?: boolean } }

/** Word-wraps styled pieces into lines no wider than `width` cells; a word longer than a line is split. */
export function wrapPieces(pieces: Piece[], width: number): Piece[][] {
  const lines: Piece[][] = [[]]
  let used = 0
  const put = (text: string, style: Piece['style']) => {
    const line = lines[lines.length - 1]
    const last = line[line.length - 1]
    if (last && last.style === style) last.text += text
    else line.push({ text, style })
    used += text.length
  }
  for (const piece of pieces) {
    for (const token of piece.text.split(/(\s+)/)) {
      if (!token) continue
      const isSpace = /^\s+$/.test(token)
      if (used + token.length > width) {
        if (isSpace) {
          lines.push([])
          used = 0
          continue
        }
        if (used > 0) {
          lines.push([])
          used = 0
        }
        let rest = token
        while (rest.length > width) {
          put(rest.slice(0, width), piece.style)
          lines.push([])
          used = 0
          rest = rest.slice(width)
        }
        put(rest, piece.style)
      } else if (!(isSpace && used === 0 && lines.length > 1)) {
        put(token, piece.style)
      }
    }
  }
  // a space where the line broke belongs to neither line
  for (const line of lines) {
    const last = line[line.length - 1]
    if (last) last.text = last.text.trimEnd()
    if (last && !last.text) line.pop()
  }
  return lines.filter(line => line.length > 0)
}
