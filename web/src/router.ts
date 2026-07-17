import { createRouter, createWebHistory } from "vue-router";

import CatalogView from "./views/CatalogView.vue";
import DetailView from "./views/DetailView.vue";
import LoginView from "./views/LoginView.vue";
import ReaderView from "./views/ReaderView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "catalog", component: CatalogView },
    { path: "/login", name: "login", component: LoginView, meta: { public: true } },
    { path: "/files/:id", name: "detail", component: DetailView },
    { path: "/reader/:id/:page(\\d+)", name: "reader", component: ReaderView, meta: { immersive: true } },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition;
    if (to.name === from.name && to.name === "catalog") return false;
    return { top: 0 };
  },
});
