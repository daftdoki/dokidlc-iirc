export type RecalledPage = { name: string; summary: string; isSuspect: boolean }

/** What iirc said about one tool call: pages its error recalled, and commands it asked to have written up. */
/** What the hint row shows of the brief: green, yellow for a warning, red when iirc needs setup or migration. */
export type IircStatus = { level: 'ok' | 'warn' | 'error'; pages: number | null; mode: string | null; note: string | null }

/** What this session did with pages: distinct pages read or pulled, and written. */
export type SessionCounts = { reads: number; writes: number }

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
    }
  }
}
