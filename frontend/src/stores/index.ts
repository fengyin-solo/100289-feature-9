import { createPinia } from 'pinia'

/** 单独引出 pinia 实例，让 api/client 这类非组件模块也能用 store。 */
export const pinia = createPinia()
