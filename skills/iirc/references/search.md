# How search ranks, and searching in string mode

## How search ranks

Every search runs two paths and fuses them: semantic search over the
whole query, and exact-text matching of the query's distinctive terms
against every page's name, title, summary, and body, leaving out its
Sources section and `[[links]]`. A term in more than a tenth of the
pages is common and does not rank. A page found by both with a rare term
ranks first; then semantic hits by distance; then string-only hits, most
rare terms first. Each line says how it was found,
`via semantic, install, pysqlite3`. Trust a page found by both. Read a
string-only hit before relying on it.

## Searching in string mode

When `doctor` says the mode is string, or every result says "string
match", only the exact-text path is running. A question sent as-is finds
nothing. Do this instead:

1. Pull the distinctive terms out of the question: tool names, file
   names, error text, hostnames, the one noun the page would have to
   mention. "Why does install fail on a mac" becomes
   `install pysqlite3 macos wheel`.
2. Search them in one call; pages matching more terms rank first.
3. Nothing? `iirc topics` lists every topic with its page count; search
   the nearest topics. Try shorter stems (`instal`, `sqlite`) and synonyms.
4. Read the top two or three pages with `iirc pull` or `iirc read`
   rather than stopping at the summaries.

Tell the creator when a search came back empty in string mode, so they
know the limit is the mode and not the pages. If ollama cannot run on
this machine, `iirc setup --cpu` gives search by meaning without it;
offer it, and run it on their yes.
