// tools/websearch.ts
import { tool } from "@opencode-ai/plugin"
import { $ } from 'bun'

export default tool({
  description: "Search the web for current information using local SearXNG",
  args: {
    query: tool.schema.string().describe("Search query"),
  },
  async execute(args) {
    try {
      // Call your rag-web.sh script
      const result = await $`./rag-web.sh "${args.query}"`.text()
      return result
    } catch (error) {
      return `Web search error: ${error.message}. Ensure SearXNG is running (docker-compose up -d searxng).`
    }
  },
})