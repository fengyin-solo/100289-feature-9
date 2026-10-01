import { defineStore } from 'pinia'

/** 登录身份：班组与角色决定保养记录能不能改（后端按同样的头再校一遍）。 */
export type Identity = {
  name: string
  team: string
  role: '管理员' | '操作人员'
}

export const IDENTITY_PRESETS: Record<string, Identity> = {
  adminA: { name: '一班管理员', team: '一班', role: '管理员' },
  operatorA: { name: '一班小王', team: '一班', role: '操作人员' },
  adminB: { name: '二班管理员', team: '二班', role: '管理员' },
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    identity: { ...IDENTITY_PRESETS.adminA } as Identity,
    operator: '一班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '园林绿化养护管理平台',
  }),
  getters: {
    canOperate: (state) => state.identity.name.length > 0,
    isAdmin: (state) => state.identity.role === '管理员',
  },
  actions: {
    setIdentity(identity: Identity) {
      this.identity = { ...identity }
      this.operator = identity.name
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
    authHeaders(): Record<string, string> {
      return {
        'X-Operator': this.identity.name,
        'X-Team': this.identity.team,
        'X-Role': this.identity.role,
      }
    },
  },
})
