import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, ResolveInput } from 'claude-code'

import type { RecalledPage, ToolNote } from '../types'

// The command hooks in hooks.json put lines into the model's context. This module
// catches each line as its row is stored and draws it for the person: recalled
// pages as a folding list under the prompt or the failed command, a pencil row
// under a command that failed and then worked, the session brief on the status
// line, and warnings as toasts. `ui = false` in .claude/memory.toml turns it off.

const byPrompt = atom({ plugin: 'memory', key: 'byPrompt' } as const, {})
const byTool = atom({ plugin: 'memory', key: 'byTool' } as const, {})
const open = atom({ plugin: 'memory', key: 'open' } as const, {})
const lastPrompt = atom({ plugin: 'memory', key: 'lastPrompt' } as const, null)
const lastTool = atom({ plugin: 'memory', key: 'lastTool' } as const, null)
const briefShown = atom({ plugin: 'memory', key: 'briefShown' } as const, null)

const RECALL_RE = /memory: \d+ pages? may apply\. Read before you investigate: (.*)/
const RECOVERED_RE = /`([^`]+)` failed (\d+) times this session before it worked/g
const STOP_RE = /memory: before you stop, note that (.*?) failed and then worked/
const BRIEF_RE = /memory: (\d+) pages?, (semantic via \S+|string only|string search)[^.]*\.\s*(.*)/s
// sentences of the brief that are instructions to the model, not news for the person
const BRIEF_QUIET = /^(Topics:|Stores:|A hook names|Context was just compacted)/
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
    const name = /`memory read ([^`]+)`/.exec(entry)?.[1]
    if (!name) continue
    const isSuspect = entry.includes('`memory verify ')
    let rest = entry.slice(entry.indexOf('`', entry.indexOf(name)) + 1).trim()
    if (rest.startsWith('(')) rest = rest.slice(1)
    const cut = isSuspect ? rest.lastIndexOf(') (') : rest.lastIndexOf(')')
    pages.push({ name, summary: (cut >= 0 ? rest.slice(0, cut) : rest).trim(), isSuspect })
  }
  return pages
}

export function parseRecovered(text: string): ToolNote['recovered'] {
  return [...text.matchAll(RECOVERED_RE)].map(m => ({ command: m[1], failures: Number(m[2]) }))
}

/** The status line text and the warnings worth a toast, from the SessionStart line. */
export function parseBrief(text: string): { status: string; warnings: string[] } | null {
  const at = text.indexOf('memory: ')
  if (at < 0) return null
  const line = text.slice(at)
  const m = BRIEF_RE.exec(line)
  if (!m) return { status: '◆ memory: needs setup', warnings: [line.split('. ')[0].replace(/^memory: /, '')] }
  const mode = m[2].startsWith('semantic') ? 'semantic' : m[2]
  const warnings = m[3]
    .split(/(?<=\.)\s+(?=[A-Z0-9])/)
    .map(s => s.trim())
    .filter(s => s && !BRIEF_QUIET.test(s))
  return { status: `◆ memory ${m[1]} · ${mode}`, warnings }
}

function keepLast<T>(map: Record<string, T>, key: string, value: T): Record<string, T> {
  const next = { ...map, [key]: value }
  const keys = Object.keys(next)
  for (const k of keys.slice(0, Math.max(0, keys.length - KEEP))) delete next[k]
  return next
}

async function uiEnabled($: EngineInterface): Promise<boolean> {
  try {
    const toml = await $.fs.read(`${await $.session.root()}/.claude/memory.toml`)
    return !/^\s*ui\s*=\s*false\b/m.test(toml)
  } catch {
    return true
  }
}

/** The brief on the status line, and its warnings as a toast once per distinct brief. */
async function showBrief($: EngineInterface, text: string) {
  const brief = parseBrief(text)
  if (!brief) return
  $.ui.status(brief.status)
  const warned = brief.warnings.join(' ')
  if (warned && (await read($, briefShown)) !== warned) {
    await update($, briefShown, () => warned)
    $.ui.toast(`memory: ${brief.warnings.join(' ')}`)
  }
}

