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
const LEVEL_COLOR = { ok: 'success', warn: 'warning', error: 'error' } as const
const STATUS_ARGS_RE = /^\s*status(?:\s+(on|off))?\s*$/
const MAX_SUGGESTED_ARGS_RE = /^\s*max-suggested(?:\s+(\S+))?\s*$/
// columns left of a page's text: the fold's indent (3), the list's (2), and the branch (3), plus one spare
const PAGE_INDENT = 9
const KEEP = 200

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

/** What a plain /iirc prints: the session's line, the two settings, and the forms /iirc takes. */
async function helpText($: EngineInterface): Promise<string> {
  const s = await read($, status)
  let max = '?'
  try {
    const ran = await $.process.run([`${$.plugin.root}/bin/iirc`, 'max-suggested'], { cwd: await $.session.root(), timeoutMs: 15000 })
    max = /up to (\d+)/.exec(ran.stdout)?.[1] ?? '?'
  } catch {}
  const head = s === null ? 'iirc: no session brief yet' : statusText(s, await read($, counts))
  const shown = (await read($, isStatusShown)) ? 'on' : 'off'
  return [
    `${head} · status ${shown} · max-suggested ${max}`,
    '/iirc status on|off       show or hide the line under the prompt',
    '/iirc max-suggested N     pages recall suggests at most (1-10)',
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
      await update($, lastPrompt, () => e.uuid)
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
    const pages = (await read($, byPrompt))[e.requestId]
    if (!pages || pages.length === 0) return next(e)
    const original = await next(e)
    const isOpen = (await read($, open))[e.requestId] === true
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {original}
        {drawPages($, e, e.requestId, pages, isOpen, 'suggested')}
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
