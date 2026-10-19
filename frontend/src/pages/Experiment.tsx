import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, DEFAULT_RUNTIME, formatTime, modeName, statusName, useConsoleData, type Activity, type Diagnostic, type Runtime } from '../consoleApi'
import { CoursePicker, ModelPanel, ModeControl } from '../components/ConsoleControls'

type Tab = 'overview' | 'courses' | 'model' | 'checks'
const TABS: [Tab, string][] = [['overview', '运行概览'], ['courses', '课程范围'], ['model', '模型连接'], ['checks', '提交自检']]
const TYPES: Record<number, string> = { 1: '单选题', 2: '多选题', 3: '投票题', 4: '填空题', 5: '简答题' }
const errorStates = new Set(['error', 'rejected', 'unknown', 'ai_failed', 'invalid', 'cache_missing', 'failed'])
function eventTitle(event: Activity) {
  if (event.type === 'problem') return `${TYPES[event.problemtype || 0] || '题目'} · ${statusName(event.status)}`
  return ({ signin: '课堂签到', connection: '课堂连接', lesson_start: '发现课堂', lesson_end: '课堂结束', problem_received: '收到新题', question: '完整题面已就绪', ai: 'AI 作答', monitor: '课程发现', runtime: '运行设置已更新', vision_test: '图片输入验证', submission_test: '模拟提交自检', problem_cache: '课件缓存', session_expired: '登录已过期' }[event.type] || event.type)
}
function answers(value: unknown): string { return Array.isArray(value) ? value.join('、') : typeof value === 'string' ? value : value ? JSON.stringify(value) : '' }

