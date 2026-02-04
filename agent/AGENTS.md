# OpenCode Rules for Local LLM Models

This AGENTS.md file is optimized for local models running via llama.cpp.
The setup script copies this to `~/.config/opencode/AGENTS.md` for global rules.
You can also place a project-specific AGENTS.md in your project root.

### Response Guidelines

- Be direct and concise - avoid unnecessary preamble
- Focus on code and technical solutions
- When editing files, show only the relevant changes, not entire files
- Use markdown code blocks with language tags
- Prefer showing diffs or specific line changes over full file contents

### Context Efficiency

Local models have limited context windows. To work effectively:

- Focus on one task at a time
- Don't repeat large code blocks unnecessarily
- Summarize previous context when relevant
- Ask clarifying questions if the task is ambiguous
- When context is running low, summarize what you've learned before continuing

## Tool Usage Patterns

Use the available tools effectively to accomplish tasks.

### File Discovery (Glob, Grep)

- **Always search first** - Use Glob and Grep to find files
- Use Glob for filename patterns: `*.ts`, `src/**/*.py`
- Use Grep for content search: function names, class definitions, error messages
- Combine both: find files by name, then search within them

### Reading Files (Read)

- **Always read before editing** - Never edit a file you haven't read first
- Read the full file initially to understand structure
- For large files, read specific line ranges after initial scan
- Read related files to understand dependencies and usage

### Editing Files (Edit)

- **Prefer Edit over Write** for modifying existing files
- Provide enough context in `oldString` to uniquely identify the location
- Keep edits focused - one logical change at a time
- After editing, verify the change if the task is complex

### Running Commands (Bash)

- Use Bash for: running tests, building projects, git operations, checking status
- Prefer project-specific commands (npm test, cargo build) over generic ones
- Check command output for errors before proceeding
- For long-running commands, consider using appropriate timeouts

### Task Delegation (Task)

- Use Task for complex, multi-step operations that benefit from focused exploration
- Provide clear, specific instructions to the subagent
- Good for: exploring unfamiliar codebases, researching patterns, multi-file analysis

## Error Recovery

When operations fail, follow these recovery patterns:

### Edit Failures

1. **"oldString not found"** - Re-read the file; it may have changed or your context is stale
2. **"multiple matches"** - Include more surrounding context to make the match unique
3. **Syntax errors after edit** - Read the file again, check for formatting issues

### Command Failures

1. **Permission denied** - Check if sudo is needed, or if file permissions need adjustment
2. **Command not found** - Check if the tool is installed, or use full path
3. **Build/test failures** - Read error output carefully, fix one issue at a time

### General Recovery

- If stuck, re-read relevant files to refresh context
- Break complex tasks into smaller steps
- Ask for clarification if requirements are unclear
- If an approach isn't working after 2-3 attempts, try an alternative

## Agentic Workflow

When handling multi-step tasks:

1. **Understand** - Read relevant files and understand the current state
2. **Plan** - Break down the task into discrete steps (use the todo list)
3. **Execute** - Complete one step at a time, verifying as you go
4. **Verify** - Run tests, check for errors, confirm the change works
5. **Report** - Summarize what was done and any issues encountered

### Best Practices

- Complete current task before starting the next
- If a step fails, don't skip it - fix it or ask for help
- Keep track of what you've done and what remains
- Test changes incrementally when possible

## Code Standards

- Follow existing code style in the project
- Add comments only when logic is non-obvious
- Prefer simple, readable solutions over clever ones
- Handle errors appropriately
- Write code that is easy to maintain and modify

## Available Subagents

When appropriate, delegate to specialized subagents using @mention:

- **@review** - Code review agent. Use for reviewing changes, checking code quality, identifying security issues, and suggesting improvements. Read-only, cannot make changes.

- **@debug** - Debugging agent. Use for systematic investigation of bugs, analyzing error messages, tracing issues through code, and proposing fixes.

Use the Tab key to switch to **Plan mode** for read-only analysis and planning without making changes.
