<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">园林绿化养护管理平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向城市园林绿化植物的栽植养护、修剪造型、病虫害防治、灌溉施肥与绿地巡查的一体化绿化管理后台。</span>
        <span class="head-user">当前值班：{{ store.identity.name }} · {{ store.identity.team }} · {{ store.identity.role }} · {{ store.shiftLabel }}</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

const navItems = [{ label: "运营概览", path: "/" }, { label: "绿地台账", path: "/plot" }, { label: "乔木管理", path: "/tree" }, { label: "灌木管理", path: "/shrub" }, { label: "草坪管理", path: "/lawn" }, { label: "花卉造景", path: "/flower" }, { label: "病虫害防治", path: "/pest" }, { label: "灌溉作业", path: "/irrigation" }, { label: "施肥作业", path: "/fertilize" }, { label: "修剪造型", path: "/prune" }, { label: "绿地巡查", path: "/patrol" }, { label: "杂草清除", path: "/weed" }, { label: "树木支撑", path: "/support" }, { label: "苗木移植", path: "/transplant" }, { label: "园建设施", path: "/facility" }, { label: "园林机械", path: "/equipment" }, { label: "苗木基地", path: "/seedling" }, { label: "水体养护", path: "/waterbody" }, { label: "名木古树", path: "/code" }, { label: "市民热线", path: "/complaint" }, { label: "季度养护方案", path: "/seasonplan" }]
</script>
