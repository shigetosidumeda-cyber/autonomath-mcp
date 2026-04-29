// /healthz — Fly.io / uptime probe.
// Lightweight: no DB, no upstream call. Returns 200 if process is alive.

import { Router } from 'express';

export const healthRouter = Router();

healthRouter.get('/', (_req, res) => {
  res.json({
    status: 'ok',
    name: 'zeimu-kaikei-ai-freee-plugin',
    version: '0.1.0',
    time: new Date().toISOString(),
  });
});
