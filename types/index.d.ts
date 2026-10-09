export type RecalledPage = { name: string; summary: string; isSuspect: boolean }

/** What iirc said about one tool call: pages its error recalled, and commands it asked to have written up. */
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
    }
  }
}
