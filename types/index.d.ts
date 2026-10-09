/** A page a recall line named; `match` is how it matched, as `69% match, meaning+term`, when the line says. */
export type RecalledPage = { name: string; summary: string; isSuspect: boolean; match?: string }

/** What iirc said about one tool call: pages its error recalled, and commands it asked to have written up. */
/** What the hint row shows of the brief: green, yellow for a warning, red when iirc needs setup or migration; `fix` is the command that clears it. */
export type IircStatus = { level: 'ok' | 'warn' | 'error'; pages: number | null; mode: string | null; note: string | null; fix?: string }

/** What this session did with pages: distinct pages read or pulled, written, suggested by recall, and suggested then read. */
export type SessionCounts = { reads: number; writes: number; suggested: number; used: number }

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
      /** Distinct pages this session read or pulled, and wrote, from `iirc stats --session`. */
      counts: SessionCounts
      /** Whether the hint row shows the brief; `/iirc status on|off`, kept in $.store. */
      isStatusShown: boolean
      /** `iirc max-suggested` as a plain /iirc last read it, for the drawn help. */
      maxSuggested: number | null
    }
  }
}
