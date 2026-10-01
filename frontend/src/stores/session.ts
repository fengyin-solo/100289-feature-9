import { defineStore } from 'pinia'

/** 可切换的演示身份：保养记录只允许本班组管理员改动，用来演示跨班组拦截。 */
export interface Identity {
  name: string
  role: '管理员' | '操作人员'
  team: string
}

export const IDENTITIES: Identity[] = [
  { name: '王建国', role: '管理员', team: '绿化一班' },
  { name: '李秀兰', role: '管理员', team: '绿化二班' },
  { name: '赵大力', role: '操作人员', team: '绿化一班' },
]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '王建国',
    role: '管理员' as Identity['role'],
    team: '绿化一班',
    shiftLabel: '白班 08:00-20:00',
    scope: '园林绿化养护管理平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isAdmin: (state) => state.role === '管理员',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setIdentity(identity: Identity) {
      this.operator = identity.name
      this.role = identity.role
      this.team = identity.team
    },
  },
})
