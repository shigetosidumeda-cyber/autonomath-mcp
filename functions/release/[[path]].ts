/// <reference types="@cloudflare/workers-types" />

export interface Env {
  ASSETS: Fetcher;
}

type RuntimePointer = {
  active_capsule_id?: string;
  active_capsule_manifest?: string;
  live_aws_commands_allowed?: boolean;
  aws_runtime_dependency_allowed?: boolean;
};

const ACTIVE_POINTER_PATH = "/releases/current/runtime_pointer.json";
const ACTIVE_CAPSULE_ID = "rc1-p0-bootstrap-2026-05-15";
const ACTIVE_CAPSULE_DIR = "rc1-p0-bootstrap";
const DIRECT_CAPSULE_RE = /^\/release\/(rc1-p0-bootstrap)\/(.+)$/;
const CURRENT_ALIAS_TARGETS: Record<string, string> = {
  "/release/current/capsule_manifest.json": "release_capsule_manifest.json",
  "/release/current/capability_matrix.json": "capability_matrix.json",
  "/release/current/capability_matrix.public.json": "capability_matrix.json",
  "/release/current/agent_surface/p0_facade.json": "agent_surface/p0_facade.json",
  "/release/current/agent_surface_manifest.json": "agent_surface/p0_facade.json",
  "/release/current/preflight_scorecard.json": "preflight_scorecard.json",
  "/release/current/zero_aws_posture_manifest.json": "preflight_scorecard.json",
  "/release/current/noop_aws_command_plan.json": "noop_aws_command_plan.json",
};

const SECURITY_HEADERS: Record<string, string> = {
  "Content-Security-Policy":
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Cross-Origin-Resource-Policy": "cross-origin",
};

function jsonHeaders(extra: Record<string, string> = {}): Headers {
  return new Headers({
    ...SECURITY_HEADERS,
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
    ...extra,
  });
}

function jsonError(status: number, error: string, message: string): Response {
  return new Response(JSON.stringify({ error, message }), {
    status,
    headers: jsonHeaders({ "cache-control": "no-store" }),
  });
}

function assetRequest(request: Request, path: string): Request {
  const url = new URL(request.url);
  url.pathname = path;
  url.search = "";
  return new Request(url.toString(), request);
}

async function fetchAsset(env: Env, request: Request, path: string): Promise<Response> {
  return env.ASSETS.fetch(assetRequest(request, path));
}

async function loadPointer(env: Env, request: Request): Promise<RuntimePointer | null> {
  const response = await fetchAsset(env, request, ACTIVE_POINTER_PATH);
  if (!response.ok) {
    return null;
  }
  try {
    return (await response.json()) as RuntimePointer;
  } catch {
    return null;
  }
}

function activeCapsuleDir(pointer: RuntimePointer | null): string | null {
  if (pointer === null) {
    return null;
  }
  if (
    pointer.live_aws_commands_allowed !== false ||
    pointer.aws_runtime_dependency_allowed !== false
  ) {
    return null;
  }
  const capsuleId = String(pointer.active_capsule_id ?? "");
  if (capsuleId !== ACTIVE_CAPSULE_ID) {
    return null;
  }
  const manifestPath = String(pointer.active_capsule_manifest ?? "");
  if (manifestPath !== `/releases/${ACTIVE_CAPSULE_DIR}/release_capsule_manifest.json`) {
    return null;
  }
  return ACTIVE_CAPSULE_DIR;
}

function capsuleAssetPath(capsuleId: string, relativePath: string): string | null {
  if (
    relativePath.length === 0 ||
    relativePath.length > 160 ||
    relativePath.startsWith("/") ||
    relativePath.includes("..") ||
    relativePath.includes("\\") ||
    relativePath.includes("_internal")
  ) {
    return null;
  }
  return `/releases/${capsuleId}/${relativePath}`;
}

function withReleaseHeaders(
  response: Response,
  cacheControl: string,
  capsuleId: string,
): Response {
  const headers = jsonHeaders({
    "cache-control": cacheControl,
    "x-jpcite-release-capsule": capsuleId,
  });
  const contentType = response.headers.get("content-type");
  if (contentType !== null) {
    headers.set("content-type", contentType);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export const onRequest: PagesFunction<Env> = async ({ request, env }) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return jsonError(405, "method_not_allowed", "release aliases are read-only");
  }

  const url = new URL(request.url);
  const currentTarget = CURRENT_ALIAS_TARGETS[url.pathname];
  if (currentTarget !== undefined) {
    const capsuleDir = activeCapsuleDir(await loadPointer(env, request));
    if (capsuleDir === null) {
      return jsonError(
        503,
        "capsule_pointer_invalid",
        "active release capsule pointer is missing, unsafe, or AWS-enabled",
      );
    }
    const assetPath = capsuleAssetPath(capsuleDir, currentTarget);
    if (assetPath === null) {
      return jsonError(503, "capsule_target_invalid", "release alias target is unsafe");
    }
    const response = await fetchAsset(env, request, assetPath);
    if (!response.ok) {
      return jsonError(503, "capsule_asset_missing", assetPath);
    }
    return withReleaseHeaders(response, "public, max-age=60, s-maxage=60", ACTIVE_CAPSULE_ID);
  }

  const direct = url.pathname.match(DIRECT_CAPSULE_RE);
  if (direct !== null) {
    const capsuleId = direct[1];
    const assetPath = capsuleAssetPath(capsuleId, direct[2]);
    if (assetPath === null) {
      return jsonError(404, "release_asset_not_found", "release path is unsafe");
    }
    const response = await fetchAsset(env, request, assetPath);
    if (!response.ok) {
      return jsonError(404, "release_asset_not_found", assetPath);
    }
    return withReleaseHeaders(
      response,
      "public, max-age=31536000, immutable",
      capsuleId,
    );
  }

  return jsonError(404, "release_alias_not_found", url.pathname);
};