export default function Experiment() {
  const data = useConsoleData()
  const { health, courses, events, ai, loading, error, refresh } = data
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('overview')
  const [draft, setDraft] = useState<Runtime>(DEFAULT_RUNTIME)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [filter, setFilter] = useState('important')
  const [report, setReport] = useState<Diagnostic | null>(null)
  const edit = (value: Runtime) => { setDraft(value); setDirty(true) }
  useEffect(() => { if (health && !dirty) setDraft(health.runtime) }, [health, dirty])
  useEffect(() => {
    if (health?.needs_setup && !sessionStorage.getItem('setup-snoozed')) navigate('/setup', { replace: true })
  }, [health?.needs_setup, navigate])
  const save = async () => {
    setBusy('save')
    try {
      const result = await api<{ ok: boolean; config: Runtime; error?: string }>('/api/runtime', draft, 'PUT')
      if (!result.ok) throw new Error(result.error || '设置保存失败')
      setDirty(false); setDraft(result.config); setMessage('设置已生效。后续课堂和新题将按当前设置处理。'); refresh()
    } catch (e) { setMessage(e instanceof Error ? e.message : '设置未保存') }
    finally { setBusy('') }
  }
  const stopActions = async () => {
    try {
      await api('/api/runtime', { mode: 'observe', auto_signin: false, submit_answers: false }, 'PUT')
      setDirty(false); setMessage('已切换为观察：停止进入课堂和提交，课程发现继续运行。'); refresh()
    } catch { setMessage('操作未完成，请检查本机服务。') }
  }
  const selfTest = async () => {
    setBusy('test')
    try {
      const result = await api<Diagnostic & { error?: string }>('/api/experiment/submission-test', {})
      if (!result.cases) throw new Error(result.error || '自检未完成')
      setReport(result); setMessage(`模拟提交自检：${result.passed}/${result.total}。真实课堂请求为 0。`); refresh()
    } catch (e) { setMessage(e instanceof Error ? e.message : '自检未完成') }
    finally { setBusy('') }
  }
  const latestQuestion = events.slice().reverse().find(event => event.type === 'question')
  const latestAnswer = latestQuestion ? events.slice().reverse().find(event => event.type === 'problem' && event.problemid === latestQuestion.problemid) : undefined
  const recent = events.slice().reverse().filter(event => filter === 'all' || (filter === 'errors' ? errorStates.has(event.status || '') || event.type === 'session_expired' : !['monitor', 'problem_cache'].includes(event.type)))
  const diagnostic = report || health?.submission_validation
  const connected = health?.monitor?.lessons.filter(lesson => lesson.connected && lesson.last_pong && Date.now() / 1000 - lesson.last_pong < 45).length || 0
  const accepted = events.filter(event => event.type === 'problem' && event.status === 'accepted').length
  const runtime = health?.runtime || DEFAULT_RUNTIME
  if (loading) return <div className="console-empty">正在连接课堂助手…</div>
  return <div className="console-page">
    <header className="console-hero"><div><div className="console-eyebrow"><span className={`status-dot ${health?.monitor?.discovery_healthy ? 'green' : 'amber'}`} /> 本机运行中心 <span className="version-tag">v{health?.version || '2.1.0'}</span></div><h1>课堂运行台</h1><p>{health?.monitor?.discovery_healthy ? '正在持续发现课程，课堂与作答结果会实时更新。' : health?.login_verified ? '账号已连接，请检查下方监听状态。' : '连接账号与模型，按你的课程范围开始监听。'}</p></div><div className="hero-actions"><Link className="console-button secondary" to="/setup">配置向导</Link><button className="console-button ghost" onClick={stopActions}>暂停自动操作</button></div></header>
    {error && <div className="console-notice error" role="alert">{error}</div>}
    {message && <div className="console-notice dismissible" role="status"><span>{message}</span><button aria-label="关闭消息" onClick={() => setMessage('')}>×</button></div>}
    <div className="metric-grid"><div className="metric-card"><span>账号连接</span><strong>{health?.login_verified ? '已验证' : '待登录'}</strong><small>{health?.domain || 'www.yuketang.cn'} {!health?.login_verified && <Link to="/login">去扫码 →</Link>}</small></div><div className="metric-card"><span>课堂连接</span><strong>{connected}<i> / {health?.monitor?.discovered.length || 0}</i></strong><small>{connected ? '心跳正常的连接 / 发现开课' : '没有连接时持续等待开课'}</small></div><div className="metric-card"><span>课程范围</span><strong>{runtime.course_ids.length}<i> 个班级</i></strong><small>{courses.length ? `已加入 ${courses.length} 个班级` : '扫码后同步班级'}</small></div><div className="metric-card accent"><span>当前运行方式</span><strong>{modeName(runtime.mode)}</strong><small>签到{runtime.auto_signin ? '开启' : '关闭'} · 提交{runtime.submit_answers ? '开启' : '关闭'}</small></div></div>
    <nav className="console-tabs" aria-label="运行台功能">{TABS.map(([id, text]) => <button key={id} aria-current={tab === id ? 'page' : undefined} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{text}</button>)}<span>{health ? '每 3 秒更新' : '服务不可达'}</span></nav>
    {tab === 'overview' && <div className="console-columns"><div className="console-stack"><section className="console-panel"><div className="panel-heading inline"><div><h2>正在监听</h2><p>进程存活和课堂在线分别核验</p></div><span className={`console-pill ${health?.monitor?.discovery_healthy ? 'green' : 'amber'}`}>{health?.monitor?.discovery_healthy ? '发现循环正常' : '等待验证'}</span></div><div className="heartbeat-line"><span>最近成功 {formatTime(health?.monitor?.last_success)}</span><span>{health?.monitor?.last_error ? `最近错误：${health.monitor.last_error}` : '未报告接口错误'}</span></div>
      {health?.monitor?.lessons.length ? health.monitor.lessons.map(lesson => <div className="lesson-card" key={lesson.lessonid}><div className="lesson-icon">课</div><div><h3>{lesson.lessonname}</h3><p>最近心跳 {formatTime(lesson.last_pong)} · 课件 {lesson.presentations} 份 · 缓存 {lesson.cached_problems} 题</p></div><span className={`console-pill ${lesson.connected && Date.now() / 1000 - lesson.last_pong < 45 ? 'green' : 'amber'}`}>{lesson.connected && Date.now() / 1000 - lesson.last_pong < 45 ? '连接在线' : '等待重连'}</span></div>) : <div className="console-empty compact"><div className="empty-symbol">◌</div><h3>{runtime.mode === 'observe' ? '正在观察课程开课' : '等待选中班级开始上课'}</h3><p>{runtime.mode === 'observe' ? '观察模式不会进入或签到。需要取题时，可调整右侧运行方式。' : '课程出现后会按签到和提交开关处理，无需逐节选择。'}</p></div>}</section>
      {latestQuestion && <section className="console-panel"><div className="panel-heading inline"><div><h2>最近一道题</h2><p>{latestQuestion.lesson} · {TYPES[latestQuestion.problemtype || 0] || '题目'}</p></div><span className="console-pill blue">{statusName(latestAnswer?.status || 'ready')}</span></div><p className="question-body">{latestQuestion.question?.body || latestQuestion.question?.content || latestQuestion.question?.title || '题目文字在课件中'}</p><div className="question-options">{latestQuestion.question?.options?.map(option => <div key={option.key}><b>{option.key}</b><span>{option.value || option.content}</span></div>)}</div>{latestAnswer?.answers !== undefined && <div className="answer-result"><span>AI 答案</span><strong>{answers(latestAnswer.answers)}</strong><small>{statusName(latestAnswer.status)}</small></div>}{latestQuestion.question?._cover && <details className="help-details"><summary>查看课件题图</summary><img src={`/api/lessons/${latestQuestion.lessonid}/problems/${latestQuestion.problemid}/image`} alt="课堂题目课件" onError={event => { event.currentTarget.style.display = 'none' }} /></details>}</section>}
      <section className="console-panel"><div className="panel-heading inline"><div><h2>课堂动态</h2><p>服务器接受的答案 {accepted} 条 · 最近 {events.length} 条记录</p></div><select className="console-input compact-select" aria-label="筛选事件" value={filter} onChange={e => setFilter(e.target.value)}><option value="important">关键事件</option><option value="errors">需要关注</option><option value="all">全部记录</option></select></div><div className="event-timeline">{recent.slice(0, 60).map((event, index) => <article className={`timeline-item ${errorStates.has(event.status || '') ? 'is-error' : ''}`} key={`${event.logged_at}-${index}`}><div className="timeline-marker" /><div className="timeline-content"><div><strong>{eventTitle(event)}</strong><time>{event.logged_at?.slice(11, 19)}</time></div>{event.lesson && <small>{event.lesson}</small>}<p>{event.message || statusName(event.status)}</p>{event.answers !== undefined && <span className="event-answer">答案 {answers(event.answers)}</span>}<details><summary>详情</summary><pre>{JSON.stringify(event, null, 2)}</pre></details></div></article>)}{!recent.length && <div className="console-empty compact">等待新的课堂事件。</div>}</div></section></div>
      <aside className="console-stack"><section className="console-panel"><div className="panel-heading"><h2>运行方式</h2><p>修改后保存，才会影响后续运行</p></div><ModeControl value={draft} onChange={edit} /><div className="panel-actions"><span className="muted">{dirty ? '有尚未保存的修改' : '与当前设置一致'}</span><button className="console-button" disabled={busy === 'save' || !dirty} onClick={save}>{busy === 'save' ? '保存中…' : '保存设置'}</button></div></section><section className="console-panel subtle"><h3>怎么看提交结果</h3><ol className="result-guide"><li><b>AI 已生成</b><span>只说明答案格式有效</span></li><li><b>等待服务器确认</b><span>已发出请求，还没有确认结果</span></li><li><b>服务器已接受</b><span>HTTP 成功且业务 code=0</span></li></ol><p className="muted">结果未知时会保留记录并停止重发，便于你到雨课堂核对。</p></section></aside></div>}
    {tab === 'courses' && <section className="console-panel"><div className="panel-heading inline"><div><h2>选择要处理的班级</h2><p>只对选中班级执行当前运行方式；空列表不进入任何课堂。</p></div><button className="console-button secondary" onClick={async () => { const r = await api<{ ok: boolean; error?: string }>('/api/courses/refresh', {}); setMessage(r.ok ? '课程已同步' : r.error || '课程刷新失败'); refresh() }}>同步课程</button></div><CoursePicker courses={courses} selected={draft.course_ids} onChange={ids => edit({ ...draft, course_ids: ids })} /><div className="panel-actions"><span className="muted">{dirty ? '课程范围尚未保存' : '范围已保存'}</span><button className="console-button" disabled={!dirty || busy === 'save'} onClick={save}>保存课程范围</button></div></section>}
    {tab === 'model' && <section className="console-panel model-panel"><div className="panel-heading"><h2>模型连接</h2><p>使用视觉模型获取题图信息。密钥只保存在本机，界面显示掩码。</p></div><ModelPanel ai={ai} health={health} onChanged={refresh} notify={setMessage} /></section>}
    {tab === 'checks' && <div className="console-stack"><section className="console-panel"><div className="panel-heading inline"><div><span className="console-eyebrow">本机模拟 · 真实课堂请求 0</span><h2>题型与提交链路自检</h2><p>独立进程运行模拟 AI 与本机 HTTP 服务，不修改账号配置，不发送课堂答案。</p></div><button className="console-button" disabled={busy === 'test'} onClick={selfTest}>{busy === 'test' ? '正在逐项自检…' : '运行全部自检'}</button></div>{diagnostic ? <><div className="diagnostic-summary"><strong>{diagnostic.passed}<i> / {diagnostic.total}</i></strong><div><b>{diagnostic.ok ? '全部模拟场景通过' : '部分场景需要检查'}</b><p>耗时 {diagnostic.elapsed_seconds} 秒 · 模拟服务接受不代表真实课堂已接受</p></div></div><div className="diagnostic-grid">{diagnostic.cases.map(item => <details key={item.id} className="diagnostic-case"><summary><span className={item.passed ? 'pass-check' : 'fail-check'}>{item.passed ? '✓' : '!'}</span><strong>{item.label}</strong><small>{item.requests} 次模拟提交</small></summary><p>处理结果：{statusName(item.actual)}</p><pre>{JSON.stringify(item.payload, null, 2)}</pre></details>)}</div></> : <div className="console-empty">运行后会分别展示单选、多选、投票、简答，以及失败、超时和重复事件的结果。</div>}</section><section className="console-panel"><h3>题型能力</h3><div className="capability-row">{Object.entries(TYPES).map(([id, text]) => <span key={id} className={`console-pill ${id === '4' ? 'amber' : 'blue'}`}>{text} · {id === '4' ? '未支持，明确跳过' : '已支持模拟提交'}</span>)}</div><p className="muted">真实业务接受、题型字段和判分仍以雨课堂响应为准。格式有效不保证 AI 答案正确。</p></section></div>}
    <section className="console-panel advanced-panel"><details><summary>高级运行选项 <span>扫描频率与时间预算</span></summary><div className="form-grid advanced-grid"><label>开课扫描间隔 / 秒<input className="console-input" type="number" min="10" max="120" value={draft.poll_interval} onChange={e => edit({ ...draft, poll_interval: +e.target.value })} /></label><label>AI 最长等待 / 秒<input className="console-input" type="number" min="5" max="180" value={draft.ai_timeout} onChange={e => edit({ ...draft, ai_timeout: +e.target.value })} /></label><label>提交预留 / 秒<input className="console-input" type="number" min="2" max="15" value={draft.submit_reserve} onChange={e => edit({ ...draft, submit_reserve: +e.target.value })} /></label></div><div className="panel-actions"><Link className="text-button" to="/settings">按课程设置题型策略 →</Link><button className="console-button" disabled={!dirty} onClick={save}>保存高级选项</button></div></details></section>
    <footer className="console-footer"><span>仅监听已加入的班级 · 关闭页面后程序继续运行</span><span>本机 {health?.domain} · v{health?.version || '2.1.0'}</span></footer>
  </div>
}
