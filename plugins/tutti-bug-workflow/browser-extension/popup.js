const dot = document.getElementById("dot");
const state = document.getElementById("state");
const hint = document.getElementById("hint");
const list = document.getElementById("pages");

function render({ native, pages }) {
  dot.classList.toggle("ok", native.connected);
  state.textContent = native.connected ? "本机 bridge 已连接" : "本机 bridge 未连接";
  hint.textContent = native.connected
    ? `bridge ${native.hubVersion ?? ""}，Agent 可读取下面的 Tutti 页面`
    : `${native.error ?? "正在连接"}。请在 Codex 中运行 bug-setup 安装本机 bridge。`;
  list.replaceChildren();
  if (pages.length === 0) {
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "没有已登录的 Tutti 页面（*.tutti.sh）。";
    list.append(empty);
  }
  for (const page of pages.sort((a, b) => Number(b.active) - Number(a.active))) {
    const item = document.createElement("div");
    item.className = "page";
    const title = document.createElement("div");
    title.className = "page-title";
    title.textContent = page.title || page.url;
    const meta = document.createElement("div");
    meta.className = "hint";
    meta.textContent = page.connectionUrl ? page.url : `${page.url}（未登录或页面不含诊断能力）`;
    item.append(title, meta);
    if (page.connectionUrl) {
      const button = document.createElement("button");
      button.textContent = "复制连接链接";
      button.addEventListener("click", async () => {
        await navigator.clipboard.writeText(page.connectionUrl);
        button.textContent = "已复制";
      });
      item.append(button);
    }
    list.append(item);
  }
}

chrome.runtime.sendMessage({ type: "status" }).then(render);
