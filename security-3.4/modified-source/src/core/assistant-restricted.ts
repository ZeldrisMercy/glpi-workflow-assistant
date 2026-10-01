import { createHash, timingSafeEqual } from 'node:crypto';
import type { NextFunction, Request, Response } from 'express';

// Opt-in profile. Native authentication remains active after these restrictions.
export function restrictedKeyValid(key: unknown, hash = process.env.WAHA_ASSISTANT_CLIENT_KEY_HASH): boolean {
  if (typeof key !== 'string' || key.length < 32 || key.length > 256 || !/^sha512:[a-f0-9]{128}$/.test(hash ?? '')) return false;
  const actual = createHash('sha512').update(key).digest();
  return timingSafeEqual(actual, Buffer.from(hash!.slice(7), 'hex'));
}

export function validateRestrictedEnvironment(env: NodeJS.ProcessEnv): void {
  const disabled = ['WAHA_DASHBOARD_ENABLED', 'WHATSAPP_SWAGGER_ENABLED', 'WAHA_EVENTS_DOWNLOAD_MEDIA', 'WAHA_API_DOWNLOAD_MEDIA', 'WHATSAPP_DOWNLOAD_MEDIA'];
  if (!/^sha512:[a-f0-9]{128}$/.test(env.WAHA_ASSISTANT_CLIENT_KEY_HASH ?? '') ||
      !/^sha512:[a-f0-9]{128}$/.test(env.WAHA_API_KEY ?? '') ||
      env.WAHA_API_KEY === env.WAHA_ASSISTANT_CLIENT_KEY_HASH ||
      env.WHATSAPP_DEFAULT_ENGINE !== 'WEBJS' || disabled.some((key) => env[key] !== 'false') ||
      env.WAHA_NO_API_KEY === 'true' || env.WAHA_API_KEY_EXCLUDE_PATH || env.WAHA_API_KEY_PLAIN) {
    throw new Error('Restricted profile requires separate hashed keys, WEBJS, authentication and disabled panels/media');
  }
}

export function restrictedRoute(method: string, url: string): boolean {
  if (method === 'GET') {
    if (['/api/sessions/default', '/api/sessions?all=true', '/api/default/auth/qr'].includes(url)) return true;
    if (/^\/api\/contacts\/check-exists\?phone=55[0-9]{10,11}&session=default$/.test(url)) return true;
    if (/^\/api\/default\/lids\/[0-9]{5,20}$/.test(url)) return true;
    return /^\/api\/default\/chats\/(?:[0-9]{10,15}%40c\.us|[0-9]{5,20}%40lid)\/messages\/[A-Za-z0-9%._-]{1,750}\?downloadMedia=false$/.test(url);
  }
  return method === 'POST' && ['/api/sessions', '/api/sessions/default/start', '/api/sessions/default/restart', '/api/sendText'].includes(url);
}

export function restrictedBody(url: string, body: unknown): boolean {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return false;
  const value = body as Record<string, unknown>;
  const keys = Object.keys(value).sort().join(',');
  if (url === '/api/sessions') return keys === 'name,start' && value.name === 'default' && value.start === true;
  if (['/api/sessions/default/start', '/api/sessions/default/restart'].includes(url)) return keys === '';
  if (url !== '/api/sendText') return false;
  return keys === 'chatId,linkPreview,session,text' && value.session === 'default'
    && typeof value.chatId === 'string' && /^(?:[0-9]{10,15}@c\.us|[0-9]{5,20}@lid)$/.test(value.chatId)
    && typeof value.text === 'string' && value.text.length > 0 && value.text.length <= 4000
    && value.linkPreview === false;
}

export function restrictedRoutes(req: Request, res: Response, next: NextFunction) {
  // Auth before parsing the body; the administrative key is not accepted here.
  if (!restrictedKeyValid(req.headers['x-api-key'])) {
    res.status(401).json({ error: 'Invalid restricted credential' });
    return;
  }
  if (req.headers.origin || !restrictedRoute(req.method, req.originalUrl)) {
    res.status(403).json({ error: 'Disabled in Assistant restricted mode' });
    return;
  }
  if (req.method === 'POST' && !/^application\/json(?:\s*;.*)?$/i.test(String(req.headers['content-type'] ?? ''))) {
    res.status(415).json({ error: 'JSON required' });
    return;
  }
  next();
}

export function restrictedBodies(req: Request, res: Response, next: NextFunction) {
  if (req.method === 'POST' && !restrictedBody(req.originalUrl, req.body)) {
    res.status(400).json({ error: 'Invalid restricted request' });
    return;
  }
  next();
}
