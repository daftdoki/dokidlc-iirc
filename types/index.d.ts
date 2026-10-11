/** A page a recall line named; `match` is how it matched, as `69% match, meaning+term`, when the line says. */
export type RecalledPage = { name: string; summary: string; isSuspect: boolean; match?: string }

/** What iirc said about one tool call: pages its error recalled, and commands it asked to have written up. */
/** What the lines at the prompt show of the brief: green, yellow for a warning, red when iirc needs setup or migration; `problems` each one the brief names with a command, in its order (`actions` sorts them). */
export type IircStatus = { level: 'ok' | 'warn' | 'error'; pages: number | null; mode: string | null; note: string | null; problems?: Problem[] }

/** One thing the person needs to do: the command that does it, if the brief names one, and why, in the brief's words. */
export type Problem = { level: 'warn' | 'error'; fix?: string; why: string }

/** What this session did with pages: distinct pages read or pulled, written, suggested by recall, and suggested then read; `searches` counts its own `iirc search` and `iirc read-matching-pages` runs; `missed` is each page suggested and never read, with how often, most first; `timeouts` counts recalls the hook's time limit killed. */
export type SessionCounts = { reads: number; writes: number; searches: number; suggested: number; used: number; missed: [string, number][]; match: MatchAverages; timeouts: number }

/** Counters that rose a moment ago, by SessionCounts key: how much, and which rise lit it, so its timer puts out only its own. */
export type Flash = Partial<Record<'suggested' | 'used' | 'searches' | 'reads' | 'writes', { by: number; gen: number }>>

/** The average match percentage of this session's suggestions: all of them, the ones read, and the ones not read; null with none. */
export type MatchAverages = { all: number | null; read: number | null; unread: number | null }

/** One store's state for the card, from `iirc doctor --health`. */
export type StoreHealth = { name: string; kind: string; pages: number; uncommitted: number; unpushed: number }

/** Trust and store state for the card: pages whose cited file changed, each store, and why run-maintenance is due. */
export type IircHealth = { suspect: string[]; stores: StoreHealth[]; due?: string[] }

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
/** What the reader's Session tab draws: this session's pages, counts, and health, or the demo's sample. */
export type SessionView = { pages: SessionPages; counts: SessionCounts; health: IircHealth | null }

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
      /** Whether the band above the prompt shows the summary line; `/iirc summary-line-visibility on|off`, kept in $.store. */
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
      /** `/iirc reader demo`'s sample session, which only the reader's Session tab draws, until the reader closes. */
      demoSession: SessionView | null
      /** `iirc max-suggested-pages` as a plain /iirc last read it, for the drawn help. */
      maxSuggested: number | null
      /** Counters that rose a moment ago, which the band lights up until a timer puts each out. */
      flash: Flash
      /** Whether this session's counts loaded once: the first load rises from nothing and lights nothing. */
      countsLoaded: boolean
      /** The frame of the band's circle while the suggestion hook runs; null when it does not. */
      pulse: number | null
      /** Whether this compaction window asked `iirc remind-to-write --at compaction` already. */
      compactAsked: boolean
      /** The line `iirc remind-to-write --at compaction` printed, waiting for the next tool result or prompt. */
      compactNudge: string | null
    }
  }
}
