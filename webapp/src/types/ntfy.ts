/**
 * Zod schemas and TypeScript types for ntfy configuration API responses.
 *
 * Mirrors the Pydantic NtfyConfigResponse model from
 * automator/src/api/config_routes.py.
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Response Schema (GET /config/ntfy and PUT /config/ntfy)
// ---------------------------------------------------------------------------

export const NtfyConfigResponseSchema = z.object({
  ntfy_enabled: z.boolean(),
  ntfy_server_url: z.string(),
  urgent_topic: z.string().nullable(),
  info_topic: z.string().nullable(),
  lan_base_url: z.string().nullable(),
});

// ---------------------------------------------------------------------------
// Update Payload (PUT /config/ntfy request body)
// ---------------------------------------------------------------------------

export const NtfyConfigUpdateSchema = z.object({
  ntfy_enabled: z.boolean(),
  ntfy_server_url: z.string(),
  lan_base_url: z.string().nullable(),
});

// ---------------------------------------------------------------------------
// Inferred TypeScript Types
// ---------------------------------------------------------------------------

export type NtfyConfigResponse = z.infer<typeof NtfyConfigResponseSchema>;
export type NtfyConfigUpdate = z.infer<typeof NtfyConfigUpdateSchema>;