export const register: Register = on => {
  // A resumed session stores its SessionStart line where neither session.append
  // nor $.session.messages() shows it, so ask memory for the brief directly.
  // Without --hook, doctor --brief reads no stdin and pulls nothing.
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    // on a timer, so the run outlives this dispatch and the first prompt never waits for it
    $.clock.after(0, () => {
      void (async () => {
        if (!(await uiEnabled($))) return
        const ran = await $.process.run([`${$.plugin.root}/bin/memory`, 'doctor', '--brief'], {
          cwd: await $.session.root(),
          timeoutMs: 15000,
        })
        if (ran.exitCode === 0) await showBrief($, ran.stdout)
      })().catch(() => {})
    })
    return result
  })

  on('tool.call', async ($, e, next) => {
    if (e.agentId === undefined) await update($, lastTool, () => e.tool_use_id)
    return next(e)
  })

  on('session.append', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    if (e.door === 'prompt') {
      await update($, lastPrompt, () => e.uuid)
      return next(e)
    }
    if (e.door !== 'hook-context' || e.origin.kind !== 'hook') return next(e)
    const text = textOf(e.message.content)
    if (!text.includes('memory: ') || !(await uiEnabled($))) return next(e)

    const event = e.origin.event
    if (event === 'UserPromptSubmit') {
      const pages = parseRecall(text)
      const prompt = await read($, lastPrompt)
      if (pages.length > 0 && prompt !== null) await update($, byPrompt, map => keepLast(map, prompt, pages))
    } else if (event === 'PostToolUse' || event === 'PostToolUseFailure') {
      const tool = await read($, lastTool)
      const pages = parseRecall(text)
      const recovered = parseRecovered(text)
      if (tool !== null && (pages.length > 0 || recovered.length > 0)) {
        await update($, byTool, map => keepLast(map, tool, { pages, recovered }))
      }
    } else if (event === 'Stop') {
      const names = STOP_RE.exec(text)?.[1]
      if (names) $.ui.toast(`✎ memory: ${names} failed and then worked; Claude was asked to write it up before stopping`)
    } else if (event === 'SessionStart') {
      await showBrief($, text)
    }
    return next(e)
  }).catch(($, e, next) => (next.called ? undefined : next(e)))

  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const pages = (await read($, byPrompt))[e.requestId]
    if (!pages || pages.length === 0) return next(e)
    const original = await next(e)
    const isOpen = (await read($, open))[e.requestId] === true
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {original}
        {drawPages($, e, e.requestId, pages, isOpen, 'retrieved')}
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
    <Box key={`memory-note-${id}`} flexDirection="column">
      {note.pages.length > 0 && drawPages($, e, id, note.pages, isOpen, 'match this error')}
      {note.recovered.map(r => (
        <Box flexDirection="row" paddingLeft={3}>
          <Text color="warning">✎ </Text>
          <Text color="subtle">memory: </Text>
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
  const noun = pages.length === 1 ? 'memory item' : 'memory items'
  const label = verb === 'retrieved' ? `${noun} retrieved` : `${noun} ${pages.length === 1 ? 'matches' : 'match'} this error`
  return (
    <Box key={`memory-${id}`} flexDirection="column" paddingLeft={3}>
      <Box flexDirection="row">
        <Button key={`toggle-${id}`} plain label={isOpen ? '−' : '+'} onPress={toggle} />
        <Text> </Text>
        <Text color="subtle">[</Text>
        <Text bold color="claude">{String(pages.length)}</Text>
        <Text color="subtle">] </Text>
        <Text color="suggestion">{label}</Text>
      </Box>
      {isOpen &&
        pages.map((p, i) => (
          <Box flexDirection="row" paddingLeft={2}>
            <Text color="subtle">{i === pages.length - 1 ? '└─ ' : '├─ '}</Text>
            <Text color={p.isSuspect ? 'warning' : 'success'}>◆ </Text>
            <Text bold color="claude">{p.name.replace(/\.md$/, '')}</Text>
            {p.isSuspect && <Text color="warning"> (suspect)</Text>}
            <Text dimColor italic wrap="truncate-end">{'  ' + p.summary}</Text>
          </Box>
        ))}
    </Box>
  )
}
