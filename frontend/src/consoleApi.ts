import { useCallback, useEffect, useState } from 'react'
import type { CourseItem } from './types'

export type Runtime = { mode: 'observe' | 'trial' | 'auto'; auto_signin: boolean; submit_answers: boolean; course_ids: string[]; poll_interval: number; submit_reserve: number; ai_timeout: number }
export const DEFAULT_RUNTIME: Runtime = { mode: 'observe', auto_signin: false, submit_answers: false, course_ids: [], poll_interval: 30, submit_reserve: 3, ai_timeout: 90 }
export interface Activity { type: string; status?: string; logged_at?: string; lesson?: string; lessonid?: string; problemid?: string; problemtype?: number; message?: string; answers?: unknown; question?: { body?: string; content?: string; title?: string; options?: { key: string; value?: string; content?: string }[]; _cover?: string } }
export interface Diagnostic { ok: boolean; simulation: boolean; passed: number; total: number; elapsed_seconds: number; tested_at: string; cases: { id: string; label: string; passed: boolean; actual: string; requests: number; payload: unknown }[] }
export interface Health {
  server: string; version?: string; domain: string; login_verified: boolean; needs_setup?: boolean; runtime: Runtime;
  monitor: null | { state: string; discovery_healthy: boolean; last_error: string | null; last_success: number; poll_age_seconds: number; discovered: { lessonid: string; classroomid: string; name: string }[]; lessons: { lessonid: string; lessonname: string; connected: boolean; connection_state: string; last_pong: number; cached_problems: number; presentations: number }[] };
  vision_validation?: { correct?: boolean; current_config?: boolean; active_model?: string; elapsed_seconds?: number; tested_at?: number };
  submission_validation?: Diagnostic;
}
export interface AISettings { active_key: number; keys: { name: string; model?: string; provider: string; key: string; base_url?: string }[] }

export async function api<T>(url: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch(url, body === undefined ? undefined : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!response.ok) throw new Error(`请求未完成（HTTP ${response.status}）`)
  return response.json() as Promise<T>
}

export function useConsoleData() {
  const [health, setHealth] = useState<Health | null>(null)
  const [courses, setCourses] = useState<CourseItem[]>([])
  const [events, setEvents] = useState<Activity[]>([])
  const [ai, setAi] = useState<AISettings>({ active_key: -1, keys: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    try {
      const [h, c, e, a] = await Promise.all([api<Health>('/api/health'), api<CourseItem[]>('/api/courses/all'), api<Activity[]>('/api/events/recent'), api<AISettings>('/api/ai/settings')])
      setHealth(h); setCourses(c); setEvents(e); setAi(a); setError('')
    } catch { setHealth(null); setError('暂时无法连接本机服务，请检查程序是否运行。') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { refresh(); const timer = setInterval(refresh, 3000); return () => clearInterval(timer) }, [refresh])
  return { health, courses, events, ai, loading, error, refresh }
}

export const modeName = (mode?: string) => ({ observe: '观察模式', trial: 'AI 试答', auto: '自动运行' }[mode || 'observe'] || '观察模式')
export const formatTime = (epoch?: number) => epoch ? new Date(epoch * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : '尚无记录'
export const statusName = (status?: string) => ({ accepted: '服务器已接受', rejected: '服务器拒绝', sent: '等待服务器确认', preview: '试答 · 未提交', valid: 'AI 答案已生成', timeout: '超时 · 已跳过', ai_failed: 'AI 失败 · 已跳过', unknown: '结果未知 · 请核对', duplicate: '重复事件已跳过', unsupported: '暂不支持 · 已跳过', cache_missing: '题面缺失', incomplete: '题面不完整', cancelled: '已取消', connected: '连接已确认', reused: '已复用签到', passed: '自检通过', failed: '未通过', ready: '题面就绪', error: '发生错误', waiting: '等待开课', watching: '正在发现课堂', skipped: '已跳过' }[status || ''] || status || '已记录')
