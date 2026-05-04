// MCP stdio bridge.
//
// The jpcite MCP server is currently distributed as the Python package
// `autonomath-mcp` for compatibility.
// This module spawns it as a child process so Node-based MCP hosts (Claude Desktop
// custom configs, Continue, Cline, custom agents) can use it without re-implementing
// the 96-tool surface in TypeScript.
//
// Prerequisite:
//   pip install autonomath-mcp
//   # or:  pipx install autonomath-mcp
//
// Usage:
//
//   import { spawnMcp } from "@autonomath/sdk/mcp";
//
//   const mcp = spawnMcp({
//     apiKey: process.env.JPCITE_API_KEY,
//   });
//
//   // pipe to/from your MCP host
//   process.stdin.pipe(mcp.stdin!);
//   mcp.stdout!.pipe(process.stdout);
//
//   mcp.on("exit", (code) => console.error(`mcp exited ${code}`));

import { spawn, type ChildProcessWithoutNullStreams, type SpawnOptions } from "node:child_process";

export interface SpawnMcpOptions {
  /**
   * jpcite REST/MCP API key. This is sent as X-API-Key by the child and is not
   * an LLM provider key. Sets JPCITE_API_KEY, plus the legacy AUTONOMATH_API_KEY
   * alias for older MCP package releases.
   */
  apiKey?: string;
  /** Override executable. Default: "autonomath-mcp" (resolved from PATH). */
  command?: string;
  /** Extra args appended to the spawn. */
  args?: string[];
  /** Override base URL (self-host). Sets JPCITE_API_BASE plus the legacy alias. */
  baseUrl?: string;
  /** Extra env vars. Merged with `process.env`. */
  env?: NodeJS.ProcessEnv;
  /** Working directory. Default: process.cwd(). */
  cwd?: string;
  /** stdio mode. Default "pipe" so caller can pipe stdin/stdout. */
  stdio?: SpawnOptions["stdio"];
}

/**
 * Spawn the Python `autonomath-mcp` server as a child process.
 *
 * Returns the child process. Stdin/stdout are JSON-RPC streams (MCP stdio
 * transport). The host (Claude Desktop, agent, etc.) is responsible for the
 * MCP handshake — this function only wires the process.
 *
 * Throws if the executable can't be found. Consider using `which autonomath-mcp`
 * before calling, or catch the spawn error event.
 */
export function spawnMcp(options: SpawnMcpOptions = {}): ChildProcessWithoutNullStreams {
  const command = options.command ?? "autonomath-mcp";
  const args = options.args ?? [];

  const env: NodeJS.ProcessEnv = {
    ...process.env,
    ...options.env,
  };
  if (options.apiKey) {
    env["JPCITE_API_KEY"] = options.apiKey;
    env["AUTONOMATH_API_KEY"] = options.apiKey;
  }
  if (options.baseUrl) {
    env["JPCITE_API_BASE"] = options.baseUrl;
    env["AUTONOMATH_API_BASE"] = options.baseUrl;
  }

  const child = spawn(command, args, {
    cwd: options.cwd ?? process.cwd(),
    env,
    stdio: options.stdio ?? "pipe",
  }) as ChildProcessWithoutNullStreams;

  return child;
}

/**
 * MCP server config object that can be JSON-serialized into a host's
 * MCP servers config (e.g. Claude Desktop `claude_desktop_config.json`).
 *
 *   {
 *     "mcpServers": {
 *       "jpcite": mcpServerConfig({ apiKey: "am_..." })
 *     }
 *   }
 */
export function mcpServerConfig(options: {
  apiKey?: string;
  baseUrl?: string;
  command?: string;
} = {}): {
  command: string;
  args: string[];
  env: Record<string, string>;
} {
  const env: Record<string, string> = {};
  if (options.apiKey) env["JPCITE_API_KEY"] = options.apiKey;
  if (options.baseUrl) env["JPCITE_API_BASE"] = options.baseUrl;
  return {
    command: options.command ?? "autonomath-mcp",
    args: [],
    env,
  };
}
