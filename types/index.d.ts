/** A page a recall line named; `match` is how it matched, as `69% match, meaning+term`, when the line says. */
export type RecalledPage = { name: string; summary: string; isSuspect: boolean; match?: string }

/** What iirc said about one tool call: pages its error recalled, and commands it asked to have written up. */
/** What the hint row shows of the brief: green, yellow for a warning, red when iirc needs setup or migration; `fix` is the command that clears it. */
export type IircStatus = { level: 'ok' | 'warn' | 'error'; pages: number | null; mode: string | null; note: string | null; fix?: string }

/** What this session did with pages: distinct pages read or pulled, written, suggested by recall, and suggested then read; `missed` is each page suggested and never read, with how often, most first; `timeouts` counts recalls the hook's time limit killed. */
export type SessionCounts = { reads: number; writes: number; suggested: number; used: number; missed: [string, number][]; match: MatchAverages; timeouts: number }

/** The average match percentage of this session's suggestions: all of them, the ones read, and the ones not read; null with none. */
export type MatchAverages = { all: number | null; read: number | null; unread: number | null }

/** One store's state for the card, from `iirc doctor --health`. */
export type StoreHealth = { name: string; kind: string; pages: number; uncommitted: number; unpushed: number }

/** Trust and store state for the card: pages whose cited file changed, and each store. */
export type IircHealth = { suspect: string[]; stores: StoreHealth[] }

/** One page as `iirc show` returns it, for the pane's reader. */
export type ShownPage = {
  store: string
  name: string
  label: string
  path: string
  fm: Record<string, unknown>
  body: string
  links: string[]
  signals: { signal: string; level: 'suspect' | 'glance'; reason: string }[]
}

/** The pane's tabs: which one shows, the page in the page tab, and the pages before it for Back. */
export type Reader = { page: ShownPage | null; history: string[]; error: string | null; loading: string | null; tab: 'session' | 'page' }

/** Where `j` and `k` stand in each tab's stops, and the item each tab's content starts at under the fixed header. */
export type Cursor = { session: number; page: number; sessionTop: number; pageTop: number }

/** This session's pages by name, from `iirc summarize-session-usage`, for the Session tab; `gone` were renamed or deleted since. */
export type SessionPages = { read: string[]; written: string[]; suggested: string[]; used: string[]; gone: string[] }

export type ToolNote = { pages: RecalledPage[]; recovered: { command: string; failures: number }[] }

declare module 'claude-code' {
  interface PluginState {
    iirc: {
      byPrompt: Record<string, RecalledPage[]>
      byTool: Record<string, ToolNote>
      open: Record<string, boolean>
      lastPrompt: string | null
      lastTool: string | null
      briefShown: string | null
      /** The brief as the hint row draws it, before the session counts join it. */
      status: IircStatus | null
      /** Distinct pages this session read or pulled, and wrote, from `iirc summarize-session-usage`. */
      counts: SessionCounts
      /** Whether the hint row shows the brief; `/iirc status on|off`, kept in $.store. */
      isStatusShown: boolean
      /** The page the reader tab shows, and the way back. */
      reader: Reader
      /** Pages `/iirc show` read, by name, for the transcript card each one draws. */
      shownPages: Record<string, ShownPage>
      /** Where vi keys stand in each tab. */
      cursor: Cursor
      /** This session's suggested, read, and written pages, for the Session tab. */
      sessionPages: SessionPages
      /** Suspect pages and store state from `iirc doctor --health`, read as a plain /iirc runs. */
      health: IircHealth | null
      /** `iirc max-suggested-pages` as a plain /iirc last read it, for the drawn help. */
      maxSuggested: number | null
      /** Whether this compaction window asked `iirc remind-to-write --at compaction` already. */
      compactAsked: boolean
      /** The line `iirc remind-to-write --at compaction` printed, waiting for the next tool result or prompt. */
      compactNudge: string | null
    }
  }
}
