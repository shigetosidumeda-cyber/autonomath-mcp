// /healthz — Fly.io / uptime probe.
// Lightweight: no DB, no upstream call. Returns 200 if process is alive.

import { Router } from 'express';

export const healthRouter = Router();

healthRouter.get('/', (_req, res) => {
  res.json({
    status: 'ok',
    name: 'jpcite-freee-plugin',
    version: '0.2.0',
    time: new Date().toISOString(),
  });
});
