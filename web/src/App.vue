<script setup lang="ts">
import { NButton, NConfigProvider, NTag, darkTheme, zhCN as naiveZhCN, dateZhCN } from "naive-ui";

import { zhCN } from "./locales/zh-CN";
</script>

<template>
  <NConfigProvider :theme="darkTheme" :locale="naiveZhCN" :date-locale="dateZhCN">
    <main class="shell">
      <nav class="nav" aria-label="主导航">
        <a class="wordmark" href="/" :aria-label="zhCN.brand">
          <span class="wordmark-mark" aria-hidden="true">D</span>
          {{ zhCN.brand }}
        </a>
        <NButton tertiary size="small">{{ zhCN.settings }}</NButton>
      </nav>

      <section class="hero" aria-labelledby="hero-title">
        <div class="hero-copy">
          <p class="eyebrow"><span></span>{{ zhCN.eyebrow }}</p>
          <h1 id="hero-title">{{ zhCN.heading }}</h1>
          <p class="intro">{{ zhCN.body }}</p>
        </div>

        <aside class="status-panel" aria-label="工程状态">
          <div class="status-heading">
            <span>{{ zhCN.baseStatus }}</span>
            <NTag round size="small" :bordered="false">{{ zhCN.stageZero }}</NTag>
          </div>
          <dl>
            <div>
              <dt>{{ zhCN.server }}</dt>
              <dd><i class="signal signal-waiting"></i>{{ zhCN.serverReady }}</dd>
            </div>
            <div>
              <dt>{{ zhCN.api }}</dt>
              <dd><i class="signal"></i>{{ zhCN.apiVersion }}</dd>
            </div>
            <div>
              <dt>{{ zhCN.content }}</dt>
              <dd><i class="signal signal-muted"></i>{{ zhCN.contentPending }}</dd>
            </div>
          </dl>
        </aside>
      </section>

      <footer>
        <span>{{ zhCN.footer }}</span>
        <span class="coordinate">DKR / 00</span>
      </footer>
    </main>
  </NConfigProvider>
</template>
