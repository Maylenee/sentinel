import { proxy } from '../../_lib/proxy.js'

export function onRequest(context) {
  return proxy(context, '/api/post', { method: 'POST' })
}
