const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  'host',
  'content-length',
  'accept-encoding',
])

function envOf(context) {
  const local = typeof process !== 'undefined' && process.env ? process.env : {}
  return { ...local, ...(context && context.env ? context.env : {}) }
}

function allowedOrigins(context) {
  return String(envOf(context).CORS_ORIGINS || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean)
}

function corsHeaders(context) {
  const origin = context && context.request ? context.request.headers.get('origin') : ''
  if (!origin) return {}

  const allowed = allowedOrigins(context)
  if (allowed.includes('*')) {
    return {
      'access-control-allow-origin': '*',
      'access-control-allow-methods': 'GET,POST,OPTIONS',
      'access-control-allow-headers': 'content-type,authorization',
    }
  }
  if (allowed.includes(origin)) {
    return {
      'access-control-allow-origin': origin,
      'access-control-allow-methods': 'GET,POST,OPTIONS',
      'access-control-allow-headers': 'content-type,authorization',
      vary: 'Origin',
    }
  }
  return {}
}

export function json(context, data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      ...corsHeaders(context),
      ...headers,
    },
  })
}

function backendBase(context) {
  return String(envOf(context).SENTINEL_API_URL || '')
    .trim()
    .replace(/\/+$/, '')
}

function timeoutMs(context) {
  const value = Number(envOf(context).SENTINEL_PROXY_TIMEOUT_MS || 110000)
  if (!Number.isFinite(value) || value <= 0) return 110000
  return Math.min(value, 115000)
}

export async function proxy(context, path, options = {}) {
  const expectedMethod = String(options.method || 'GET').toUpperCase()
  const request = context.request
  const method = request.method.toUpperCase()

  if (method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        ...corsHeaders(context),
        'access-control-max-age': '86400',
      },
    })
  }

  if (method !== expectedMethod) {
    return json(context, { detail: `Method ${method} tidak didukung; gunakan ${expectedMethod}.` }, 405, {
      allow: expectedMethod,
    })
  }

  const base = backendBase(context)
  if (!base) {
    return json(context, {
      detail: 'SENTINEL_API_URL belum diset di environment EdgeOne.',
    }, 500)
  }

  const source = new URL(request.url)
  const target = new URL(base + path)
  if (options.forwardQuery !== false) target.search = source.search

  const headers = new Headers()
  for (const [key, value] of request.headers) {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== 'origin') {
      headers.set(key, value)
    }
  }

  const env = envOf(context)
  if (env.SENTINEL_API_TOKEN) {
    headers.set('authorization', `Bearer ${env.SENTINEL_API_TOKEN}`)
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs(context))

  try {
    const init = {
      method: expectedMethod,
      headers,
      signal: controller.signal,
      redirect: 'follow',
    }
    if (expectedMethod !== 'GET' && expectedMethod !== 'HEAD') {
      init.body = await request.text()
    }

    const response = await fetch(target.toString(), init)
    const body = await response.text()
    const responseHeaders = new Headers(corsHeaders(context))
    responseHeaders.set('cache-control', response.headers.get('cache-control') || 'no-store')
    const contentType = response.headers.get('content-type')
    if (contentType) responseHeaders.set('content-type', contentType)

    return new Response(body, { status: response.status, headers: responseHeaders })
  } catch (error) {
    if (error && error.name === 'AbortError') {
      return json(context, {
        detail: `Backend timeout setelah ${timeoutMs(context)} ms.`,
      }, 504)
    }
    return json(context, {
      detail: 'Backend tidak dapat dihubungi.',
      error: error && error.message ? error.message : String(error),
    }, 502)
  } finally {
    clearTimeout(timer)
  }
}
