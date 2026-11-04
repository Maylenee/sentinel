import { json, proxy } from '../../_lib/proxy.js'

export function onRequest(context) {
  const id = new URL(context.request.url).searchParams.get('id')
  if (!id) return json(context, { detail: 'Query id wajib diisi.' }, 400)
  return proxy(context, `/api/job/${encodeURIComponent(id)}`, { method: 'GET', forwardQuery: false })
}
