/** 统一请求封装：拼后端地址、带登录身份头、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function authHeaders(): Record<string, string> {
  return useSessionStore().authHeaders()
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init?.headers ?? {}) },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

/** 4xx 时把后端 detail 原样抛出来，页面上才能显示“为什么被拦下”。 */
export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  const text = await response.text()
  const payload = text ? (JSON.parse(text) as unknown) : null
  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : `接口返回 ${response.status}`
    throw new Error(detail)
  }
  return payload as T
}

export async function fetchJson<T>(path: string): Promise<T> {
  return requestJson<T>(path)
}
