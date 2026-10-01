<template>
  <section class="page" data-module="equipment">
    <header class="page-head">
      <div>
        <h2>园林机械管理</h2>
        <p class="page-desc">
          下次保养日 = 上次保养 + 类型保养周期；距保养不足 5 天或已超期的机械禁止调度，
          超龄机械另作提示；已报废不参与排班。保养记录仅本班组管理员可改。
        </p>
      </div>
      <div class="page-actions">
        <label class="identity-box">
          <span>当前身份</span>
          <select :value="identityKey" @change="switchIdentity(($event.target as HTMLSelectElement).value)">
            <option v-for="(item, index) in IDENTITIES" :key="`${item.team}-${item.name}`" :value="String(index)">
              {{ item.name }}（{{ item.role }}·{{ item.team }}）
            </option>
          </select>
        </label>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.danger ? 'stat-danger' : ''">{{ item.value }}</strong>
      </article>
    </div>

    <nav class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <p v-if="message" class="form-msg" :class="messageOk ? 'msg-ok' : 'msg-error'">{{ message }}</p>

    <!-- 机械台账 -->
    <template v-if="activeTab === 'ledger'">
      <form class="filter-bar" @submit.prevent="reloadLedger">
        <label class="filter-item">
          <span>关键字</span>
          <input v-model="filters.keyword" placeholder="按机械编号/名称检索" />
        </label>
        <label class="filter-item">
          <span>机械类型</span>
          <select v-model="filters.eq_type">
            <option value="">全部类型</option>
            <option v-for="t in typeNames" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>班组</span>
          <select v-model="filters.team">
            <option value="">全部班组</option>
            <option v-for="t in teamNames" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
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
              <template v-if="column === '保养判定'">
                <span class="badge" :class="flagClass(String(row[column]))">{{ row[column] }}</span>
              </template>
              <template v-else-if="column === '超龄提示'">
                <span v-if="row[column]" class="warn-text" :title="String(row[column] ?? '')">超龄⚠</span>
                <span v-else>—</span>
              </template>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
            <td class="row-actions">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="ledgerColumns.length + 1" class="empty-state">暂无符合条件的园林机械</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>共 {{ total }} 条机械台账（保养日由后台统一口径计算）</span></footer>
    </template>

    <!-- 调度看板 -->
    <template v-else-if="activeTab === 'board'">
      <p class="page-desc">看板与台账调用同一套保养口径；已报废机械已剔除。</p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in boardColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in board" :key="String(row['机械编号'])" :class="{ 'row-blocked': !row['允许调度'] }">
            <td v-for="column in boardColumns" :key="column">
              <template v-if="column === '允许调度'">
                <span class="badge" :class="row[column] ? 'badge-ok' : 'badge-block'">
                  {{ row[column] ? '允许' : '禁排' }}
                </span>
              </template>
              <template v-else-if="column === '保养判定'">
                <span class="badge" :class="flagClass(String(row[column]))">{{ row[column] }}</span>
              </template>
              <template v-else-if="column === '缘由'">
                <span v-if="row[column]" class="block-reason">{{ row[column] }}</span>
                <span v-else class="ok-text">可正常调度</span>
              </template>
              <template v-else-if="column === '超龄提示'">
                <span v-if="row[column]" class="warn-text">{{ row[column] }}</span>
                <span v-else>—</span>
              </template>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- 保养记录 -->
    <template v-else-if="activeTab === 'maintenance'">
      <form class="filter-bar" @submit.prevent="reloadMaintenance">
        <label class="filter-item">
          <span>机械编号</span>
          <input v-model="maintFilter.code" placeholder="留空查全部" />
        </label>
        <label class="filter-item">
          <span>只看有效</span>
          <input v-model="maintFilter.onlyValid" type="checkbox" @change="reloadMaintenance" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>

      <form class="editor-card" @submit.prevent="submitMaintenance">
        <h4>登记保养（登记后自动重算下次保养日）</h4>
        <label class="filter-item">
          <span>机械编号</span>
          <select v-model="maintForm.code" required>
            <option value="" disabled>请选择机械</option>
            <option v-for="row in rows" :key="String(row.id)" :value="String(row['机械编号'])">
              {{ row['机械编号'] }} · {{ row['机械名称'] }}（{{ row['所属班组'] }}）
            </option>
          </select>
        </label>
        <label class="filter-item">
          <span>保养日期</span>
          <input v-model="maintForm.date" type="date" required />
        </label>
        <label class="filter-item grow">
          <span>保养内容</span>
          <input v-model="maintForm.content" placeholder="如：更换刀片、加注润滑脂" required />
        </label>
        <button class="btn primary" type="submit">提交保养</button>
        <p class="form-hint">以「{{ store.operator }}（{{ store.role }}·{{ store.team }}）」身份提交；非本班组管理员会被拦下。</p>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in maintenanceColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in maintenanceRows" :key="String(row.id)" :class="{ 'row-void': !row['有效'] }">
            <td v-for="column in maintenanceColumns" :key="column">
              <template v-if="column === '有效'">
                <span class="badge" :class="row[column] ? 'badge-ok' : 'badge-void'">
                  {{ row[column] ? '有效（第一回）' : '作废（重复）' }}
                </span>
              </template>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
          </tr>
          <tr v-if="!maintenanceRows.length">
            <td :colspan="maintenanceColumns.length" class="empty-state">暂无保养记录</td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- 判定标准 -->
    <template v-else>
      <p class="page-desc">
        不同机械类型分别配置保养周期与使用年限上限；保存后后台会全量重算已有保养记录与台账保养日。
      </p>
      <table class="data-table">
        <thead>
          <tr><th>机械类型</th><th>保养周期（天）</th><th>使用年限上限（年）</th></tr>
        </thead>
        <tbody>
          <tr v-for="rule in ruleDraft" :key="String(rule['机械类型'])">
            <td>{{ rule['机械类型'] }}</td>
            <td><input v-model.number="rule['保养周期天数']" type="number" min="1" /></td>
            <td><input v-model.number="rule['使用年限上限']" type="number" min="1" /></td>
          </tr>
        </tbody>
      </table>
      <div class="page-actions" style="margin-top: 12px">
        <button class="btn primary" type="button" @click="submitRules">保存并重算</button>
        <button class="btn ghost" type="button" @click="loadRules">放弃修改</button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { IDENTITIES, useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/equipment'
const store = useSessionStore()

const tabs = [
  { key: 'ledger', label: '机械台账' },
  { key: 'board', label: '调度看板' },
  { key: 'maintenance', label: '保养记录' },
  { key: 'rules', label: '判定标准' },
] as const
type TabKey = (typeof tabs)[number]['key']
const activeTab = ref<TabKey>('ledger')

const ledgerColumns = [
  '机械编号', '机械名称', '机械类型', '所属班组', '规格型号', '购置日期',
  '上次保养', '下次保养日', '保养判定', '距下次保养天数', '超龄提示',
  '操作人员', '机械状态',
]
const boardColumns = [
  '机械编号', '机械名称', '机械类型', '所属班组', '状态',
  '上次保养', '下次保养日', '保养判定', '超龄提示', '允许调度', '缘由',
]
const maintenanceColumns = ['id', '机械编号', '保养日期', '保养内容', '登记人', '登记班组', '有效', '作废原因']
const actions = ['安排保养', '调度使用', '申请报废']

const rows = ref<Row[]>([])
const total = ref(0)
const board = ref<Row[]>([])
const maintenanceRows = ref<Row[]>([])
const typeNames = ref<string[]>([])
const teamNames = ['绿化一班', '绿化二班']
const ruleDraft = ref<Row[]>([])

const filters = reactive({ keyword: '', eq_type: '', team: '' })
const maintFilter = reactive({ code: '', onlyValid: false })
const maintForm = reactive({ code: '', date: todayISO(), content: '' })

const message = ref('')
const messageOk = ref(true)

const identityKey = computed(() => {
  const index = IDENTITIES.findIndex(
    (item) => item.team === store.team && item.name === store.operator && item.role === store.role
  )
  return String(index < 0 ? 0 : index)
})

const stats = computed(() => {
  const totalCount = rows.value.length
  const near = rows.value.filter((r) => r['保养判定'] === '临近保养' || r['保养判定'] === '已超期').length
  const overAge = rows.value.filter((r) => r['超龄提示']).length
  const blockedBoard = board.value.filter((r) => !r['允许调度']).length
  return [
    { label: '在册机械', value: totalCount, danger: false },
    { label: '临近/超期保养', value: near, danger: near > 0 },
    { label: '超龄机械', value: overAge, danger: overAge > 0 },
    { label: '看板禁排', value: blockedBoard, danger: blockedBoard > 0 },
  ]
})

function todayISO(): string {
  const d = new Date()
  const m = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

function flagClass(flag: string): string {
  if (flag === '已超期') return 'badge-overdue'
  if (flag === '临近保养') return 'badge-near'
  if (flag === '正常') return 'badge-ok'
  return 'badge-muted'
}

function switchIdentity(key: string) {
  const found = IDENTITIES[Number(key)]
  if (found) {
    store.setIdentity(found)
    flash(`已切换身份：${found.name}（${found.role}·${found.team}）`, true)
  }
}

function switchTab(key: TabKey) {
  activeTab.value = key
  message.value = ''
  if (key === 'board') void reloadBoard()
  if (key === 'maintenance') void reloadMaintenance()
  if (key === 'rules') void loadRules()
}

function resetFilters() {
  filters.keyword = ''
  filters.eq_type = ''
  filters.team = ''
  void reloadLedger()
}

function flash(text: string, ok: boolean) {
  message.value = text
  messageOk.value = ok
}

async function reloadLedger() {
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.eq_type) query.set('eq_type', filters.eq_type)
  if (filters.team) query.set('team', filters.team)
  const response = await request(`${ENDPOINT}?${query.toString()}`)
  if (!response.ok) {
    flash('机械台账读取失败', false)
    return
  }
  const payload = await response.json()
  rows.value = payload.items ?? []
  total.value = payload.total ?? rows.value.length
  typeNames.value = [...new Set(rows.value.map((r) => String(r['机械类型'])).filter(Boolean))]
  await reloadBoard()
}

async function reloadBoard() {
  const response = await request(`${ENDPOINT}/dispatch-board`)
  if (!response.ok) return
  const payload = await response.json()
  board.value = payload.items ?? []
}

async function reloadMaintenance() {
  const query = new URLSearchParams()
  if (maintFilter.code) query.set('code', maintFilter.code)
  if (maintFilter.onlyValid) query.set('only_valid', 'true')
  const response = await request(`${ENDPOINT}/maintenance?${query.toString()}`)
  if (!response.ok) {
    flash('保养记录读取失败', false)
    return
  }
  const payload = await response.json()
  maintenanceRows.value = payload.items ?? []
}

async function loadRules() {
  const response = await request(`${ENDPOINT}/types`)
  if (!response.ok) {
    flash('判定标准读取失败', false)
    return
  }
  const payload = await response.json()
  ruleDraft.value = (payload.items ?? []).map((item: Row) => ({ ...item }))
}

async function postJSON(path: string, body: Record<string, unknown>) {
  return request(path, {
    method: 'POST',
    body: JSON.stringify({
      values: {
        ...body,
        操作人: store.operator,
        角色: store.role,
        班组: store.team,
      },
    }),
  })
}

async function runAction(action: string, row: Row) {
  const response = await postJSON(`${ENDPOINT}/${row.id}/actions`, { action })
  const payload = await response.json()
  flash(String(payload.message ?? ''), Boolean(payload.ok))
  await reloadLedger()
}

async function submitMaintenance() {
  const response = await postJSON(`${ENDPOINT}/maintenance`, {
    机械编号: maintForm.code,
    保养日期: maintForm.date,
    保养内容: maintForm.content,
  })
  const payload = await response.json()
  flash(String(payload.message ?? ''), Boolean(payload.ok))
  maintForm.content = ''
  await reloadLedger()
  await reloadMaintenance()
}

async function submitRules() {
  const response = await request(`${ENDPOINT}/types`, {
    method: 'PUT',
    body: JSON.stringify({
      values: {
        rules: ruleDraft.value,
        操作人: store.operator,
        角色: store.role,
        班组: store.team,
      },
    }),
  })
  const payload = await response.json()
  flash(String(payload.message ?? ''), Boolean(payload.ok))
  if (payload.ok) {
    await loadRules()
    await reloadLedger()
  }
}

onMounted(() => {
  void reloadLedger()
})
</script>

<style scoped>
.identity-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #555;
}
.identity-box select {
  min-width: 220px;
  padding: 6px 8px;
}
.tab-bar {
  display: flex;
  gap: 8px;
  margin: 12px 0;
  border-bottom: 1px solid #e3e3e3;
}
.tab-btn {
  border: none;
  background: none;
  padding: 8px 16px;
  cursor: pointer;
  font-size: 14px;
  color: #555;
  border-bottom: 2px solid transparent;
}
.tab-btn.active {
  color: #1f6f43;
  border-bottom-color: #1f6f43;
  font-weight: 600;
}
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  white-space: nowrap;
}
.badge-ok { background: #e6f6ec; color: #1f7a43; }
.badge-near { background: #fff4e0; color: #b26b00; }
.badge-overdue { background: #fde8e8; color: #c0392b; }
.badge-block { background: #fde8e8; color: #c0392b; }
.badge-void { background: #ececec; color: #777; }
.badge-muted { background: #f2f2f2; color: #888; }
.stat-danger { color: #c0392b; }
.warn-text { color: #b26b00; }
.ok-text { color: #1f7a43; }
.block-reason { color: #c0392b; font-size: 12px; }
.row-blocked { background: #fff8f8; }
.row-void { color: #999; background: #fafafa; }
.form-msg { padding: 8px 12px; border-radius: 4px; margin: 8px 0; font-size: 13px; }
.msg-ok { background: #e6f6ec; color: #1f7a43; }
.msg-error { background: #fde8e8; color: #c0392b; }
.editor-card {
  border: 1px solid #e3e3e3;
  border-radius: 6px;
  padding: 12px 16px;
  margin: 12px 0;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  background: #fcfcfc;
}
.editor-card h4 { width: 100%; margin: 0 0 4px; font-size: 14px; }
.editor-card .grow { flex: 1; min-width: 220px; }
.form-hint { width: 100%; font-size: 12px; color: #888; margin: 0; }
</style>
