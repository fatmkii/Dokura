<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, ApiError } from "../api";
import { zhCN } from "../locales/zh-CN";

const route = useRoute();
const router = useRouter();
const username = ref("admin");
const password = ref("");
const loading = ref(false);
const error = ref("");

async function submit(): Promise<void> {
  if (!username.value || !password.value) return;
  loading.value = true;
  error.value = "";
  try {
    const result = await api.login(username.value, password.value);
    if (result.default_password) sessionStorage.setItem("dokura-default-password", "true");
    const redirect = typeof route.query.redirect === "string" && route.query.redirect.startsWith("/")
      ? route.query.redirect
      : "/";
    // Chromium may resolve fetch just before committing an HttpOnly Set-Cookie.
    // Confirm the cookie on the same origin before App.vue checks the session.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        await api.session();
        break;
      } catch (reason) {
        if (!(reason instanceof ApiError) || reason.status !== 401 || attempt === 2) throw reason;
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    }
    sessionStorage.setItem("dokura-login-handoff", "true");
    await router.replace(redirect);
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : zhCN.connectFailed;
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-intro" aria-labelledby="login-title">
      <div class="login-wordmark"><span>D</span>{{ zhCN.brand }}</div>
      <p class="eyebrow">{{ zhCN.loginEyebrow }}</p>
      <h1 id="login-title">{{ zhCN.loginTitleFirst }}<br />{{ zhCN.loginTitleSecond }}</h1>
      <p>{{ zhCN.loginBodyFirst }}<br />{{ zhCN.loginBodySecond }}</p>
      <i aria-hidden="true">DKR — 04</i>
    </section>
    <section class="login-form-wrap">
      <form class="login-form" @submit.prevent="submit">
        <header>
          <span>01</span>
          <div><h2>{{ zhCN.login }}</h2><p>{{ zhCN.loginHint }}</p></div>
        </header>
        <label>{{ zhCN.username }}<input v-model="username" name="username" autocomplete="username" required /></label>
        <label>{{ zhCN.password }}<input v-model="password" name="password" type="password" autocomplete="current-password" required autofocus /></label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="primary-button" type="submit" :disabled="loading || !username || !password">
          {{ loading ? zhCN.verifying : zhCN.loginAction }}<span aria-hidden="true">→</span>
        </button>
      </form>
    </section>
  </main>
</template>
