<template>
  <section class="page" data-module="equipment">
    <header class="page-head">
      <div>
        <h2>园林机械管理</h2>
        <p class="page-desc">
          下次保养日 = 上次保养 + 类型周期；距保养不足 5 天或已超期禁止调度并说明缘由，超龄另作提示；
          已报废不排班，保养记录仅本班组管理员可改，同机重复保养只认第一回。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记园林机械</button>
        <button class="btn" type="button" @click="exportRows">导出园林机械清单</button>
      </div>
    </header>

    <div class="identity-bar">
      <span class="filter-item"><span>切换身份（验证权限口径）</span></span>
      <select v-model="identityKey" @change="onIdentityChange">
        <option value="adminA">一班管理员（本班组管理员）</option>
        <option value="operatorA">一班操作人员（非管理员）</option>
        <option value="adminB">二班管理员（跨班组管理员）</option>
      </select>
      <span class="identity-hint">
        当前：{{ session.identity.team }} · {{ session.identity.role }} · {{ session.identity.name }}
      </span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'" class="action-message">{{ message }}</span>
    </div>

    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="item.cls">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 调度看板 -->
    <div v-if="activeTab === 'board'">
      <p class="page-desc">
        看板日期 {{ board.today }}；已报废机械已剔除，禁排机械置顶。看板保养日与台账由同一口径实时算出。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in boardColumns" :key="column">{{ column }}</th>
            <th>调度操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in board.items" :key="String(row.id)" :class="{ 'row-blocked': !row.可调度 }">
            <td v-for="column in boardColumns" :key="column">
              <span v-if="column === '保养口径'" class="badge" :class="badgeClass(row.保养口径)">{{ row.保养口径 }}</span>
              <span v-else-if="column === '调度说明'" class="dispatch-note">
                {{ row.调度说明 }}
                <div v-if="row.超龄提示 && !String(row.调度说明 ?? '').includes('超龄')" class="warn-text">{{ row.超龄提示 }}</div>
              </span>
              <span v-else>{{ formatCell(row[column], column) }}</span>
            </td>
            <td>
              <button class="link" type="button" @click="runAction('调度使用', row)">调度使用</button>
            </td>
          </tr>
          <tr v-if="!board.items.length">
            <td :colspan="boardColumns.length + 1" class="empty-state">暂无可排班机械</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 台账 -->
    <div v-else-if="activeTab === 'ledger'">
      <form class="filter-bar" @submit.prevent="reloadLedger">
        <label class="filter-item">
          <span>机械编号</span>
          <input v-model="ledgerFilters.keyword" placeholder="按机械编号检索" />
        </label>
        <label class="filter-item">
          <span>状态</span>
          <select v-model="ledgerFilters.status">
            <option value="">全部</option>
            <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>机械类型</span>
          <select v-model="ledgerFilters.machine_type">
            <option value="">全部</option>
            <option v-for="t in types" :key="t.机械类型" :value="t.机械类型">{{ t.机械类型 }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetLedgerFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in ledgerColumns" :key="column">
              <span v-if="column === '保养口径'" class="badge" :class="badgeClass(row.保养口径)">{{ row.保养口径 }}</span>
              <span v-else>{{ formatCell(row[column], column) }}</span>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="runAction('调度使用', row)">调度使用</button>
              <button class="link" type="button" @click="openRegister(row)">登记保养</button>
              <button class="link danger" type="button" @click="runAction('申请报废', row)">申请报废</button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="ledgerColumns.length + 1" class="empty-state">暂无符合条件的园林机械</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>共 {{ total }} 条园林机械记录</span></footer>
    </div>

    <!-- 保养记录 -->
    <div v-else-if="activeTab === 'records'">
      <form class="filter-bar" @submit.prevent="reloadRecords">
        <label class="filter-item">
          <span>机械编号</span>
          <input v-model="recordKeyword" placeholder="按机械编号检索" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn primary" type="button" @click="openRegister()">登记保养</button>
      </form>
      <p class="page-desc">
        保养记录只允许本班组管理员登记；同一台机械同一天重复保养只认第一回，重复提交会被直接拒绝。
      </p>
      <table class="data-table">
        <thead>
          <tr><th v-for="column in recordColumns" :key="column">{{ column }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in records" :key="String(row.id)">
            <td v-for="column in recordColumns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!records.length">
            <td :colspan="recordColumns.length" class="empty-state">暂无保养记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 类型阈值 -->
    <div v-else-if="activeTab === 'types'">
      <p class="page-desc">
        不同机械类型各自配置保养周期、年限上限与提前提醒天数；调整后立即重算全部在册机械的下次保养日。
      </p>
      <div v-if="!session.isAdmin" class="warn-banner">当前身份不是管理员，阈值为只读；请切换到管理员身份再调整。</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>机械类型</th>
            <th>保养周期（天）</th>
            <th>年限上限（年）</th>
            <th>提前提醒（天）</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rule in types" :key="rule.机械类型">
            <td>{{ rule.机械类型 }}</td>
            <td><input v-model.number="ruleDraft[rule.机械类型].保养周期天数" class="num-input" type="number" min="1" :disabled="!session.isAdmin" /></td>
            <td><input v-model.number="ruleDraft[rule.机械类型].年限上限年数" class="num-input" type="number" min="1" :disabled="!session.isAdmin" /></td>
            <td><input v-model.number="ruleDraft[rule.机械类型].提醒提前天数" class="num-input" type="number" min="1" :disabled="!session.isAdmin" /></td>
            <td>
              <button class="link" type="button" :disabled="!session.isAdmin" @click="saveType(rule.机械类型)">保存并重算</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 登记保养弹层 -->
    <div v-if="registerForm.visible" class="modal-mask" @click.self="registerForm.visible = false">
      <div class="modal">
        <h3>登记保养</h3>
        <label class="form-item"><span>机械编号</span><input v-model="registerForm.机械编号" placeholder="如 EQUI-0001" /></label>
        <label class="form-item"><span>保养日期</span><input v-model="registerForm.保养日期" type="date" /></label>
        <label class="form-item"><span>保养内容</span><input v-model="registerForm.保养内容" placeholder="如 换机油、检查刀片" /></label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="registerForm.visible = false">取消</button>
          <button class="btn primary" type="button" @click="submitRegister">提交登记</button>
        </div>
      </div>
    </div>

    <!-- 登记机械弹层 -->
    <div v-if="createForm.visible" class="modal-mask" @click.self="createForm.visible = false">
      <div class="modal">
        <h3>登记园林机械</h3>
        <label class="form-item"><span>机械编号</span><input v-model="createForm.机械编号" /></label>
        <label class="form-item"><span>机械名称</span><input v-model="createForm.机械名称" /></label>
        <label class="form-item">
          <span>机械类型</span>
          <select v-model="createForm.机械类型">
            <option value="">请选择</option>
            <option v-for="t in types" :key="t.机械类型" :value="t.机械类型">{{ t.机械类型 }}</option>
          </select>
        </label>
        <label class="form-item"><span>规格型号</span><input v-model="createForm.规格型号" /></label>
        <label class="form-item"><span>购置日期</span><input v-model="createForm.购置日期" type="date" /></label>
        <label class="form-item">
          <span>所属班组</span>
          <select v-model="createForm.所属班组">
            <option>一班</option>
            <option>二班</option>
          </select>
        </label>
        <label class="form-item"><span>操作人员</span><input v-model="createForm.操作人员" /></label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="createForm.visible = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">提交登记</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { requestJson } from '@/api/client'
import { IDENTITY_PRESETS, useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>
type Rule = { 机械类型: string; 保养周期天数: number; 年限上限年数: number; 提醒提前天数: number }
type ActionPayload = { values: Record<string, string> }

const ENDPOINT = '/api/equipment'
const session = useSessionStore()

const tabs = [
  { key: 'board', label: '调度看板' },
  { key: 'ledger', label: '机械台账' },
  { key: 'records', label: '保养记录' },
  { key: 'types', label: '类型阈值' },
] as const

const boardColumns = [
  '机械编号', '机械名称', '机械类型', '所属班组', '操作人员', '上次保养', '下次保养日',
  '距保养天数', '保养口径', '机龄', '调度说明',
]
const ledgerColumns = [
  '机械编号', '机械名称', '机械类型', '规格型号', '购置日期', '机龄', '所属班组', '操作人员',
  '上次保养', '下次保养日', '距保养天数', '保养口径', 'status',
]
const recordColumns = ['id', '机械编号', '保养日期', '保养内容', '登记人', '所属班组']
const statuses = ['可用', '使用中', '保养中', '已报废']

const activeTab = ref<(typeof tabs)[number]['key']>('board')
const rows = ref<Row[]>([])
const total = ref(0)
const records = ref<Row[]>([])
const types = ref<Rule[]>([])
const ruleDraft = reactive<Record<string, Rule>>({})
const board = ref<{ today: string; items: Row[]; summary: Record<string, number> }>({
  today: '',
  items: [],
  summary: {},
})
const message = ref('')
const messageOk = ref(true)
const recordKeyword = ref('')
const ledgerFilters = reactive({ keyword: '', status: '', machine_type: '' })
const identityKey = ref('adminA')

const todayISO = () => new Date().toISOString().slice(0, 10)

const registerForm = reactive({
  visible: false,
  机械编号: '',
  保养日期: todayISO(),
  保养内容: '',
})
const createForm = reactive({
  visible: false,
  机械编号: '',
  机械名称: '',
  机械类型: '',
  规格型号: '',
  购置日期: todayISO(),
  所属班组: '一班',
  操作人员: '',
})

const stats = computed(() => {
  const s = board.value.summary
  return [
    { label: '参与排班', value: s['参与排班'] ?? 0, cls: '' },
    { label: '可调度', value: s['可调度'] ?? 0, cls: 'stat-ok' },
    { label: '禁止调度', value: s['禁止调度'] ?? 0, cls: 'stat-bad' },
    { label: '超龄提示', value: s['超龄提示'] ?? 0, cls: 'stat-warn' },
    { label: '已报废剔除', value: s['已报废剔除'] ?? 0, cls: 'stat-muted' },
  ]
})

function showMessage(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function badgeClass(verdict: unknown): string {
  switch (verdict) {
    case '保养正常':
      return 'badge-ok'
    case '临近保养':
      return 'badge-warn'
    case '已超期':
      return 'badge-bad'
    case '已报废':
      return 'badge-muted'
    default:
      return 'badge-unknown'
  }
}

function formatCell(value: unknown, column: string): string {
  if (value === null || value === undefined || value === '') return '—'
  if (column === '距保养天数') {
    const n = Number(value)
    if (n < 0) return `已超期 ${-n} 天`
    return `剩 ${n} 天`
  }
  return String(value)
}

async function loadBoard() {
  const payload = await requestJson<{ today: string; items: Row[]; summary: Record<string, number> }>(
    `${ENDPOINT}/dispatch/board`,
  )
  board.value = payload
}

async function loadTypes() {
  const payload = await requestJson<{ items: Rule[] }>(`${ENDPOINT}/types`)
  types.value = payload.items
  for (const rule of payload.items) {
    ruleDraft[rule.机械类型] = { ...rule }
  }
}

async function reloadLedger() {
  const query = new URLSearchParams()
  if (ledgerFilters.keyword) query.set('keyword', ledgerFilters.keyword)
  if (ledgerFilters.status) query.set('status', ledgerFilters.status)
  if (ledgerFilters.machine_type) query.set('machine_type', ledgerFilters.machine_type)
  const payload = await requestJson<{ items: Row[]; total: number }>(`${ENDPOINT}?${query.toString()}`)
  rows.value = payload.items
  total.value = payload.total
}

function resetLedgerFilters() {
  ledgerFilters.keyword = ''
  ledgerFilters.status = ''
  ledgerFilters.machine_type = ''
  void reloadLedger()
}

async function reloadRecords() {
  const query = new URLSearchParams()
  if (recordKeyword.value) query.set('keyword', recordKeyword.value)
  const payload = await requestJson<{ items: Row[] }>(`${ENDPOINT}/maintenance/records?${query.toString()}`)
  records.value = payload.items
}

async function refreshAll() {
  // 任何写操作后全量刷新：看板、台账、保养记录共用后端同一口径，不会出现两边对不上。
  await Promise.all([loadBoard(), reloadLedger(), reloadRecords(), loadTypes()])
}

async function switchTab(key: (typeof tabs)[number]['key']) {
  activeTab.value = key
  await safeRefresh()
}

async function safeRefresh() {
  try {
    await refreshAll()
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '数据加载失败', false)
  }
}

async function runAction(action: string, row: Row) {
  try {
    const body: ActionPayload = { values: { action } }
    const result = await requestJson<{ ok: boolean; message: string }>(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    showMessage(result.message, true)
    await refreshAll()
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '操作失败', false)
    await refreshAll()
  }
}

function openRegister(row?: Row) {
  registerForm.机械编号 = row ? String(row.机械编号 ?? '') : ''
  registerForm.保养日期 = todayISO()
  registerForm.保养内容 = ''
  registerForm.visible = true
}

async function submitRegister() {
  try {
    const body: ActionPayload = {
      values: {
        机械编号: registerForm.机械编号,
        保养日期: registerForm.保养日期,
        保养内容: registerForm.保养内容,
      },
    }
    const result = await requestJson<{ message: string }>(`${ENDPOINT}/maintenance/register`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    registerForm.visible = false
    showMessage(result.message, true)
    await refreshAll()
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '保养登记失败', false)
  }
}

function openCreate() {
  Object.assign(createForm, {
    机械编号: '',
    机械名称: '',
    机械类型: types.value[0]?.机械类型 ?? '',
    规格型号: '',
    购置日期: todayISO(),
    所属班组: '一班',
    操作人员: '',
  })
  createForm.visible = true
}

async function submitCreate() {
  try {
    const { visible: _visible, ...values } = createForm
    const result = await requestJson<{ message: string }>(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    createForm.visible = false
    showMessage(result.message, true)
    await refreshAll()
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '登记失败', false)
  }
}

async function saveType(typeName: string) {
  const draft = ruleDraft[typeName]
  try {
    const result = await requestJson<{ message: string }>(`${ENDPOINT}/types/${encodeURIComponent(typeName)}`, {
      method: 'PUT',
      body: JSON.stringify({ values: draft }),
    })
    showMessage(result.message, true)
    await refreshAll()
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '阈值调整失败', false)
  }
}

function onIdentityChange() {
  session.setIdentity(IDENTITY_PRESETS[identityKey.value])
  showMessage(`已切换为 ${session.identity.team} · ${session.identity.role}`, true)
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

onMounted(safeRefresh)
</script>
