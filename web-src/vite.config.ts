import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

/* 构建产物直接写进 ../web/，main.py 原样当静态目录发出去，
   所以 clone 下来仍然只要「构建一次 + python main.py」就能跑。
   （这里刻意不用 node:url —— 相对路径 Vite 自己会按 root 解析，
     省掉一个 @types/node 依赖。） */
export default defineConfig({
  plugins: [vue()],
  base: "./",
  resolve: {
    alias: {
      "@": "/src",
    },
  },
  build: {
    outDir: "../web",
    /* web/ 现在只剩下构建产物（源码都在 web-src/），
       所以每次构建前清空，免得旧 hash 文件越堆越多。 */
    emptyOutDir: true,
    assetsDir: "assets",
    target: "es2020",
    cssCodeSplit: false,
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
  server: {
    port: 5273,
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
});
