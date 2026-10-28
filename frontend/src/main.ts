import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./components/WebGate.vue";
import "./style.css";
createApp(App).use(createPinia()).mount("#app");
